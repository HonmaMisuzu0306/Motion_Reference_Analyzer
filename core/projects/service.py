from pathlib import Path

from db import ReferenceLibrary
from db.paths import store_path, video_hash


class ContentMismatch(ValueError):
    pass


class ProjectService:
    def __init__(self, library=None):
        self.library = library or ReferenceLibrary()

    def save_current(self, project):
        if project.video is None:
            raise ValueError("请先导入视频")
        return self.library.save_analysis(project)

    def rename(self, id: int, name: str):
        name = name.strip()
        if not name or len(name) > 100:
            raise ValueError("项目名称需要1–100个字符")
        self.library.get_project(id)
        conn = self.library._conn
        with conn:
            conn.execute(
                "UPDATE projects SET display_name=?,updated_at=datetime('now') WHERE id=?",
                (name, id),
            )
        return self.library.get_project(id)

    def relink(self, id: int, source: Path):
        project = self.library.get_project(id)
        if not source.is_file():
            raise ValueError("源视频文件不存在")
        if not project.video_hash or video_hash(source) != project.video_hash:
            raise ContentMismatch("视频内容与原素材不同，旧分析不能关联，请创建新分析")
        conn = self.library._conn
        with conn:
            conn.execute(
                "UPDATE projects SET video_path=?,updated_at=datetime('now') WHERE id=?",
                (store_path(source.resolve()), id),
            )
            conn.execute(
                "UPDATE videos SET source_path=? WHERE content_hash=?",
                (store_path(source.resolve()), project.video_hash),
            )
        return self.library.get_project(id)
