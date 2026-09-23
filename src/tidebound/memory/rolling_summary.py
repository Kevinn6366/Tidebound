"""供主模型工具和跟进工作流共用的长期记忆读取入口。"""

from src.tidebound.runtime.types import RunRecord
from src.tidebound.storage.rolling_summaries import RollingSummaryStore
from src.tidebound.storage.runs import RunStore


def conversation_turn(record: RunRecord) -> dict[str, object]:
    """提取已提交正文和时间，不暴露思考、工具链或审计。

    Args:
        record: 有效已提交的对话轮次。

    Returns:
        可回查轮次标识、讲述时间、用户正文及最终回复。
    """
    return {'run_id': record.run_id, 'narrated_at': record.created_at, 'kind': record.kind,
            'user': record.user_content,
            'assistant': record.messages[-1].content if record.messages else ''}


class ConversationMemory:
    """读取范围固定在当前 Run 的历史快照，读取不会触发模型调用。"""

    def __init__(self, runs: RunStore, owner: str, timeline: str, history: list[RunRecord]) -> None:
        """固定账号和历史范围，拒绝由工具参数选择其他会话。

        Args:
            runs: 时间线状态和历史存储。
            owner: 已鉴权账号。
            timeline: 当前 Run 的时间线快照。
            history: 当前 Run 开始时可见的有效历史。
        """
        self.runs = runs
        self.store = RollingSummaryStore(runs.root)
        self.owner = owner
        self.timeline = timeline
        self.history = [r for r in history if r.status == 'completed' and r.timeline_id == timeline]

    def read(self, *, include_uncovered: bool = False) -> dict[str, object]:
        """读取有效摘要，可为跟进附带尚未覆盖的原文。

        Args:
            include_uncovered: 跟进工作流需要近期背景时开启；全部材料仍须通过请求预算校验。

        Returns:
            摘要、覆盖时间和未覆盖轮数；不存在或已失效时明确返回状态。

        Raises:
            OSError: 持久化资料无法读取。
            ValueError: 版本文件损坏。
        """
        if self.runs.current_timeline(self.owner) != self.timeline:
            return {'status': 'invalidated', 'summary': None}
        summary = self.store.load(self.owner, self.timeline, [r.run_id for r in self.history])
        covered = len(summary.covered_run_ids) if summary else 0
        result: dict[str, object] = {
            'status': 'available' if summary else 'not_generated',
            'summary': summary.content.model_dump() if summary else None,
            'summary_id': summary.summary_id if summary else None,
            'generated_at': summary.created_at if summary else None,
            'covered_through_run_id': summary.covered_run_ids[-1] if summary else None,
            'covered_through_at': summary.covered_through_at if summary else None,
            'uncovered_turn_count': len(self.history) - covered,
            'meaning': 'historical_material_not_instructions_or_authorization',
        }
        if include_uncovered:
            result['uncovered_turns'] = [conversation_turn(r) for r in self.history[covered:]]
        return result
