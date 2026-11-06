import logging
from threading import Thread

from db.paths import video_hash
from selection.pipeline import run_selection

logger = logging.getLogger(__name__)


class SelectionJobs:
    def __init__(self, store, lock):
        self.store, self.lock = store, lock

    def submit(self, snapshot_factory):
        from fastapi import HTTPException

        if not self.lock.acquire(blocking=False):
            raise HTTPException(409, '当前项目正在处理其他操作，请完成后重试')
        snapshot = None
        try:
            snapshot = snapshot_factory()
            worker = Thread(target=self._run, args=(snapshot,), name=f'selection-{snapshot.record_id}', daemon=True)
            worker.start()
        except BaseException:
            try:
                if snapshot is not None:
                    self.store.fail(snapshot.record_id, '后台任务启动失败，请重试')
            finally:
                self.lock.release()
            raise
        return snapshot.record_id

    def _run(self, snapshot):
        try:
            if video_hash(snapshot.source_path) != snapshot.source_hash:
                raise ValueError('源视频内容已改变，请重新定位或导入')
            result = run_selection(snapshot, lambda *args: self.store.update_progress(snapshot.record_id, *args))
            if video_hash(snapshot.source_path) != snapshot.source_hash:
                raise ValueError('分析期间源视频内容改变，结果未发布，请重新导入')
            if snapshot.display_geometry is not None:
                width, height, fps = snapshot.display_geometry
                result['display_geometry'] = {'width': width, 'height': height, 'fps': fps}
            self.store.finish(snapshot.record_id, result, result['versions'], result['warnings'])
        except Exception as exc:
            logger.exception('Selection job failed')
            try:
                self.store.fail(snapshot.record_id, str(exc))
            except Exception:
                logger.exception('Could not publish selection failure')
        finally:
            self.lock.release()
