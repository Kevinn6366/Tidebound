"""对只读 ATRI 输入执行结构审计与可复现抽样，不自动生成语义判断。"""
from __future__ import annotations
import collections
import hashlib
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT.parents[2] / 'prompts/RAW/RAW-DATA.jsonl'
SEED = 20260915


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def audit() -> None:
    """审计全部物理行，按模板与问答关联组件预留数据并记录初始阅读样本。

    Returns:
        无返回值，结果写入同目录 manifest.json。
    Raises:
        FileExistsError: 已有清单时拒绝覆盖，须先读取既有轮次状态。
        OSError: 输入或产物读写失败。
    """
    target = ROOT / 'manifest.json'
    if target.exists():
        raise FileExistsError('已有 manifest，禁止重复导入或重置审核状态')
    raw = SOURCE.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    rows = raw.decode('utf-8').splitlines()
    valid: dict[int, dict] = {}
    records = []
    exact: dict[str, list[int]] = collections.defaultdict(list)
    schemas: collections.Counter = collections.Counter()
    types: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    missing: collections.Counter = collections.Counter()
    empty: collections.Counter = collections.Counter()
    for line, text in enumerate(rows, 1):
        entry = {'id': f'{sha[:12]}:L{line}', 'line': line}
        if not text.strip():
            entry['parse_status'] = 'blank'
        else:
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                entry.update(parse_status='quarantined', error=str(exc), error_column=exc.colno, raw_line=text)
            else:
                valid[line] = obj
                exact[canonical(obj)].append(line)
                entry['parse_status'] = 'valid'
                schemas['|'.join(sorted(obj))] += 1
                for field in ['instruction', 'input', 'output', 'memory_hook', 'emotion', 'scene', 'history', 'conversation_id', 'turn_id']:
                    if field not in obj:
                        missing[field] += 1
                for field, value in obj.items():
                    types[field][type(value).__name__] += 1
                    if value is None or value == '':
                        empty[field] += 1
        records.append(entry)
    representatives = {lines[0]: valid[lines[0]] for lines in exact.values()}
    parent = {line: line for line in representatives}

    def root(line: int) -> int:
        while parent[line] != line:
            parent[line] = parent[parent[line]]
            line = parent[line]
        return line

    def union(a: int, b: int) -> None:
        parent[root(b)] = root(a)

    indexes: dict[str, dict[str, list[int]]] = {}
    for kind in ['instruction', 'qa', 'output']:
        index: dict[str, list[int]] = collections.defaultdict(list)
        for line, obj in representatives.items():
            key = canonical([obj['input'], obj['output']]) if kind == 'qa' else obj[kind]
            index[key].append(line)
        indexes[kind] = index
        for lines in index.values():
            for line in lines[1:]:
                union(lines[0], line)
    components: dict[int, list[int]] = collections.defaultdict(list)
    for line in representatives:
        components[root(line)].append(line)
    groups = sorted(components.values(), key=min)
    exposed = {91, 101, 111, 827}
    forced_reps = {lines[0] for lines in exact.values() if exposed.intersection(lines)}
    eligible = [g for g in groups if not forced_reps.intersection(g)]
    rng = random.Random(SEED)
    rng.shuffle(eligible)
    reserved: set[int] = set()
    reserve_target = round(len(representatives) * 0.10)
    for group in eligible:
        if len(reserved) + len(group) <= reserve_target:
            reserved.update(group)
    analysis = sorted(set(representatives) - reserved)
    strata: dict[str, list[int]] = collections.defaultdict(list)
    for line in analysis:
        segment = min(2, (line - 1) * 3 // len(rows))
        schema = 'tagged' if 'scene' in representatives[line] else 'plain'
        strata[f'{segment}:{schema}'].append(line)
    chosen = sorted(forced_reps)
    sample_rng = random.Random(SEED + 1)
    for pool in strata.values():
        sample_rng.shuffle(pool)
    while len(chosen) < 120:
        for key in sorted(strata):
            pool = strata[key]
            while pool and pool[-1] in chosen:
                pool.pop()
            if pool and len(chosen) < 120:
                chosen.append(pool.pop())
    rep_for = {line: lines[0] for lines in exact.values() for line in lines}
    group_for = {line: f'G{min(g):04d}' for g in groups for line in g}
    for entry in records:
        line = entry['line']
        if line not in valid:
            continue
        rep = rep_for[line]
        entry.update(representative_line=rep, exact_group=f'D{rep:04d}', split_group=group_for[rep], split='reserved' if rep in reserved else 'analysis', review_status='unreviewed' if rep == line else 'exact_duplicate_mapped')
        if rep == line and rep in chosen:
            entry['selection'] = 'purposeful_preexposed' if rep in forced_reps else 'stratified_random'
    manifest = {
        'schema_version': 1, 'input_files': [{'file': SOURCE.name, 'actual_path': str(SOURCE), 'sha256': sha, 'bytes': len(raw), 'encoding': 'utf-8', 'sha256_after': None}],
        'audit': {'physical_lines': len(rows), 'parsed': len(valid), 'quarantined': sum(e['parse_status']=='quarantined' for e in records), 'blank': sum(e['parse_status']=='blank' for e in records), 'field_combinations': dict(schemas), 'field_types': dict(types), 'missing_fields': dict(missing), 'null_or_empty_fields': dict(empty), 'unique_records': len(representatives), 'exact_duplicate_groups': sum(len(g)>1 for g in exact.values()), 'extra_exact_copies': len(valid)-len(representatives)},
        'records': records,
        'exact_duplicate_groups': [{'id': f'D{lines[0]:04d}', 'representative_line': lines[0], 'source_lines': lines} for lines in exact.values() if len(lines)>1],
        'same_qa_groups': [{'id': f'Q{min(lines):04d}', 'representative_lines': lines, 'note': '相同 input/output；保留不同 instruction/标签，不另计为不同回答行为'} for lines in indexes['qa'].values() if len(lines)>1],
        'split_groups': [{'id': f'G{min(g):04d}', 'representative_lines': sorted(g), 'split': 'reserved' if g[0] in reserved else 'analysis'} for g in groups],
        'split_policy': {'seed': SEED, 'target_fraction': 0.1, 'reserved_count': len(reserved), 'analysis_count': len(analysis), 'basis': '精确去重后，以相同 instruction、相同 input/output、相同 output 的传递闭包整组划分；这些仅为保守防泄漏组，不宣称同一事件或独立来源。随机打乱未暴露组，累计不超过四舍五入10%的目标。', 'preexposed_lines': sorted(exposed), 'leakage_risks': ['不同字面模板或问答改写仍可能同源；没有来源元数据，不能保证独立盲测。', '预留集仅机械处理，不展示文本、不用于候选或反证。'], 'migrations': []},
        'sampling': {'seed': SEED+1, 'rule': '按代表行所在物理前中后三段×是否带标签分层，各层洗牌后按层名轮转抽取；先加入计划已暴露代表行，直到120条。标签不作场景真值。', 'selected_lines': sorted(chosen), 'purposeful_lines': sorted(forced_reps)},
        'reviewed_ids': [], 'unreviewed_analysis_ids': [f'{sha[:12]}:L{i}' for i in analysis], 'reserved_ids': [f'{sha[:12]}:L{i}' for i in sorted(reserved)],
        'rounds': [{'round_id': 'R001', 'status': 'in_progress', 'main_sample_count': 120, 'auxiliary_count': 0, 'method_reference': 'https://arxiv.org/html/2507.16799v2#S3.SS1', 'method_boundary': '仅借鉴分块分析后综合与人格/记忆/风格拆分；审计抽样证据机制是本项目设计。'}]
    }
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'audit': manifest['audit'], 'split': manifest['split_policy'], 'selected': sorted(chosen)}, ensure_ascii=False, indent=2))

def verify() -> None:
    """重新打开原始输入，核验产物来源、引文、分组与覆盖计数。

    Returns:
        无返回值；成功后保存 validation.json 并将本轮标记为待讨论。
    Raises:
        AssertionError: 输入变化、引用不匹配或清单计数不一致。
        OSError: 输入或分析产物无法读取。
    """
    manifest = json.loads((ROOT / 'manifest.json').read_text())
    source = manifest['input_files'][0]
    raw = Path(source['actual_path']).read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    assert sha == source['sha256']
    rows = raw.decode('utf-8').splitlines()
    records = {entry['line']: entry for entry in manifest['records']}
    assert set(records) == set(range(1, len(rows) + 1))
    valid: dict[int, dict] = {}
    exact: dict[str, list[int]] = collections.defaultdict(list)
    statuses: collections.Counter = collections.Counter()
    for line, text in enumerate(rows, 1):
        entry = records[line]
        assert entry['id'] == f'{sha[:12]}:L{line}'
        if not text.strip():
            assert entry['parse_status'] == 'blank'
        else:
            try:
                obj = json.loads(text)
            except json.JSONDecodeError as exc:
                assert entry['parse_status'] == 'quarantined'
                assert entry['error'] == str(exc) and entry['raw_line'] == text
            else:
                assert entry['parse_status'] == 'valid'
                valid[line] = obj
                exact[canonical(obj)].append(line)
        statuses[entry['parse_status']] += 1
    stats = manifest['audit']
    assert len(raw) == source['bytes']
    assert len(rows) == stats['physical_lines'] == sum(statuses.values())
    assert statuses == {'valid': stats['parsed'], 'quarantined': stats['quarantined'], 'blank': stats['blank']}
    assert len(exact) == stats['unique_records']
    assert len(valid) - len(exact) == stats['extra_exact_copies']
    assert sum(len(g) > 1 for g in exact.values()) == stats['exact_duplicate_groups']
    duplicate_map = {g['representative_line']: g['source_lines'] for g in manifest['exact_duplicate_groups']}
    assert duplicate_map == {g[0]: g for g in exact.values() if len(g) > 1}
    for lines in exact.values():
        for line in lines:
            assert records[line]['representative_line'] == lines[0]
            assert records[line]['split'] == records[lines[0]]['split']
    representatives = {g[0] for g in exact.values()}
    grouped = [line for g in manifest['split_groups'] for line in g['representative_lines']]
    assert len(grouped) == len(set(grouped)) and set(grouped) == representatives
    for g in manifest['split_groups']:
        assert all(records[line]['split_group'] == g['id'] and records[line]['split'] == g['split'] for line in g['representative_lines'])
    for kind in ['instruction', 'output', 'qa']:
        membership: dict[str, set[str]] = collections.defaultdict(set)
        for line in representatives:
            obj = valid[line]
            key = canonical([obj['input'], obj['output']]) if kind == 'qa' else obj[kind]
            membership[key].add(records[line]['split'])
        assert all(len(splits) == 1 for splits in membership.values())
    for g in manifest['related_evidence_groups']:
        assert len({records[line]['split_group'] for line in g['representative_lines']}) == 1
    evidence = [json.loads(s) for s in (ROOT / 'evidence.jsonl').read_text().splitlines()]
    hypotheses = [json.loads(s) for s in (ROOT / 'hypotheses.jsonl').read_text().splitlines()]
    by_id = {e['evidence_id']: e for e in evidence}
    reviewed = {e['source']['line'] for e in evidence}
    assert len(evidence) == len(by_id) == len(reviewed)
    quote_count = 0
    for e in evidence:
        line = e['source']['line']
        assert e['source']['file_sha256'] == sha and e['source']['id'] == records[line]['id']
        assert line in representatives and records[line]['split'] == 'analysis'
        assert e['original'] == valid[line]
        assert records[line]['evidence_id'] == e['evidence_id']
        for claim in e['claims'] + e.get('output_subclaims', []):
            assert claim['quote'] in valid[line][claim['field']]
            quote_count += 1
    main = {e['source']['line'] for e in evidence if e['review_role'] == 'main'}
    auxiliary = reviewed - main
    search = json.loads((ROOT / 'counter_search.json').read_text())
    assert main == set(manifest['sampling']['selected_lines']) and len(main) == 120
    assert auxiliary == {line for q in search for line in q['new_auxiliary_lines']}
    assert {q['hypothesis_id'] for q in search} == {h['hypothesis_id'] for h in hypotheses}
    for q in search:
        assert all(line in representatives and records[line]['split'] == 'analysis' for line in q['mechanical_match_lines'])
    for h in hypotheses:
        ids = set(h['support_evidence_ids'] + h['counter_evidence_ids'])
        assert ids <= set(by_id)
        assert all(h['hypothesis_id'] in by_id[eid]['candidate_ids'] for eid in ids)
        assert h['support_context_group_count'] == len(h['support_context_groups'])
        assert {eid for group in h['support_context_groups'] for eid in group} == set(h['support_evidence_ids'])
        assert h['support_split_group_count'] == len({by_id[eid]['split_group'] for eid in h['support_evidence_ids']})
        assert len({canonical(by_id[eid]['original']) for eid in h['support_evidence_ids']}) == len(h['support_evidence_ids'])
    reserved = {line for line in representatives if records[line]['split'] == 'reserved'}
    unreviewed = representatives - reserved - reviewed
    assert len(reserved) == manifest['split_policy']['reserved_count'] == 201
    assert len(reviewed) == 143 and len(auxiliary) == 23 and len(unreviewed) == 1668
    for field, lines in [('reviewed_ids', reviewed), ('reserved_ids', reserved), ('unreviewed_analysis_ids', unreviewed)]:
        assert set(manifest[field]) == {records[line]['id'] for line in lines}
    # 报告的完整字段引文再与原始行核对，不仅检查上一轮摘要。
    report = (ROOT / 'reports/R001.md').read_text()
    current_line = None
    report_quotes = 0
    import re
    for text in report.splitlines():
        locator = re.search(r'\*\*E\d+ · `[^`]+:L(\d+)`', text)
        if locator:
            current_line = int(locator.group(1))
        field_match = re.match(r'- (instruction（作者预设）|input|output)：(.*)', text)
        if field_match:
            field, quote = field_match.groups()
            field = 'instruction' if field.startswith('instruction') else field
            if field == 'output':
                quote = quote[2:-2]
            assert current_line is not None and quote == valid[current_line][field]
            report_quotes += 1
    assert report_quotes > 0
    source['sha256_after'] = sha
    manifest['rounds'][0]['status'] = 'completed_waiting_for_review'
    manifest['rounds'][0]['validation'] = 'validation.json'
    (ROOT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    result = {'status': 'passed', 'source_sha256_before': source['sha256'], 'source_sha256_after': sha,
              'physical_lines': len(rows), 'parsed': len(valid), 'unique': len(representatives),
              'main_reviewed': len(main), 'auxiliary_reviewed': len(auxiliary), 'reserved': len(reserved),
              'unreviewed_analysis': len(unreviewed), 'hypotheses': len(hypotheses),
              'evidence_quotes_checked': quote_count, 'report_full_field_quotes_checked': report_quotes,
              'checks': ['逐物理行解析状态与隔离原文', '精确重复及代表行', '关联组不跨划分', '预留未用于证据或反证检索', '每条证据全部原始字段', '引文逐字存在', '候选和证据双向链接', '覆盖计数', '输入前后哈希'],
              'limits': ['机械验证不等于人格结论正确或原作事实核验', '未识别的跨模板近重复仍可能泄漏', '本轮之后等待用户讨论']}
    (ROOT / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if sys.argv[1:] == ['--verify']:
        verify()
    else:
        audit()
