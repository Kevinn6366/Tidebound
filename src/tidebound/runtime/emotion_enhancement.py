"""管理员账号的云端情感增强配置及执行快照。"""

from urllib.parse import urlsplit

from pydantic import BaseModel

from src.tidebound.config import AgentSettings
from src.tidebound.context.budget import FORMAT_MARGIN
from src.tidebound.errors import AgentError
from src.tidebound.llm import ChatCompletionsClient, ModelClient
from src.tidebound.prompting import load_prompt_bundles
from src.tidebound.storage.emotion_enhancement import EmotionEnhancementStore, EmotionSetting
from src.tidebound.workflows.emotion_enhancement import ENHANCEMENT_PURPOSE, EmotionEnhancementRun


class EmotionEnhancementView(BaseModel):
    """只暴露开关和配置齐备状态，不包含地址、提示词或凭据。"""

    enabled: bool
    configured: bool
    model: str


class EmotionEnhancement:
    """将账号开关与固定的服务端 instruct 配置组合，不修改主模型设置。"""

    def __init__(self, settings: AgentSettings, model: ModelClient | None = None) -> None:
        self.settings = settings
        self.model = model
        self.store = EmotionEnhancementStore(settings.data_dir)

    def _require_dev(self) -> None:
        if self.settings.mode != "dev":
            raise AgentError("dev_only", "云端情感增强仅在开发环境开放。", 403)

    def _configured(self) -> bool:
        """检查独立渠道配置及预算是否齐备，不发起网络探测。

        Returns:
            地址、模型、凭据与最低预算全部可用时为真。
        """
        try:
            url = urlsplit(self.settings.emotion_base_url)
            valid = bool(url.scheme in ("http", "https") and url.hostname and not url.username
                         and not url.password and not url.query and not url.fragment)
            _ = url.port
        except ValueError:
            return False
        return bool(valid and self.settings.emotion_model.strip()
                    and self.settings.emotion_api_key.get_secret_value().strip()
                    and self.settings.emotion_context_limit > self.settings.emotion_max_output_tokens + FORMAT_MARGIN)

    def view(self, owner: str) -> EmotionEnhancementView:
        """读取当前账号的安全配置视图。

        Args:
            owner: 通信层确认的账号内部范围。

        Returns:
            当前账号开关、服务端配置是否齐备及模型名。

        Raises:
            AgentError: 非开发环境。
            OSError: 设置不可读。
            ValueError: 设置文件内容损坏。
        """
        self._require_dev()
        return EmotionEnhancementView(enabled=self.store.load(owner).enabled,
                                      configured=self._configured(), model=self.settings.emotion_model)

    def select(self, owner: str, enabled: bool) -> EmotionEnhancementView:
        """持久化当前账号下一轮生效的开关，开启前验证配置和提示词。

        Args:
            owner: 经服务端授权的管理员账号范围。
            enabled: 是否为后续回复启用云端润色。

        Returns:
            服务端确认保存后的配置视图。

        Raises:
            AgentError: 非 dev、启用所需配置缺失或提示词无法读取。
            OSError: 开关写入失败。
        """
        self._require_dev()
        if enabled:
            self._prepare_run()
        self.store.save(owner, EmotionSetting(enabled=enabled))
        return self.view(owner)

    def prepare(self, owner: str) -> EmotionEnhancementRun | None:
        """在 Run 启动前固定账号开关、独立渠道和角色提示词。

        Args:
            owner: 本次 Run 所属账号。

        Returns:
            不受后续开关修改影响的增强快照，未开启时为空。

        Raises:
            AgentError: 已开启但环境、配置或提示词不可用。
            OSError: 持久化开关不可读。
            ValueError: 持久化开关损坏。
        """
        if not self.store.load(owner).enabled:
            return None
        self._require_dev()
        return self._prepare_run()

    def _prepare_run(self) -> EmotionEnhancementRun:
        """验证独立连接配置，并加载本次增强唯一的指令包。

        Returns:
            关闭调试流与主模型推理参数的润色调用快照。

        Raises:
            AgentError: 配置不完整或提示词包无效。
        """
        if not self._configured():
            raise AgentError("emotion_not_configured", "请先在后端配置情感增强模型的地址、模型 Code 和 Key，再重启服务。", 409)
        settings = self.settings.model_copy(update={
            "base_url": self.settings.emotion_base_url, "model": self.settings.emotion_model,
            "api_key": self.settings.emotion_api_key, "timeout_seconds": self.settings.emotion_timeout_seconds,
            "max_output_tokens": self.settings.emotion_max_output_tokens,
            "context_limit": self.settings.emotion_context_limit, "reasoning_effort": None, "debug": False,
        })
        system = load_prompt_bundles(settings.prompts_dir, (ENHANCEMENT_PURPOSE,)).content
        instruction = load_prompt_bundles(settings.prompts_dir, (ENHANCEMENT_PURPOSE + ".instruction",)).content
        return EmotionEnhancementRun(settings, system, self.model or ChatCompletionsClient(settings), instruction)
