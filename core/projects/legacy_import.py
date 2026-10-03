"""Read-only SQLite snapshot plus staged assets; publish rows in one transaction."""

import hashlib
import json
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from app.runtime_paths import RuntimePaths
from db.schema import init_schema


def import_legacy_library(source_db: Path, source_root: Path, target: RuntimePaths):
    source_db, source_root = source_db.resolve(), source_root.resolve()
    if not source_db.is_file():
        raise ValueError("源数据库不存在")
    if source_db == target.database.resolve():
        raise ValueError("源和目标数据库不能相同")
    target.data_root.mkdir(parents=True, exist_ok=True)
    tables = [
        "videos",
        "tags",
        "projects",
        "shots",
        "shot_tags",
        "project_tags",
        "automatic_shot_tags",
        "selection_analyses",
    ]
    destination = sqlite3.connect(target.database, timeout=10)
    init_schema(destination)
    if any(destination.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables):
        destination.close()
        raise ValueError("仅允许导入到为空的参考库")
    publication = target.data_root / ("imported-" + uuid4().hex)
    missing_sources = []
    try:
        with tempfile.TemporaryDirectory(prefix=".mra-import-", dir=target.data_root) as temporary:
            staging = Path(temporary)
            snapshot = staging / "snapshot.db"
            with (
                closing(sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True)) as source,
                closing(sqlite3.connect(snapshot)) as copy,
            ):
                version = source.execute("PRAGMA user_version").fetchone()[0]
                if version < 3 or version > 6:
                    raise ValueError(f"支持 schema 3–6 的旧库，当前为 {version}")
                source.backup(copy)
                init_schema(copy)
                copy.row_factory = sqlite3.Row
                mappings = []
                for project in copy.execute("SELECT * FROM projects").fetchall():
                    value = project["assets_dir"]
                    if value:
                        original = Path(value)
                        if value.startswith("@data/"):
                            original = source_db.parent / value.removeprefix("@data/")
                        elif not original.is_absolute():
                            original = source_root / original
                        original = original.resolve()
                        if not original.is_relative_to(source_root):
                            raise ValueError(f"资产目录超出指定源根：{original}")
                        if not original.is_dir():
                            raise ValueError(f"资产目录缺失，导入已取消：{original}")
                        # Resolve every link before copying; never follow outside source_root.
                        for asset in original.rglob("*"):
                            if not asset.resolve().is_relative_to(source_root):
                                raise ValueError(f"资产链接超出指定源根：{asset}")
                        relative = Path(str(project["id"]))
                        shutil.copytree(original, staging / "assets" / relative)
                        mappings.append((original, relative))
                        copy.execute(
                            "UPDATE projects SET assets_dir=? WHERE id=?",
                            (
                                "@data/" + (Path(publication.name) / relative).as_posix(),
                                project["id"],
                            ),
                        )
                    if project["video_path"]:
                        path = Path(project["video_path"])
                        if not path.is_absolute():
                            path = source_root / path
                        copy.execute(
                            "UPDATE projects SET video_path=? WHERE id=?",
                            (str(path), project["id"]),
                        )
                        if not path.is_file():
                            missing_sources.append(str(path))

                def translate(value):
                    if not value:
                        return value
                    old = Path(value)
                    if value.startswith("@data/"):
                        old = source_db.parent / value.removeprefix("@data/")
                    elif not old.is_absolute():
                        old = source_root / old
                    old = old.resolve()
                    for original, relative in mappings:
                        if old.is_relative_to(original):
                            if not old.is_file():
                                raise ValueError(f"引用资产缺失，导入已取消：{old}")
                            return (
                                "@data/"
                                + (
                                    Path(publication.name) / relative / old.relative_to(original)
                                ).as_posix()
                            )
                    raise ValueError(f"引用资产未在指定源根的项目目录中：{old}")

                for shot in copy.execute("SELECT * FROM shots").fetchall():
                    frames = [translate(v) for v in json.loads(shot["frame_paths"] or "[]")]
                    copy.execute(
                        "UPDATE shots SET thumbnail_path=?,frame_paths=? WHERE id=?",
                        (translate(shot["thumbnail_path"]), json.dumps(frames), shot["id"]),
                    )
                for record in copy.execute('SELECT * FROM selection_analyses').fetchall():
                    value = record['assets_dir']
                    original = Path(value)
                    if value.startswith('@data/'):
                        original = source_db.parent / value.removeprefix('@data/')
                    elif not original.is_absolute():
                        original = source_root / original
                    original = original.resolve()
                    if not original.is_relative_to(source_root):
                        raise ValueError(f'局部资产超出指定源根：{original}')
                    # Failed/interrupted jobs may have no assets; done records must keep evidence.
                    if not original.is_dir() and record['status'] == 'done':
                        raise ValueError(f'局部资产目录缺失，导入已取消：{original}')
                    result = json.loads(record['result_json'])
                    evidence = ([result.get('frame', {}).get('image', 'frame.png')] if record['kind'] == 'frame'
                                else [f"shots/{shot['shot_id']}/{name}" for shot in result.get('shots', [])
                                      for name in shot.get('frames', [])])
                    if record['status'] in ('done', 'completed_with_warnings'):
                        for name in evidence:
                            referenced = (original / name).resolve()
                            if not referenced.is_relative_to(original) or not referenced.is_file():
                                raise ValueError(f'局部引用资产缺失或越界，导入已取消：{name}')
                    relative = Path('selections') / hashlib.sha256(record['id'].encode()).hexdigest()
                    if original.is_dir():
                        for asset in original.rglob('*'):
                            if not asset.resolve().is_relative_to(source_root):
                                raise ValueError(f'局部资产链接超出指定源根：{asset}')
                        shutil.copytree(original, staging / 'assets' / relative)
                    copy.execute('UPDATE selection_analyses SET assets_dir=? WHERE id=?',
                                 ('@data/' + (Path(publication.name) / relative).as_posix(), record['id']))
                copy.execute("""UPDATE selection_analyses SET status='interrupted',
                    error='导入的任务没有运行中的工作进程，请重新分析为新记录'
                    WHERE status IN ('preparing','running')""")
                for video in copy.execute("SELECT * FROM videos").fetchall():
                    path = Path(video["source_path"])
                    copy.execute(
                        "UPDATE videos SET source_path=? WHERE id=?",
                        (str(path if path.is_absolute() else source_root / path), video["id"]),
                    )
                copy.commit()
                if copy.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("旧库关联校验失败")
            if (staging / "assets").exists():
                (staging / "assets").replace(publication)
            with closing(sqlite3.connect(snapshot)) as read_copy, destination:
                destination.execute("BEGIN IMMEDIATE")
                if any(
                    destination.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables
                ):
                    raise ValueError("仅允许导入到为空的参考库")
                for table in tables:
                    cursor = read_copy.execute(f"SELECT * FROM {table}")
                    placeholders = ",".join("?" for _ in cursor.description)
                    while batch := cursor.fetchmany(256):
                        destination.executemany(
                            f"INSERT INTO {table} VALUES ({placeholders})", batch
                        )
                if destination.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("目标库关联校验失败")
            count = destination.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        return {
            "projects": count,
            "missing_sources": missing_sources,
            "target": str(target.data_root),
        }
    except Exception:
        destination.rollback()
        if publication.is_dir() and publication.resolve().parent == target.data_root.resolve():
            shutil.rmtree(publication)
        raise
    finally:
        destination.close()
