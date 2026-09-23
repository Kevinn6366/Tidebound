"""不耗模型请求的边界对照与下一次输入空间测量。"""

import argparse
import json
from pathlib import Path

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import FORMAT_MARGIN, measure_input
from src.tidebound.context.compaction import assemble_context, needs_compaction, plan_compaction
from src.tidebound.errors import AgentError
from src.tidebound.prompting import load_character_bundle, load_prompt_bundles
from src.tidebound.runtime.types import Message
from src.tidebound.storage.runs import RunStore
from src.tidebound.storage.summaries import ContextSummary, SummaryStore
from src.tidebound.tools.registry import create_tools, tool_definitions


def run_controls(root: Path) -> dict[str, object]:
    """测量精确阈值及必需材料过大时的结果，并重算新增消息的真实 JSON 开销。

    Args:
        root: 已生成实际试验数据的隔离根目录。

    Returns:
        离线断言和每个已提交试验的剩余空间结果，不计入 100 次真实调用。
    """
    settings = AgentSettings.from_env().model_copy(update={'debug': False})
    controls: list[dict[str, object]] = []
    s = settings.model_copy(update={'context_limit': 20000})
    reserved = s.max_output_tokens + FORMAT_MARGIN
    for total in (19799, 19800, 20001):
        controls.append({'name': f'threshold_{total}', 'total': total,
                         'triggered': needs_compaction(total - reserved, s)})
    assert [c['triggered'] for c in controls] == [False, True, True]
    system = load_character_bundle(settings.prompts_dir).content
    injection = load_prompt_bundles(settings.prompts_dir, ('context.injection.summary',)).content
    tools = tool_definitions(create_tools(settings.timezone))
    first = json.loads(min((root / 'normal_32k_sparse/trials').glob('*.json')).read_text())
    runs = RunStore(Path(first['data_dir']))
    records = runs.list_runs(first['owner'])
    test_cases = [
        ('oversized_current_turn', settings.model_copy(update={'context_limit': 32768}),
         [Message(role='user', content='x' * 40000)], None),
        ('fixed_prompt_exceeds_budget', settings.model_copy(update={'context_limit': 16384}), [], None),
    ]
    existing = SummaryStore(Path(first['data_dir'])).load(first['owner'], '', [r.run_id for r in records])
    assert existing is not None
    test_cases.append(('no_new_history_to_compact', settings.model_copy(update={'context_limit': 32768}),
                       [Message(role='user', content='x' * 30000)], existing))
    for name, conf, current, previous in test_cases:
        try:
            plan_compaction(system, records, current, tools, previous, injection, conf)
            controls.append({'name': name, 'result': 'unexpected_plan'})
        except AgentError as error:
            controls.append({'name': name, 'result': error.code})
    spaces = []
    for path in sorted(root.glob('*/trials/*.json')):
        trial = json.loads(path.read_text())
        if trial['status'] != 'committed':
            continue
        conf = settings.model_copy(update={'context_limit': trial['scenario']['budget']})
        records = RunStore(Path(trial['data_dir'])).list_runs(trial['owner'])
        # 连续会话磁盘已有未来轮次，严格限制到该试验的固定历史前缀。
        records = [r for r in records if r.run_id in trial['history_run_ids']]
        summary = ContextSummary.model_validate(trial['summary'])
        context = assemble_context(system, records, [], tools, summary, injection)
        assert context.input_used == trial['after_input']
        fits = {}
        for size in (100, 500, 1000):
            used = measure_input(context.system, [*context.messages, Message(role='user', content='x' * size)], tools)
            fits[str(size)] = {'fits': used + reserved <= conf.context_limit,
                              'additional_estimate': used - context.input_used}
        spaces.append({'group': trial['scenario']['key'], 'episode': trial['episode'], 'next_input': fits})
    result = {'controls': controls, 'spaces': spaces, 'model_calls': 0}
    (root / 'controls.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    result = run_controls(args.root)
    print(json.dumps(result['controls'], ensure_ascii=False, indent=2))
