"""以固定合成样例单次调用云端增强，记录协议与保真结果，不修改用户会话。

运行：python -m scripts.experiments.emotion_fidelity
结果保存到 data/emotion-fidelity-issue14.json；每条样例只调用一次，无重试。
"""

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from src.tidebound.config import ROOT, AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import ChatCompletionsClient
from src.tidebound.runtime.emotion_enhancement import EmotionEnhancement
from src.tidebound.runtime.types import Message, ModelReply


class RecordingModel(ChatCompletionsClient):
    """仅供合成语料实验记录实际候选，运行时不保存未采用正文。"""

    reply: ModelReply | None = None

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """发送唯一请求并保留实验响应。

        Args:
            system: 固定增强规则。
            messages: 单条合成原稿。
            tools: 空工具列表。

        Returns:
            未经保真检查的模型响应。

        Raises:
            AgentError: 模型请求或协议解析失败。
        """
        self.reply = await super().complete(system, messages, tools)
        return self.reply


async def evaluate() -> None:
    """逐条运行隔离实验，凭据只进入鉴权头，报告不包含配置与错误原文。

    Raises:
        AgentError: 云端增强未配置，无法启动实验。
        OSError: 合成语料或报告无法读写。
    """
    settings = AgentSettings.from_env()
    cases = json.loads((ROOT / 'tests/fixtures/emotion_fidelity.json').read_text())
    results: list[dict[str, object]] = []
    target = ROOT / 'data/emotion-fidelity-issue14.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='emotion-fidelity-') as directory:
        service = EmotionEnhancement(settings.model_copy(update={'data_dir': Path(directory)}))
        owner = uuid4().hex
        service.select(owner, True)
        prepared = service.prepare(owner)
        assert prepared is not None
        for case in cases:
            model = RecordingModel(prepared.settings)
            run = type(prepared)(prepared.settings, prepared.system, model, prepared.instruction)
            error_code = ''
            try:
                await run.polish(case['draft'])
            except AgentError as error:
                error_code = error.code
            reply = model.reply
            protocol_pass = bool(reply and reply.finish_reason == 'stop' and reply.message.role == 'assistant'
                                 and not reply.message.tool_calls and reply.message.content.strip())
            candidate = reply.message.content if reply else ''
            # 即使供应商反射鉴权信息，实验产物也不写入真实凭据。
            for value in settings:
                secret = getattr(value[1], 'get_secret_value', None)
                if secret and secret():
                    candidate = candidate.replace(secret(), '[REDACTED]')
            results.append({'id': case['id'], 'draft': case['draft'], 'candidate': candidate,
                            'protocol_pass': protocol_pass, 'fidelity_pass': not error_code,
                            'safety_boundary': 'preserved_by_identity' if not error_code else 'not_admitted',
                            'error_code': error_code})
            target.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n')
            print(case['id'], error_code or 'identity_pass', flush=True)


if __name__ == '__main__':
    asyncio.run(evaluate())
