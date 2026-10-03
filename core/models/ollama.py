import httpx


class OllamaInspector:
    def __init__(self, base_url: str, timeout: float = 5, transport=None):
        self.base_url = base_url.rstrip("/").removesuffix("/v1")
        self.timeout = timeout
        self.transport = transport

    def inspect(self) -> dict:
        try:
            with httpx.Client(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                tags = client.get("/api/tags")
                tags.raise_for_status()
                models = []
                for item in tags.json()["models"]:
                    name = item.get("name") or item["model"]
                    row = {"id": name, "size": item.get("size"), "vision": False, "error": ""}
                    try:
                        response = client.post("/api/show", json={"model": name})
                        response.raise_for_status()
                        row["vision"] = "vision" in response.json().get("capabilities", [])
                    except Exception as exc:
                        row["error"] = f"无法检测视觉能力：{exc}"
                    models.append(row)
                return {"connected": True, "models": models, "message": "本地模型服务已连接"}
        except Exception as exc:
            return {
                "connected": False,
                "models": [],
                "message": f"无法连接本地 Ollama，请安装或启动后重新检测：{exc}",
            }
