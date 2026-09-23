"""主聊天渠道的配置选择，凭据仅保留在运行时快照。"""
from urllib.parse import urlsplit

from pydantic import BaseModel

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.storage.model_channel import ChannelId, ChannelSelection, ModelChannelStore

SILICONFLOW_BASE_URL = 'https://api.siliconflow.cn/v1'
SILICONFLOW_MODEL = 'zai-org/GLM-5.3'


class ChannelView(BaseModel):
    id: ChannelId
    name: str
    model: str
    base_url: str
    ready: bool


class ChannelsView(BaseModel):
    selected: ChannelId
    channels: list[ChannelView]


class ModelChannels:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.store = ModelChannelStore(settings.data_dir)

    def resolve(self, channel: ChannelId | None = None) -> AgentSettings:
        """构造独立主模型配置，调用方在 Run 开始时固定它。

        Args:
            channel: 指定渠道；省略时读取持久化选择。

        Returns:
            保留预算等公共配置、替换模型连接参数的快照。

        Raises:
            OSError: 选择文件无法读取。
            ValueError: 选择文件损坏。
        """
        selected = channel or self.store.load().channel
        if selected == 'codex789':
            return self.settings.model_copy(update={
                'base_url': self.settings.relay_base_url,
                'model': self.settings.relay_model,
                'api_key': self.settings.relay_api_key,
            })
        return self.settings.model_copy()

    def view(self) -> ChannelsView:
        """提供管理员可见的渠道状态，不序列化任何凭据。

        Returns:
            当前选择及各渠道配置是否齐备。

        Raises:
            OSError: 无法读取选择。
            ValueError: 已保存选择损坏。
        """
        channels: list[ChannelView] = []
        for channel, name in [('siliconflow', '硅基流动'), ('codex789', 'codex789')]:
            settings = self.resolve(channel)
            url = urlsplit(settings.base_url)
            valid = bool(url.scheme in ('http', 'https') and url.hostname
                         and not url.username and not url.password and not url.query and not url.fragment)
            channels.append(ChannelView(id=channel, name=name, model=settings.model,
                base_url=settings.base_url if valid else '',
                ready=bool(valid and settings.model.strip() and settings.api_key.get_secret_value().strip())))
        return ChannelsView(selected=self.store.load().channel, channels=channels)

    def select(self, selection: ChannelSelection) -> ChannelsView:
        """校验渠道配置后持久化选择，仅影响后续 Run。

        Args:
            selection: 管理员选择的已知渠道。

        Returns:
            持久化成功后的安全状态视图。

        Raises:
            AgentError: 当前模式不支持切换或目标配置缺失。
            OSError: 选择无法持久化。
        """
        if self.settings.mode != 'dev':
            raise AgentError('dev_only', '当前只支持单 worker dev 渠道切换。', 503)
        target = next(item for item in self.view().channels if item.id == selection.channel)
        if not target.ready:
            raise AgentError('channel_not_configured', '请先在后端配置该渠道的地址、模型和 API Key，再重启服务。', 409)
        self.store.save(selection)
        return self.view()
