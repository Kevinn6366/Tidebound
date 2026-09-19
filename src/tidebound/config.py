"""仅在后端加载模型配置，首版限定本地 dev。"""

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr

ROOT = Path(__file__).resolve().parents[2]


class AgentSettings(BaseModel):
    """首版模型调用和本地执行参数。"""

    mode: str = "dev"
    base_url: str = ""
    api_key: SecretStr = SecretStr("")
    model: str = ""
    relay_base_url: str = "https://www.codex789.com/v1"
    relay_api_key: SecretStr = SecretStr("")
    relay_model: str = "glm-5.3"
    search_api_key: SecretStr = SecretStr("")
    websearch_model: str = "deepseek-ai/DeepSeek-V4-Flash"
    websearch_base_url: str = ""
    websearch_api_key: SecretStr = SecretStr("")
    meet_model: str = "glm-5.3-flash"
    meet_base_url: str = ""
    meet_api_key: SecretStr = SecretStr("")
    meet_timeout_seconds: float = Field(default=30, gt=0, le=120)
    debug: bool = False
    reasoning_effort: Literal["low", "high", "max"] | None = None
    timezone: str = "Asia/Shanghai"
    prompts_dir: Path = ROOT / "prompts"
    data_dir: Path = ROOT / "data" / "agent"
    max_model_calls: int = Field(default=4, ge=1, le=20)
    max_output_tokens: int = Field(default=2048, ge=1)
    context_limit: int = Field(default=32768, ge=2048)
    timeout_seconds: float = Field(default=120, gt=0, le=600)

    @classmethod
    def from_env(cls) -> "AgentSettings":
        """读取本地 .env 和环境变量，环境变量优先。

        Returns:
            已完成类型和范围校验的配置；缺失模型可在界面启动后提示。

        Raises:
            ValueError: 数字或范围配置非法。
        """
        load_dotenv(ROOT / ".env", override=False)
        fields = {
            "relay_base_url": "TIDEBOUND_RELAY_BASE_URL",
            "relay_api_key": "TIDEBOUND_RELAY_API_KEY",
            "relay_model": "TIDEBOUND_RELAY_MODEL",
            "search_api_key": "TIDEBOUND_BOCHA_API_KEY",
            "websearch_model": "TIDEBOUND_WEBSEARCH_MODEL",
            "websearch_base_url": "TIDEBOUND_WEBSEARCH_BASE_URL",
            "websearch_api_key": "TIDEBOUND_WEBSEARCH_API_KEY",
            "meet_model": "TIDEBOUND_MEET_MODEL",
            "meet_base_url": "TIDEBOUND_MEET_BASE_URL",
            "meet_api_key": "TIDEBOUND_MEET_API_KEY",
            "meet_timeout_seconds": "TIDEBOUND_MEET_TIMEOUT",
            "debug": "TIDEBOUND_DEBUG",
            "reasoning_effort": "TIDEBOUND_LLM_REASONING_EFFORT",
            "mode": "TIDEBOUND_MODE", "base_url": "TIDEBOUND_LLM_BASE_URL",
            "api_key": "TIDEBOUND_LLM_API_KEY", "model": "TIDEBOUND_LLM_MODEL",
            "timezone": "TIDEBOUND_TIMEZONE", "prompts_dir": "TIDEBOUND_PROMPTS_DIR",
            "data_dir": "TIDEBOUND_AGENT_DATA_DIR", "max_model_calls": "TIDEBOUND_MAX_MODEL_CALLS",
            "max_output_tokens": "TIDEBOUND_MAX_OUTPUT_TOKENS", "context_limit": "TIDEBOUND_CONTEXT_LIMIT",
            "timeout_seconds": "TIDEBOUND_RUN_TIMEOUT",
        }
        return cls.model_validate({key: os.environ[name] for key, name in fields.items() if name in os.environ})
