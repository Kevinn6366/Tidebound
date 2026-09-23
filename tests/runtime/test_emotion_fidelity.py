"""固定对照语料验证保真拒绝、原样通过与无正文审计。"""

import asyncio
import json
from pathlib import Path

import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.runtime.types import Message, ModelReply
from src.tidebound.workflows.emotion_enhancement import EmotionEnhancementRun

CASES = json.loads((Path(__file__).parents[1] / 'fixtures/emotion_fidelity.json').read_text())


@pytest.mark.parametrize('case', CASES, ids=[case['id'] for case in CASES])
@pytest.mark.parametrize('unchanged', [False, True])
def test_fidelity_corpus(case: dict[str, str], unchanged: bool, tmp_path: Path) -> None:
    """协议合法不等于保真，原稿中的攻击文字只作为 JSON 数据。

    Args:
        case: 固定原稿与存在漂移的对照结果。
        unchanged: 返回完整原稿或有漂移的候选正文。
        tmp_path: 隔离无正文执行事件目录。
    """
    class CandidateModel:
        calls = 0

        async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
            """检查单条资料输入并返回对照样本。

            Args:
                system: 增强阶段固定规则。
                messages: 唯一校对任务及 JSON 原稿。
                tools: 必须为空的工具声明。

            Returns:
                协议合法的候选回复。
            """
            self.calls += 1
            assert not tools and len(messages) == 1
            assert messages[0].role == 'user'
            assert json.loads(messages[0].content.split('\n\n', 1)[1]) == {'draft': case['draft']}
            return ModelReply(message=Message(role='assistant', content=case['draft'] if unchanged else case['unsafe']),
                              finish_reason='stop')

    async def scenario() -> None:
        model = CandidateModel()
        enhancement = EmotionEnhancementRun(AgentSettings(data_dir=tmp_path), '规则', model, '校对任务')
        if unchanged:
            assert await enhancement.polish(case['draft']) == case['draft']
        else:
            with pytest.raises(AgentError) as failure:
                await enhancement.polish(case['draft'])
            assert failure.value.code == 'emotion_fidelity_failed'
            assert case['unsafe'] not in str(failure.value)
        assert model.calls == 1
        events = [json.loads(line) for line in (tmp_path / 'runtime-events.jsonl').read_text().splitlines()]
        assert [(event['name'], event['status']) for event in events] == [
            ('emotion.protocol', 'started'), ('emotion.protocol', 'completed'),
            ('emotion.fidelity', 'started'), ('emotion.fidelity', 'completed' if unchanged else 'failed')]
        assert all('content' not in event for event in events)

    asyncio.run(scenario())


def test_outer_whitespace_returns_exact_draft() -> None:
    """供应商首尾空白不改变最终采用的原稿格式，段落内部仍逐字比较。"""
    from src.tidebound.workflows.emotion_enhancement import validate_fidelity

    draft = '  你好。\n\n先这样。\n'
    assert validate_fidelity(draft, '\n你好。\n\n先这样。  ') == draft
    with pytest.raises(AgentError):
        validate_fidelity(draft, '你好。先这样。')
