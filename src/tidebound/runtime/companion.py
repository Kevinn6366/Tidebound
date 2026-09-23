"""从有效历史恢复陪伴状态，并构造计入预算的本轮资料。"""
import json

from src.tidebound.config import AgentSettings
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.runtime.types import Message, RunRecord
from src.tidebound.storage.companion import CompanionState


def load_state(history: list[RunRecord]) -> CompanionState:
    """复制最近已提交快照，当前 Run 的修改不影响持久化历史。

    Args:
        history: 当前账号有效时间线上按时间排序的已完成 Run。

    Returns:
        可独立修改的状态，旧记录默认没有状态。
    """
    return next((r.companion_state.model_copy(deep=True) for r in reversed(history)
                 if r.status == 'completed' and r.companion_state is not None), CompanionState())


def companion_context(system: str, state: CompanionState, settings: AgentSettings,
                      run_id: str) -> tuple[str, list[Message]]:
    """构造规则、来源标识和独立资料，不写入用户历史。

    Args:
        system: 本次原始角色及临时规则。
        state: 当前执行可见的有效陪伴状态。
        settings: 提示词配置。
        run_id: 当前来源标识，空闲预算测量使用占位标识。

    Returns:
        追加规则的 system 和作为非指令资料提供的消息。

    Raises:
        AgentError: 提示词无法加载。
    """
    rules = load_prompt_bundles(settings.prompts_dir, ('companion.rules',)).content
    system = f'{system}\n\n{rules}\n' + json.dumps({'current_run_id': run_id})
    material = []
    if state.facts or state.followups or state.interests:
        material = [Message(role='user', content=json.dumps({'companion_state': state.model_dump(exclude={'interests': {'__all__': {'seen_urls'}}})}, ensure_ascii=False))]
    return system, material
