"""陪伴工具的严格输入约束，账号和时间线始终由运行时绑定。"""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Arguments(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, str_strip_whitespace=True)


class ReadPastArguments(Arguments):
    query: str = Field(default='', max_length=200)
    run_id: str | None = Field(default=None, max_length=36)
    content_offset: int = Field(default=0, ge=0)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=3, ge=1, le=5)


class FactArguments(Arguments):
    fact: str = Field(min_length=1, max_length=300)
    source_run_id: str = Field(default="current", min_length=1, max_length=36, description="本轮用户原话用 current；仅引用历史原话时填历史工具返回的 run_id。")
    evidence: str = Field(min_length=1, max_length=500, description="逐字复制用户正文中的连续原文，不添加引号、用户说等前缀，不改写。")


class CreateFollowupArguments(Arguments):
    topic: str = Field(min_length=1, max_length=300)
    condition: str = Field(default='下次相关对话时自然关心', max_length=200)
    source_run_id: str = Field(default="current", min_length=1, max_length=36, description="本轮用户原话用 current；仅引用历史原话时填历史工具返回的 run_id。")
    evidence: str = Field(min_length=1, max_length=500, description="逐字复制用户正文中的连续原文，不添加引号、用户说等前缀，不改写。")


class UpdateFollowupArguments(CreateFollowupArguments):
    followup_id: str = Field(min_length=1, max_length=36)
    status: Literal['active', 'completed'] = 'active'


class CancelFollowupArguments(Arguments):
    followup_id: str = Field(min_length=1, max_length=36)
    source_run_id: str = Field(default="current", min_length=1, max_length=36, description="本轮用户原话用 current；仅引用历史原话时填历史工具返回的 run_id。")
    evidence: str = Field(min_length=1, max_length=500, description="逐字复制用户正文中的连续原文，不添加引号、用户说等前缀，不改写。")


class ListFollowupsArguments(Arguments):
    status: Literal['active', 'completed', 'cancelled', 'all'] = 'active'


class SearchArguments(Arguments):
    query: str = Field(min_length=1, max_length=300)


class WebpageArguments(Arguments):
    url: str = Field(min_length=1, max_length=2048)


class WeatherArguments(Arguments):
    location: str = Field(min_length=1, max_length=100)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class InterestArguments(Arguments):
    topic: str = Field(min_length=1, max_length=200)
    source_run_id: str = Field(default="current", min_length=1, max_length=36, description="本轮用户原话用 current；仅引用历史原话时填历史工具返回的 run_id。")
    evidence: str = Field(min_length=1, max_length=500, description="逐字复制用户正文中的连续原文，不添加引号、用户说等前缀，不改写。")


class CheckInterestArguments(Arguments):
    interest_id: str = Field(min_length=1, max_length=36)
