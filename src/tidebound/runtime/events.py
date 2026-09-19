"""与流式正文分离的有界执行事件日志，debug 关闭时仍记录。"""
import asyncio
import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.storage.model_requests import request_purpose, request_run, request_step

MAX_EVENT_BYTES = 2 * 1024 * 1024
_LOCK = RLock()
logger = logging.getLogger(__name__)


def emit_event(settings: AgentSettings, kind: str, name: str, status: str, *,
               event_id: str = '', duration_ms: int | None = None, error_code: str = '',
               run: tuple[str, str] | None = None) -> None:
    """追加不含输入、结果正文或凭据的阶段事件，最多保留两个日志文件。

    Args:
        settings: 本次执行的固定配置，用于日志目录和模型名。
        kind: 代码确定的事件类别。
        name: 代码确定的阶段名，不能传入任意用户正文。
        status: 开始、成功、失败、停止等执行状态。
        event_id: 同一步骤的关联标识。
        duration_ms: 步骤耗时，开始事件为空。
        error_code: 安全错误码，不包含异常原文。
        run: 可选账号和 Run 标识，否则读取当前执行上下文。

    Raises:
        日志 I/O 错误记录到应用 logger，不中断用户执行。
    """
    owner, run_id = run or request_run.get() or ('', '')
    safe_code = error_code if re.fullmatch(r'[A-Za-z0-9_]{0,80}', error_code) else 'operation_failed'
    data = {'time': datetime.now(UTC).isoformat(), 'owner': owner, 'run_id': run_id,
            'event_id': event_id, 'kind': kind, 'name': name, 'status': status,
            'duration_ms': duration_ms, 'step': request_step.get(), 'purpose': request_purpose.get(),
            'model': settings.model if kind == 'model' else '', 'error_code': safe_code}
    path = settings.data_dir / 'runtime-events.jsonl'
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and path.stat().st_size >= MAX_EVENT_BYTES:
                path.replace(path.with_suffix('.previous.jsonl'))
            with path.open('a', encoding='utf-8') as output:
                output.write(json.dumps(data, ensure_ascii=False) + '\n')
    except OSError as error:
        logger.error('Runtime event log unavailable: %s', type(error).__name__)


@contextmanager
def trace_operation(settings: AgentSettings, kind: str, name: str) -> Iterator[dict[str, str]]:
    """记录步骤起止和耗时，异常仅记录类型或安全码后继续抛出。

    Args:
        settings: 当前模型及存储配置。
        kind: 事件类别。
        name: 代码确定的步骤名。

    Yields:
        调用方可设置 error_code，标记以安全结果返回的业务失败。

    Raises:
        BaseException: 原操作异常按原语义继续传播，包括取消。
    """
    event_id = uuid4().hex
    started = time.monotonic()
    outcome: dict[str, str] = {}
    emit_event(settings, kind, name, 'started', event_id=event_id)
    status = 'completed'
    try:
        yield outcome
        if outcome.get('error_code'):
            status = 'failed'
    except BaseException as error:
        status = 'stopped' if isinstance(error, asyncio.CancelledError) or (
            isinstance(error, AgentError) and error.code == 'run_stopped') else 'failed'
        outcome['error_code'] = error.code if isinstance(error, AgentError) else type(error).__name__
        raise
    finally:
        emit_event(settings, kind, name, status, event_id=event_id,
                   duration_ms=round((time.monotonic() - started) * 1000), error_code=outcome.get('error_code', ''))
