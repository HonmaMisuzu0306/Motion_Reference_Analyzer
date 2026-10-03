use serde::{Deserialize, Serialize};
use std::{fs::{self, File}, io::{BufRead, BufReader, Write}, path::PathBuf,
    process::{Child, Command, Stdio}, sync::{Arc, Mutex, mpsc}, thread, time::{Duration, SystemTime, UNIX_EPOCH}};
#[cfg(windows)] use std::os::windows::process::CommandExt;

#[derive(Clone, Serialize)]
pub struct BackendStatus { pub status: String, pub endpoint: Option<String>, pub instance_id: String,
    pub owned: bool, pub message: String }
struct Inner { status: BackendStatus, child: Option<Child> }
pub struct Backend { inner: Arc<Mutex<Inner>>, pub log_path: PathBuf, resource: PathBuf, data: PathBuf }
#[derive(Deserialize)]
struct Ready { product: String, version: String, protocol: u32, instance_id: String, port: u16, pid: u32 }
fn matches(ready: &Ready, expected: &str, port: u16) -> bool {
    ready.product == "mra" && ready.version == "1.0.0" && ready.protocol == 1
        && ready.instance_id == expected && ready.port == port && ready.pid > 0
}
fn kill_owned(child: &mut Child) {
    #[cfg(windows)] { let mut cmd = Command::new("taskkill"); cmd.args(["/PID", &child.id().to_string(), "/T", "/F"]);
        cmd.creation_flags(0x08000000); let _ = cmd.output(); }
    let _ = child.kill(); let _ = child.wait();
}
impl Backend {
    pub fn new(resource: PathBuf, data: PathBuf) -> Self {
        Self { inner: Arc::new(Mutex::new(Inner { child: None, status: BackendStatus { status: "error".into(),
            endpoint: None, instance_id: String::new(), owned: false, message: "尚未启动".into() }})),
            log_path: data.join("logs/backend.log"), resource, data }
    }
    pub fn status(&self) -> BackendStatus {
        let mut inner = self.inner.lock().unwrap();
        if inner.status.status == "ready" {
            if let Some(child) = &mut inner.child {
                if let Ok(Some(code)) = child.try_wait() { inner.status.status = "error".into();
                    inner.status.endpoint = None; inner.status.message = format!("分析服务已退出 ({code})，请重试启动"); }
            }
        }
        inner.status.clone()
    }
    pub fn start(&self) -> BackendStatus {
        let mut inner = self.inner.lock().unwrap();
        if inner.status.status == "starting" || inner.status.status == "ready" { return inner.status.clone(); }
        if let Some(mut child) = inner.child.take() { kill_owned(&mut child); }
        let instance = format!("mra-{}-{}", std::process::id(), SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos());
        inner.status = BackendStatus { status: "starting".into(), endpoint: None, instance_id: instance.clone(),
            owned: true, message: "正在启动本地分析服务…".into() };
        let status = inner.status.clone(); drop(inner);
        let shared = self.inner.clone(); let data = self.data.clone(); let log_path = self.log_path.clone(); let resource = self.resource.clone();
        thread::spawn(move || {
            let result = (|| -> Result<String, String> {
                fs::create_dir_all(log_path.parent().unwrap()).map_err(|e| e.to_string())?;
                let log = Arc::new(Mutex::new(File::create(&log_path).map_err(|e| e.to_string())?));
                let mut command;
                if cfg!(debug_assertions) {
                    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
                    command = Command::new(root.join("core/.venv/Scripts/python.exe"));
                    command.args(["-m", "app.bootstrap"]).env("PYTHONPATH", root.join("core")).env("PYTHONUNBUFFERED", "1");
                } else { command = Command::new(resource.join("mra-core/mra-core.exe")); }
                command.arg("--data-dir").arg(&data).args(["--port", "0", "--instance-id", &instance]);
                command.current_dir(&data).stdout(Stdio::piped()).stderr(Stdio::piped());
                #[cfg(windows)] command.creation_flags(0x08000000);
                let mut owner=shared.lock().unwrap();
                if owner.status.instance_id!=instance || owner.status.status!="starting" { return Err("启动已取消".into()); }
                let mut child = command.spawn().map_err(|e| format!("无法启动分析服务：{e}"))?;
                let stdout = child.stdout.take().unwrap(); let stderr = child.stderr.take().unwrap();
                owner.child = Some(child); drop(owner);
                let errors = log.clone();
                thread::spawn(move || { for line in BufReader::new(stderr).lines().map_while(Result::ok) {
                    let _ = writeln!(errors.lock().unwrap(), "{line}"); } });
                let (sender, receiver) = mpsc::channel();
                thread::spawn(move || { for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                    let _ = writeln!(log.lock().unwrap(), "{line}");
                    if let Some(json) = line.strip_prefix("MRA_READY ") { let _ = sender.send(json.to_owned()); }
                }});
                let json = receiver.recv_timeout(Duration::from_secs(60)).map_err(|_| "服务启动失败或超时，请查看日志后重试".to_string())?;
                let ready: Ready = serde_json::from_str(&json).map_err(|e| e.to_string())?;
                if !matches(&ready, &instance, ready.port) { return Err("分析服务身份验证失败".into()); }
                let endpoint = format!("http://127.0.0.1:{}", ready.port);
                let client = reqwest::blocking::Client::builder().no_proxy().timeout(Duration::from_secs(5)).build().map_err(|e| e.to_string())?;
                let health: Ready = client.get(format!("{endpoint}/health")).send().and_then(|r| r.json()).map_err(|e| e.to_string())?;
                if !matches(&health, &instance, ready.port) || health.pid != ready.pid { return Err("健康检查身份不一致".into()); }
                Ok(endpoint)
            })();
            let mut inner = shared.lock().unwrap();
            if inner.status.instance_id!=instance { return; }
            match result { Ok(endpoint) => { inner.status.status = "ready".into(); inner.status.endpoint = Some(endpoint); inner.status.message = "分析服务已就绪".into(); },
                Err(error) => { inner.status.status = "error".into(); inner.status.message = error; inner.status.endpoint = None;
                    if let Some(mut child) = inner.child.take() { kill_owned(&mut child); } } }
        });
        status
    }
    pub fn retry(&self) -> BackendStatus { if self.status().status=="starting" { return self.status(); } self.stop(); self.start() }
    pub fn stop(&self) { let mut inner=self.inner.lock().unwrap(); inner.status.status="error".into(); inner.status.endpoint=None; inner.status.instance_id.clear(); if let Some(mut child) = inner.child.take() { kill_owned(&mut child); } }
}
#[cfg(test)] mod tests { use super::*;
    #[test] fn refuses_unrelated_or_wrong_protocol_server() {
        let mut r = Ready { product: "mra".into(), version: "1.0.0".into(), protocol: 1, instance_id: "owned".into(), port: 1234, pid: 1 };
        assert!(matches(&r,"owned",1234)); assert!(!matches(&r,"other",1234));
        r.protocol = 2; assert!(!matches(&r,"owned",1234)); r.protocol=1; r.product="other".into(); assert!(!matches(&r,"owned",1234));
    }
}
