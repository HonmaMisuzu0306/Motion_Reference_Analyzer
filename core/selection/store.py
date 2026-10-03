"""Each operation owns a connection; worker publication is one transaction."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from db.paths import store_path
from db.schema import init_schema


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _record(row):
    result = dict(row)
    for key in ('request', 'actual_time', 'result', 'progress', 'versions', 'warnings'):
        result[key] = json.loads(result.pop(key + '_json'))
    return result


class SelectionStore:
    def __init__(self, database: Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as conn:
            definition = conn.execute("SELECT sql FROM sqlite_master WHERE name='selection_analyses'").fetchone()
            if conn.execute('PRAGMA user_version').fetchone()[0] != 6 or not definition or 'completed_with_warnings' not in definition[0]:
                init_schema(conn)

    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.database, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def create(self, project_id: int, kind: str, source_hash: str, request: dict, assets_dir: str,
               *, record_id: str | None = None) -> str:
        rid, now = record_id or str(uuid4()), _now()
        with self._connection() as conn:
            conn.execute('''INSERT INTO selection_analyses
                (id,project_id,kind,source_hash,request_json,assets_dir,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?)''',
                         (rid, project_id, kind, source_hash, _json(request), store_path(assets_dir), now, now))
        return rid

    def get(self, record_id: str) -> dict:
        with self._connection() as conn:
            row = conn.execute('SELECT * FROM selection_analyses WHERE id=?', (record_id,)).fetchone()
        if row is None:
            raise KeyError(record_id)
        return _record(row)

    def list(self, project_id: int, limit: int = 20, offset: int = 0) -> dict:
        if not 1 <= limit <= 100 or offset < 0:
            raise ValueError('分页参数无效')
        with self._connection() as conn:
            total = conn.execute('SELECT COUNT(*) FROM selection_analyses WHERE project_id=?', (project_id,)).fetchone()[0]
            rows = conn.execute('''SELECT id,project_id,kind,source_hash,request_json,actual_time_json,
                '{}' AS result_json,progress_json,status,assets_dir,versions_json,warnings_json,error,created_at,updated_at
                FROM selection_analyses WHERE project_id=?
                ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?''', (project_id, limit, offset)).fetchall()
        return {'items': [_record(row) for row in rows], 'total': total}

    def update_progress(self, record_id: str, stage: str, completed: int, total: int, message: str) -> None:
        progress = {'stage': stage, 'completed': completed, 'total': total, 'message': message}
        with self._connection() as conn:
            conn.execute("""UPDATE selection_analyses SET status='running',progress_json=?,updated_at=?
                WHERE id=? AND status IN ('preparing','running')""", (_json(progress), _now(), record_id))

    def finish(self, record_id: str, result: dict, versions: dict, warnings: list) -> None:
        status = 'completed_with_warnings' if result.get('partial_failures') else 'done'
        with self._connection() as conn:
            updated = conn.execute("""UPDATE selection_analyses SET status=?,result_json=?,actual_time_json=?,
                versions_json=?,warnings_json=?,progress_json=?,updated_at=?
                WHERE id=? AND status IN ('preparing','running')""",
                                   (status, _json(result), _json(result.get('time', {})), _json(versions), _json(warnings),
                                    _json({'stage': status, 'completed': 1, 'total': 1, 'message': '部分完成，请查看警告' if status != 'done' else '分析完成'}),
                                    _now(), record_id)).rowcount
            if not updated:
                raise ValueError('记录已不处于可完成状态')

    def fail(self, record_id: str, message: str) -> None:
        with self._connection() as conn:
            conn.execute("""UPDATE selection_analyses SET status='error',error=?,updated_at=?
                WHERE id=? AND status IN ('preparing','running')""", (message, _now(), record_id))

    def recover_interrupted(self) -> int:
        with self._connection() as conn:
            return conn.execute("""UPDATE selection_analyses SET status='interrupted',error=?,updated_at=?
                WHERE status IN ('preparing','running')""",
                                ('上次任务随应用退出而中断，请新建分析记录重试', _now())).rowcount
