"""随已完成 Run 原子提交的陪伴状态，不建立第二份会话事实来源。"""
from typing import Literal

from pydantic import BaseModel, Field


class SavedFact(BaseModel):
    id: str
    fact: str
    source_run_id: str
    evidence: str


class Followup(BaseModel):
    id: str
    summary: str
    condition: str
    status: Literal['active', 'completed', 'cancelled'] = 'active'
    source_run_id: str
    evidence: str


class Interest(BaseModel):
    id: str
    topic: str
    source_run_id: str
    evidence: str
    seen_urls: list[str] = Field(default_factory=list)
    checked_at: str | None = None


class CompanionState(BaseModel):
    facts: list[SavedFact] = Field(default_factory=list)
    followups: list[Followup] = Field(default_factory=list)
    interests: list[Interest] = Field(default_factory=list)
