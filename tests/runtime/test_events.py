"""结构化事件的失败、取消、轮换与敏感正文边界。"""
import asyncio
import json
from pathlib import Path

import pytest

from src.tidebound.config import AgentSettings
from src.tidebound.runtime.events import emit_event, trace_operation
from src.tidebound.storage.model_requests import request_run


def test_events_capture_failures_cancel_and_rotate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """debug 关闭仍记录起止，错误原文不会落盘，轮换后可继续写。"""
    settings = AgentSettings(data_dir=tmp_path, model='fixture', debug=False)
    token = request_run.set(('owner', 'run'))
    try:
        with pytest.raises(ValueError), trace_operation(settings, 'workflow', 'fixture'):
            raise ValueError('SECRET_PROMPT_AND_KEY')
        with pytest.raises(asyncio.CancelledError), trace_operation(settings, 'tool', 'search_web'):
            raise asyncio.CancelledError()
        with trace_operation(settings, 'tool', 'search_web') as outcome:
            outcome['error_code'] = 'invalid_arguments'
    finally:
        request_run.reset(token)
    path = tmp_path / 'runtime-events.jsonl'
    raw = path.read_text()
    assert 'SECRET_PROMPT_AND_KEY' not in raw
    rows = [json.loads(line) for line in raw.splitlines()]
    assert [row['status'] for row in rows] == ['started', 'failed', 'started', 'stopped', 'started', 'failed']
    assert all(row['run_id'] == 'run' for row in rows)
    assert rows[0]['event_id'] == rows[1]['event_id']
    assert rows[1]['duration_ms'] >= 0
    monkeypatch.setattr('src.tidebound.runtime.events.MAX_EVENT_BYTES', 1)
    emit_event(settings, 'run', 'chat', 'started')
    assert path.with_suffix('.previous.jsonl').exists()
    assert len(path.read_text().splitlines()) == 1
