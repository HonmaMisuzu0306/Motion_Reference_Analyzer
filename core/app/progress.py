"""分析进度追踪器。

所有进度值必须由后端 Pipeline 真实状态驱动，禁止前端伪造定时器进度。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from schemas.progress import (
    STAGE_WEIGHTS,
    StageProgress,
    StageStatus,
)

if TYPE_CHECKING:
    from schemas.shot import Project


class AnalysisProgressTracker:
    """在分析 Pipeline 执行过程中更新项目进度状态。"""

    def __init__(self, project: Project) -> None:
        self.project = project
        self._progress = project.progress

    def _recompute_overall(self) -> None:
        """根据 Stage 权重和当前 Stage 进度重新计算总体进度。"""
        total = 0.0
        for key, stage in self._progress.stages.items():
            weight = STAGE_WEIGHTS.get(key, 0.0)  # type: ignore[arg-type]
            if stage.status in {"completed", "skipped"}:
                total += weight
            elif stage.status == "error":
                total += weight * stage.progress
            elif stage.status == "running":
                total += weight * stage.progress
        self._progress.overall_progress = min(round(total, 4), 1.0)
        self._sync_status()

    def _sync_status(self) -> None:
        """将顶层状态同步回 Project，保持旧版 API 兼容。"""
        self.project.analysis_status = self._progress.status
        self.project.analysis_message = self._progress.message

    def _ensure_prior_stages_completed(self, current_key: str) -> None:
        """将当前 Stage 之前的所有 Stage 标记为已完成。"""
        keys = list(self._progress.stages.keys())
        for key in keys:
            if key == current_key:
                break
            stage = self._progress.stages[key]
            if stage.status not in {"completed", "skipped", "error"}:
                stage.status = "completed"
                stage.progress = 1.0

    def _set_stage_status(self, key: str, status: StageStatus) -> StageProgress:
        """设置指定 Stage 的状态。"""
        stage = self._progress.stages[key]
        stage.status = status
        return stage

    def start_analysis(self) -> None:
        """分析开始时重置并进入 preparing 阶段。"""
        now = time.time()
        self._progress.status = "preparing"
        self._progress.stage = "preparing"
        self._progress.message = "准备分析"
        self._progress.started_at = now
        self._progress.completed_at = None
        self._progress.error = None
        self._progress.eta_seconds = None
        self._progress.current_shot = None
        self._progress.total_shots = None
        self._progress.overall_progress = 0.0

        # 重置所有 Stage
        for stage in self._progress.stages.values():
            stage.status = "pending"
            stage.progress = 0.0
            stage.completed = 0
            stage.total = 0
            stage.failed = 0
            stage.message = ""

        self.start_stage("preparing", "准备分析")

    def start_stage(self, key: str, message: str) -> None:
        """进入新的 Stage。"""
        self._ensure_prior_stages_completed(key)
        stage = self._set_stage_status(key, "running")
        stage.progress = 0.0
        stage.completed = 0
        stage.total = 0
        stage.failed = 0
        stage.message = ""

        self._progress.stage = key
        self._progress.message = message
        self._recompute_overall()

    def update_stage(
        self,
        key: str,
        completed: int,
        total: int,
        message: str,
        current_shot: int | None = None,
    ) -> None:
        """更新 Stage 的 Shot 级进度。"""
        stage = self._progress.stages[key]
        stage.completed = max(0, completed)
        stage.total = max(1, total)
        stage.progress = min(stage.completed / stage.total, 1.0)
        stage.message = message

        self._progress.current_shot = current_shot
        self._progress.total_shots = total
        self._progress.message = message
        self._recompute_overall()
        self._update_eta()

    def shot_complete(
        self,
        key: str,
        shot_index: int,
        total: int,
        message: str,
    ) -> None:
        """单个 Shot 成功完成后更新进度。"""
        self.update_stage(
            key,
            completed=shot_index,
            total=total,
            message=message,
            current_shot=shot_index,
        )

    def shot_failed(
        self,
        key: str,
        shot_index: int,
        total: int,
        error: str,
    ) -> None:
        """单个 Shot 失败但 Pipeline 继续时记录失败计数。"""
        stage = self._progress.stages[key]
        stage.failed += 1
        stage.total = max(1, total)
        stage.completed = max(0, shot_index - 1)
        stage.progress = min((stage.completed + stage.failed) / stage.total, 1.0)
        stage.message = f"{stage.message or key}: shot_{shot_index:03d} 失败"

        self._progress.current_shot = shot_index
        self._progress.total_shots = total
        self._progress.message = f"Shot {shot_index}/{total} 失败: {error}"
        self._recompute_overall()

    def complete_stage(self, key: str) -> None:
        """标记 Stage 完成。"""
        stage = self._progress.stages[key]
        stage.status = "completed"
        stage.progress = 1.0
        if stage.total == 0:
            stage.total = 1
            stage.completed = 1
        self._progress.message = ""
        self._recompute_overall()

    def set_stage_error(self, key: str, message: str) -> None:
        """Stage 整体失败时调用。"""
        stage = self._set_stage_status(key, "error")
        stage.message = message
        self._progress.status = "error"
        self._progress.stage = key
        self._progress.message = message
        self._progress.error = {"stage": key, "message": message}

    def complete_optional_stage(self, key: str, status: str, message: str) -> None:
        """Finish a nonfatal stage without falsifying its skipped/error result."""
        self.complete_stage(key)
        stage = self._progress.stages[key]
        stage.message = message
        stage.total = 1
        stage.completed = 1
        stage.failed = 0
        self._progress.message = message
        if status in {'no_audio','skipped'}:
            stage.status = 'skipped'
            stage.total = stage.completed = 0
        elif status == 'error':
            stage.status = 'error'
            stage.failed = 1
            stage.completed = 0
        self._recompute_overall()

    def set_error(
        self,
        stage: str,
        message: str,
        shot_id: str = "",
    ) -> None:
        """设置全局错误状态。"""
        self._progress.status = "error"
        self._progress.stage = stage
        self._progress.message = message
        self._progress.error = {
            "stage": stage,
            "message": message,
            "shot": shot_id,
        }
        if stage in self._progress.stages:
            self._set_stage_status(stage, "error")
        self._sync_status()

    def finish_analysis(self, has_warnings: bool = False) -> None:
        """分析完成，可能带有警告。"""
        self._ensure_prior_stages_completed("saving")
        self.complete_stage("saving")
        self._progress.status = "completed_with_warnings" if has_warnings else "done"
        self._progress.stage = "done"
        self._progress.message = (
            "分析完成（部分步骤存在警告）" if has_warnings else "分析完成"
        )
        self._progress.overall_progress = 1.0
        self._progress.completed_at = time.time()
        self._progress.current_shot = None
        self._progress.eta_seconds = None
        self._sync_status()

    def _update_eta(self) -> None:
        """根据当前运行 Stage 的已完成 Shot 平均耗时估算剩余时间。"""
        if self._progress.started_at is None:
            self._progress.eta_seconds = None
            return

        current_stage = self._progress.stage
        if current_stage not in self._progress.stages:
            self._progress.eta_seconds = None
            return

        stage = self._progress.stages[current_stage]
        finished = stage.completed + stage.failed
        if finished == 0 or stage.total == 0:
            self._progress.eta_seconds = None
            return

        elapsed = time.time() - self._progress.started_at
        avg_per_unit = elapsed / finished
        remaining = max(0, stage.total - finished)
        self._progress.eta_seconds = round(avg_per_unit * remaining, 1)
