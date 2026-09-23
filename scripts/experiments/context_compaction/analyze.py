"""对原始实验结果进行可复核的事实匹配、圆环计算与汇总。"""

import argparse
import json
import re
import statistics
from collections import Counter
from pathlib import Path


def load(path: Path) -> dict:
    """读取单份实验 JSON，不访问配置或真实账号。"""
    return json.loads(path.read_text(encoding='utf-8'))


def normalize(text: str) -> str:
    """归一化摘要的换行与常见标点，不改变否定或事实值。"""
    return text.lower().replace('\\n', '\n').replace('－', '-').replace('—', '-').replace('：', ':')


def match_fact(text: str, fact: dict) -> bool:
    """按预先固定模式初筛，不能替代否定、来源与动作状态的语义复核。

    Args:
        text: 摘要正文或完整活动上下文。
        fact: 含预先固定正则条件的事实。

    Returns:
        所有模式均有匹配时为真。
    """
    text = normalize(text)
    return all(re.search(pattern, text) is not None for pattern in fact['patterns'])


def percent(hits: int, total: int) -> float | None:
    return round(hits / total * 100, 2) if total else None


def analyze(root: Path) -> dict:
    """保留所有调用与失败，生成逐项初筛及人工复核入口。

    Args:
        root: 原始实验根目录。

    Returns:
        分组统计、调用记账和逐次工作流结果。
    """
    overrides_path = root / 'semantic-review.json'
    overrides = load(overrides_path).get('overrides', {}) if overrides_path.exists() else {}
    scored = []
    groups = []
    omissions = []
    for group in sorted(root.iterdir()):
        if not (group / 'calls').exists():
            continue
        calls = [load(p) for p in sorted(group.glob('calls/*.json'))]
        trials = [load(p) for p in sorted(group.glob('trials/*.json'))]
        group_scored = []
        for trial in trials:
            if trial['status'] != 'committed':
                continue
            summary = trial['summary']['content']
            active = trial['active_text']
            covered = set(trial['covered_run_ids'])
            rows = []
            for fact in trial['facts']:
                automatic = match_fact(active, fact)
                summary_match = match_fact(summary, fact)
                key = f"{group.name}/{trial['episode']:03d}/{fact['id']}"
                review = overrides.get(key)
                hit = review['retained'] if review else automatic
                row = {'key': key, 'fact_id': fact['id'], 'category': fact['category'], 'critical': fact['critical'],
                       'source': fact['text'], 'compressed': fact['run_id'] in covered,
                       'automatic_active': automatic, 'automatic_summary': summary_match,
                       'retained': hit, 'review': review}
                rows.append(row)
                if not automatic and fact['category'] != 'ordinary_detail':
                    omissions.append({'key': key, 'source': fact['text'], 'summary': summary,
                                      'compressed': fact['run_id'] in covered})
            for scope, selected in [('all', rows), ('core', [r for r in rows if r['category'] != 'ordinary_detail']),
                ('critical', [r for r in rows if r['critical']]), ('ordinary', [r for r in rows if r['category'] == 'ordinary_detail']),
                ('compressed_core', [r for r in rows if r['compressed'] and r['category'] != 'ordinary_detail'])]:
                trial[f'{scope}_hits'] = sum(row['retained'] for row in selected)
                trial[f'{scope}_total'] = len(selected)
                trial[f'{scope}_retention'] = percent(trial[f'{scope}_hits'], len(selected))
            trial['fact_scores'] = rows
            trial['point_reduction'] = trial['before_percent'] - trial['after_percent']
            group_scored.append(trial)
        scored.extend(group_scored)
        stats = {'group': group.name, 'calls': len(calls), 'responses': sum(c['status'] == 'response' for c in calls),
                 'call_errors': Counter(c.get('error_code') for c in calls if c['status'] == 'error'),
                 'finish_reasons': Counter(c.get('finish_reason') for c in calls),
                 'trials': len(trials), 'statuses': Counter(t['status'] for t in trials),
                 'failures': Counter(t.get('error_code') for t in trials if t['status'] == 'failed'),
                 'invalid_outputs': sum(c.get('output_bytes', 0) > c['summary_max_bytes'] or c.get('finish_reason') != 'stop'
                                        for c in calls if c['status'] == 'response'),
                 'call_latency_median': round(statistics.median(c['elapsed_seconds'] for c in calls if 'elapsed_seconds' in c), 2) if any('elapsed_seconds' in c for c in calls) else None}
        for key in ['before_percent', 'after_percent', 'point_reduction', 'remaining_budget', 'history_turns',
                    'core_retention', 'critical_retention', 'ordinary_retention', 'elapsed_seconds']:
            values = [t[key] for t in group_scored if t[key] is not None]
            stats[key] = {'mean': round(statistics.mean(values), 2), 'min': round(min(values), 2),
                          'max': round(max(values), 2)} if values else None
        stats['ui_matches'] = all(t['ui_matches_context'] for t in group_scored)
        stats['ring_decreased'] = sum(t['after_ring_percent'] < t['before_ring_percent'] for t in group_scored)
        stats['at_most_70'] = sum(t['after_percent'] <= 70 for t in group_scored)
        stats['fallback'] = sum(t['fallback'] for t in group_scored)
        stats['fact_totals'] = {scope: {'hits': sum(t[f'{scope}_hits'] for t in group_scored),
                                      'total': sum(t[f'{scope}_total'] for t in group_scored)}
                               for scope in ['all', 'core', 'critical', 'ordinary', 'compressed_core']}
        groups.append(stats)
    result = {'groups': groups, 'trials': scored,
              'calls_total': sum(g['calls'] for g in groups), 'responses_total': sum(g['responses'] for g in groups),
              'committed_total': len(scored), 'review_overrides': len(overrides)}
    (root / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    (root / 'review-candidates.json').write_text(json.dumps(omissions, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    result = analyze(args.root)
    print(json.dumps({key: value for key, value in result.items() if key != 'trials'}, ensure_ascii=False, indent=2))
