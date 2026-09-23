"""运行预注册的 100 次真实压缩调用实验；数据和凭据完全分离。"""

import argparse
import asyncio
import hashlib
import json
import math
import shutil
import sys
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from scripts.experiments.context_compaction.fixtures import SCENARIOS, Scenario, make_records
from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import FORMAT_MARGIN, context_usage, measure_input
from src.tidebound.context.compaction import assemble_context
from src.tidebound.llm import ChatCompletionsClient
from src.tidebound.prompting import load_character_bundle, load_prompt_bundles
from src.tidebound.runtime.session import ChatSession
from src.tidebound.runtime.types import Message, ModelReply
from src.tidebound.storage.model_requests import request_run
from src.tidebound.storage.runs import RunStore
from src.tidebound.storage.summaries import SummaryStore
from src.tidebound.tools.registry import create_tools, tool_definitions
from src.tidebound.workflows.compaction import N01, N02, run_compaction
from src.tidebound.workflows.compaction.types import CompactionInput
from webapp.chat_service import session_view

CALLS_PER_GROUP = 10
FILLER = '海风吹过窗边，远处灯光亮了起来。我们慢慢闲聊，暂时没有新的事实、任务或约定。'


class CallQuotaReached(Exception):
    """只用于实验记账，不冒充产品工作流的失败。"""


def write_json(path: Path, data: object) -> None:
    """原子写入不含凭据的实验记录。

    Args:
        path: 实验目录中的输出路径。
        data: 可 JSON 序列化的测量结果。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


class RecordedModel:
    """使用真实模型适配器，逐次保存请求、可见输出、耗时和失败；不保存凭据或推理正文。"""

    def __init__(self, directory: Path, settings: AgentSettings, maximum: int) -> None:
        self.directory = directory
        self.settings = settings
        self.maximum = maximum
        self.episode = 0
        self.sequence = len(list(directory.glob('calls/*.json')))

    async def complete(self, system: str, messages: list[Message], tools: list[dict[str, object]]) -> ModelReply:
        """发送一次实际调用，重试也占用组内额度，不隐瞒失败。

        Args:
            system: 真实压缩指令。
            messages: 真实 N03 生成的合成来源资料。
            tools: 工作流的空工具集。

        Returns:
            生产适配器解析后的模型响应。

        Raises:
            CallQuotaReached: 已达到组内 10 次请求，标记未完成试验为额度截尾。
            AgentError: 原样传播网络、模型或协议错误。
        """
        if self.sequence >= CALLS_PER_GROUP:
            raise CallQuotaReached
        self.sequence += 1
        started = time.monotonic()
        path = self.directory / 'calls' / f'{self.sequence:03d}.json'
        record: dict[str, object] = {
            'sequence': self.sequence, 'episode': self.episode, 'started_at': datetime.now(UTC).isoformat(),
            'status': 'in_flight', 'system': system,
            'messages': [message.model_dump(exclude={'reasoning_content'}) for message in messages],
            'summary_max_bytes': self.maximum, 'max_output_tokens': self.settings.max_output_tokens,
            'input_estimate': measure_input(system, messages, tools),
        }
        write_json(path, record)
        try:
            reply = await ChatCompletionsClient(self.settings).complete(system, messages, tools)
            record.update(status='response', finish_reason=reply.finish_reason,
                          content=reply.message.content, output_bytes=len(reply.message.content.encode('utf-8')),
                          tool_calls=len(reply.message.tool_calls))
            return reply
        except Exception as error:
            record.update(status='error', error_type=type(error).__name__, error_code=getattr(error, 'code', None))
            raise
        finally:
            record['elapsed_seconds'] = round(time.monotonic() - started, 3)
            write_json(path, record)
            print(json.dumps({'group': self.directory.name, 'call': self.sequence, 'status': record['status'],
                              'seconds': record['elapsed_seconds']}, ensure_ascii=False), flush=True)


async def run_group(scenario: Scenario, directory: Path, base: AgentSettings) -> None:
    """执行一组 10 次请求，连续场景沿用已有摘要，其余各次使用独立会话。

    Args:
        scenario: 预先固定的预算和历史条件。
        directory: 组内证据目录。
        base: 仅从服务端配置读取的模型连接信息。
    """
    directory.mkdir(parents=True, exist_ok=True)
    if (directory / 'done.json').exists():
        return
    # 意外中断后不会重发不确定的在途请求；保留该记录，以新 episode 继续剩余额度。
    existing_calls = sorted(directory.glob('calls/*.json'))
    for path in existing_calls:
        record = json.loads(path.read_text())
        if record['status'] == 'in_flight':
            raise RuntimeError(f'Unresolved in-flight call: {path}; inspect before resuming')
    completed_trials = sorted(directory.glob('trials/*.json'))
    episode = max((int(path.stem) for path in completed_trials), default=0)
    records = []
    all_facts: list[dict[str, object]] = []
    owner = uuid4().hex
    data_dir = directory / 'runtime' / f'{episode + 1:03d}'
    if scenario.rolling and episode:
        state = json.loads((directory / 'rolling-state.json').read_text())
        owner = state['owner']
        data_dir = Path(state['data_dir'])
        records = RunStore(data_dir).list_runs(owner)
        all_facts = state['facts']
    model = RecordedModel(directory, base, 0)
    while model.sequence < CALLS_PER_GROUP:
        episode += 1
        if not scenario.rolling:
            records, all_facts, owner = [], [], uuid4().hex
            data_dir = directory / 'runtime' / f'{episode:03d}'
        settings = base.model_copy(update={'context_limit': scenario.budget, 'data_dir': data_dir, 'debug': False})
        runs, summaries = RunStore(data_dir), SummaryStore(data_dir)
        added, facts = make_records(scenario, episode, len(records))
        records.extend(added)
        all_facts.extend(facts)
        system = load_character_bundle(settings.prompts_dir).content
        injection = load_prompt_bundles(settings.prompts_dir, ('context.injection.summary',)).content
        tools = tool_definitions(create_tools(settings.timezone))
        previous = summaries.load(owner, '', [item.run_id for item in records])
        reserved = settings.max_output_tokens + FORMAT_MARGIN
        before = assemble_context(system, records, [], tools, previous, injection)
        target = math.ceil(scenario.occupancy * scenario.budget)
        deficit = max(0, target - before.input_used - reserved)
        repeats = math.ceil(deficit / max(1, len(added) * len(FILLER.encode('utf-8'))))
        for record in added:
            # 仅添加已知低信息密度的冗余材料；密集条件另有每轮独立事实。
            target_message = record.messages[-2] if scenario.tool_heavy else record.messages[-1]
            target_message.content += FILLER * repeats
        before = assemble_context(system, records, [], tools, previous, injection)
        records[-1].context_usage = context_usage(settings, before.input_used)
        for record in added:
            runs.save(owner, record)
        inputs = CompactionInput(owner, '', system, records, [], tools, settings)
        trial: dict[str, object] = {
            'scenario': asdict(scenario), 'episode': episode, 'owner': owner, 'data_dir': str(data_dir),
            'history_turns': len(records), 'new_turns': len(added), 'previous_summary_id': previous.summary_id if previous else None,
            'before_input': before.input_used, 'before_total': before.input_used + reserved,
            'before_percent': 100 * (before.input_used + reserved) / scenario.budget,
            'before_ring_percent': min(100, math.floor(100 * (before.input_used + reserved) / scenario.budget + 0.5)),
            'facts': all_facts, 'history_run_ids': [record.run_id for record in records],
            'calls_before': model.sequence,
        }
        start = time.monotonic()
        token = request_run.set((owner, records[-1].run_id))
        try:
            source = N01.read_source(inputs, summaries)
            plan = N02.build_plan(inputs, source)
            if plan is None:
                trial['status'] = 'not_triggered'
                raise RuntimeError('Generated scenario did not trigger; do not spend calls on unrelated input')
            trial.update(planned_end=plan.end, summary_max_bytes=plan.maximum, fallback=plan.fallback,
                         target_input=plan.target_input)
            model.settings, model.maximum, model.episode = plan.settings, plan.maximum, episode
            result = await run_compaction(inputs, runs, summaries, model)
            if result is None:
                trial['status'] = 'not_committed'
            else:
                trial.update(status='committed', summary=result.model_dump())
                after = assemble_context(system, records, [], tools, result, injection)
                # 调用实际会话查询路径，验证 UI 收到的圆环用量，而不仅是规划值。
                session = ChatSession(settings)
                view = session_view(session, owner)
                ui_input = view.context_usage.input_used
                trial.update(after_input=after.input_used, after_total=after.input_used + reserved,
                    after_percent=100 * (after.input_used + reserved) / scenario.budget,
                    ui_input=ui_input, ui_matches_context=ui_input == after.input_used,
                    after_ring_percent=min(100, math.floor(100 * (int(ui_input) + reserved) / scenario.budget + 0.5)),
                    remaining_budget=scenario.budget - after.input_used - reserved,
                    retained_turns=len(records) - len(result.covered_run_ids),
                    active_text='\n'.join(message.content for message in after.messages),
                    covered_run_ids=result.covered_run_ids)
                await session.close()
        except CallQuotaReached:
            trial['status'] = 'quota_censored'
        except Exception as error:  # noqa: BLE001 - 实验必须完整记录所有失败条件
            trial.update(status='failed', error_type=type(error).__name__, error_code=getattr(error, 'code', None))
        finally:
            request_run.reset(token)
            trial.update(calls_after=model.sequence, elapsed_seconds=round(time.monotonic() - start, 3))
            write_json(directory / 'trials' / f'{episode:03d}.json', trial)
            if scenario.rolling:
                write_json(directory / 'rolling-state.json', {'owner': owner, 'data_dir': str(data_dir), 'facts': all_facts})
            print(json.dumps({'group': scenario.key, 'episode': episode, 'status': trial['status'],
                              'calls': model.sequence, 'after_percent': trial.get('after_percent')}, ensure_ascii=False), flush=True)
        if trial['calls_after'] == trial['calls_before'] and trial['status'] != 'quota_censored':
            raise RuntimeError(f'Non-model blocker in {scenario.key}: {trial.get("error_code")}')
    write_json(directory / 'done.json', {'calls': model.sequence, 'episodes': episode})


def snapshot(root: Path, settings: AgentSettings) -> None:
    """冻结代码、提示词及公开实验配置，不复制 .env、凭据或真实运行数据。

    Args:
        root: 新的实验输出根目录。
        settings: 模型配置，只有公开的模型名和生成参数会写入清单。
    """
    hashes = {}
    for base in [ROOT / 'src/tidebound', ROOT / 'prompts/master', ROOT / 'scripts/experiments/context_compaction']:
        for path in base.rglob('*'):
            if path.is_file() and path.suffix in {'.py', '.md'}:
                relative = path.relative_to(ROOT)
                target = root / 'snapshot' / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                hashes[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    for relative in ['prompts/master.yaml', 'webfrontend/src/components/ContextBudgetRing.tsx', 'webapp/chat_service.py']:
        path = ROOT / relative
        target = root / 'snapshot' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(root / 'manifest.json', {'created_at': datetime.now(UTC).isoformat(), 'model': settings.model,
        'reasoning_effort': settings.reasoning_effort, 'main_output_reserved': settings.max_output_tokens,
        'timeout_seconds': settings.timeout_seconds, 'call_limit': 100, 'calls_per_group': CALLS_PER_GROUP,
        'scenarios': [asdict(item) for item in SCENARIOS], 'source_hashes': hashes,
        'method': 'All 100 requests are compression requests through production N01-N05; retries and quota censoring are reported. Synthetic data only. No LLM judge calls.'})


async def main() -> None:
    """并发三组、组内串行执行，所有真实调用均计入固定 100 次总额度。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    settings = AgentSettings.from_env().model_copy(update={'debug': False})
    if (root / 'manifest.json').exists():
        manifest = json.loads((root / 'manifest.json').read_text())
        for relative, expected in manifest['source_hashes'].items():
            if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f'Experiment source changed: {relative}')
    else:
        snapshot(root, settings)
    if args.plan_only:
        print(json.dumps({'output': str(root), 'groups': len(SCENARIOS), 'calls': 100}))
        return
    semaphore = asyncio.Semaphore(3)
    async def limited(scenario: Scenario) -> None:
        """限制实际网络并发，避免对共享模型服务施加过量请求。

        Args:
            scenario: 本次运行的固定条件。
        """
        async with semaphore:
            await run_group(scenario, root / scenario.key, settings)
    results = await asyncio.gather(*(limited(item) for item in SCENARIOS), return_exceptions=True)
    errors = [str(item) for item in results if isinstance(item, BaseException)]
    write_json(root / 'execution.json', {'finished_at': datetime.now(UTC).isoformat(), 'errors': errors,
        'calls': len(list(root.glob('*/calls/*.json'))),
        'finished_groups': len(list(root.glob('*/done.json')))})
    print(json.dumps({'finished': True, 'calls': len(list(root.glob('*/calls/*.json'))), 'errors': errors}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
