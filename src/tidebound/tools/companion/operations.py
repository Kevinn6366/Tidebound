"""只操作当前 Run 暂存状态的陪伴能力，成功提交由会话层负责。"""
import asyncio
from functools import partial
from uuid import uuid4

from src.tidebound.config import AgentSettings
from src.tidebound.errors import AgentError
from src.tidebound.llm import ModelClient
from src.tidebound.memory.rolling_summary import ConversationMemory
from src.tidebound.runtime.types import RunRecord
from src.tidebound.storage.companion import CompanionState, Followup, Interest, SavedFact
from src.tidebound.tools.companion.arguments import (
    CancelFollowupArguments,
    CheckInterestArguments,
    CreateFollowupArguments,
    FactArguments,
    InterestArguments,
    ListFollowupsArguments,
    ReadPastArguments,
    SearchArguments,
    UpdateFollowupArguments,
)
from src.tidebound.tools.internet.client import search_web
from src.tidebound.tools.internet.interest_updates import check_interest_updates
from src.tidebound.workflows.followup import summarize
from src.tidebound.workflows.websearch import search_workflow

MAX_ITEMS = 50


class CompanionTools:
    """运行时绑定已鉴权的历史与状态副本，模型无法指定其他账号。"""

    def __init__(self, history: list[RunRecord], record: RunRecord, state: CompanionState,
                 model: ModelClient, settings: AgentSettings, stop: asyncio.Event,
                 websearch_model: ModelClient | None = None,
                 character_system: str | None = None, memory: ConversationMemory | None = None) -> None:
        """绑定经过会话层鉴权的材料，不接受模型自行选择业务范围。

        Args:
            history: 已提交历史，进一步筛选当前时间线。
            record: 本轮执行及用户输入。
            state: 本轮可独立修改的状态副本。
            model: 工作流使用的模型。
            settings: 本轮提示词与预算配置。
            stop: 执行撤销信号。
            websearch_model: 独立搜索整理模型，未指定时沿用传入的模型替身。
            character_system: 主执行固定的角色规则，供搜索首段沿用。
            memory: 当前账号的长期摘要读取服务，读取不触发生成。
        """
        self.memory = memory
        self.history = [r for r in history if r.status == 'completed' and r.timeline_id == record.timeline_id]
        self.record = record
        self.state = state
        self.model = model
        self.websearch_model = websearch_model or model
        self.settings = settings
        self.stop = stop
        self.character_system = character_system

    def read_conversation_summary(self) -> dict[str, object]:
        """读取当前执行可见的长期摘要，不等待或触发后台生成。

        Returns:
            摘要、覆盖时间和未覆盖轮数；没有版本时明确返回状态。

        Raises:
            OSError: 摘要文件不可读。
            ValueError: 摘要版本损坏。
        """
        return self.memory.read() if self.memory else {'status': 'not_generated', 'summary': None}

    def evidence(self, source_run_id: str, quote: str) -> str:
        """确保事实来源是当前时间线上的用户原话。

        Args:
            source_run_id: current 表示当前 Run，其他值须是已提交有效 Run 标识。
            quote: 模型引用的非空用户原文片段。

        Returns:
            已确认原话来源的实际 Run 标识。

        Raises:
            AgentError: 来源不存在、来自角色或引文与原文不符。
        """
        source_id = self.record.run_id if source_run_id == 'current' else source_run_id
        source = next((r for r in [*self.history, self.record] if r.run_id == source_id), None)
        if source is None or source.kind != 'chat' or quote not in source.user_content:
            raise AgentError('invalid_evidence', 'evidence 必须逐字复制 source_run_id 对应的用户正文片段，不添加引号或用户说等前缀；本轮用户原话请把 source_run_id 设为 current，不要猜测 UUID。')

        return source.run_id

    def read_past(self, args: ReadPastArguments) -> dict[str, object]:
        """分页读取已提交有效对话正文，排除审计、工具内容和思考。

        Args:
            args: 关键词、可选轮次和分页范围。

        Returns:
            按时间排列的原文片段及下一页位置，截断会明确标记。
        """
        matches = [r for r in self.history if (not args.run_id or r.run_id == args.run_id)
                   and args.query.casefold() in (r.user_content + r.messages[-1].content).casefold()]
        page = matches[args.offset:args.offset + args.limit]
        return {'turns': [{'run_id': r.run_id, 'created_at': r.created_at,
                          'user': r.user_content[args.content_offset:args.content_offset + 1200],
                          'assistant': r.messages[-1].content[args.content_offset:args.content_offset + 1200],
                          'next_content_offset': args.content_offset + 1200
                          if max(len(r.user_content), len(r.messages[-1].content)) > args.content_offset + 1200 else None}
                         for r in page],
                'next_offset': args.offset + len(page) if args.offset + len(page) < len(matches) else None}

    def remember(self, args: FactArguments) -> dict[str, object]:
        """暂存有用户原话来源的事实，重复正文保持幂等。

        Args:
            args: 事实正文、来源轮次和精确引文。

        Returns:
            暂存的事实及提交状态。

        Raises:
            ValueError: 证据无效或已达到保存上限。
        """
        source_run_id = self.evidence(args.source_run_id, args.evidence)
        existing = next((f for f in self.state.facts if f.fact == args.fact), None)
        if existing is None:
            if len(self.state.facts) >= MAX_ITEMS:
                raise ValueError('事实已达上限')
            existing = SavedFact(id=uuid4().hex, **args.model_dump(exclude={"source_run_id"}), source_run_id=source_run_id)
            self.state.facts.append(existing)
        return {'fact': existing.model_dump(), 'commit': 'on_run_completion'}

    def list_followups(self, args: ListFollowupsArguments) -> dict[str, object]:
        """读取当前 Run 可见的跟进事项。

        Args:
            args: 要查看的事项状态。

        Returns:
            已绑定账号的跟进事项列表。
        """
        return {'followups': [f.model_dump() for f in self.state.followups
                              if args.status == 'all' or f.status == args.status]}

    async def change_followup(self, args: CreateFollowupArguments | UpdateFollowupArguments |
                              CancelFollowupArguments) -> dict[str, object]:
        """按已识别意图执行摘要工作流，成功后暂存创建、更新或取消。

        Args:
            args: 已校验的操作参数；更新与取消须指向已有事项。

        Returns:
            工作流整理后的事项与待提交状态。

        Raises:
            ValueError: 证据、事项或摘要无效，或事项达到上限。
            AgentError: 模型失败、预算不足或执行停止。
        """
        source_run_id = self.evidence(args.source_run_id, args.evidence)
        existing = None
        action = 'create'
        if isinstance(args, (UpdateFollowupArguments, CancelFollowupArguments)):
            existing = next((f for f in self.state.followups if f.id == args.followup_id), None)
            if existing is None:
                raise ValueError('事项不存在')
            action = 'cancel' if isinstance(args, CancelFollowupArguments) else 'update'
        elif len(self.state.followups) >= MAX_ITEMS:
            raise ValueError('跟进事项已达上限')
        # 重复的创建调用不再次请求模型，也不新增相同事项。
        if action == 'create':
            duplicate = next((f for f in self.state.followups if f.status == 'active'
                              and f.source_run_id == source_run_id and f.evidence == args.evidence), None)
            if duplicate:
                return {'followup': duplicate.model_dump(), 'commit': 'on_run_completion'}
        result = await summarize({'action': action, 'request': args.model_dump(),
                                  'previous': existing.model_dump() if existing else None,
                                  'conversation_memory': self.memory.read(include_uncovered=True) if self.memory else None},
                                 self.model, self.settings, self.stop)
        status = 'cancelled' if action == 'cancel' else getattr(args, 'status', 'active')
        item = Followup(id=existing.id if existing else uuid4().hex, summary=result.summary,
                        condition=result.condition, status=status, source_run_id=source_run_id,
                        evidence=args.evidence)
        if existing:
            self.state.followups[self.state.followups.index(existing)] = item
        else:
            self.state.followups.append(item)
        return {'followup': item.model_dump(), 'commit': 'on_run_completion'}

    def save_interest(self, args: InterestArguments) -> dict[str, object]:
        """暂存用户明确表达的兴趣主题，不启动离线监控。

        Args:
            args: 兴趣主题及对应用户原话。

        Returns:
            去重后的兴趣资料及提交状态。

        Raises:
            ValueError: 证据无效或数量已达到上限。
        """
        source_run_id = self.evidence(args.source_run_id, args.evidence)
        item = next((i for i in self.state.interests if i.topic.casefold() == args.topic.casefold()), None)
        if item is None:
            if len(self.state.interests) >= MAX_ITEMS:
                raise ValueError('兴趣已达上限')
            item = Interest(id=uuid4().hex, **args.model_dump(exclude={"source_run_id"}), source_run_id=source_run_id)
            self.state.interests.append(item)
        return {'interest': item.model_dump(), 'commit': 'on_run_completion'}


    async def search(self, args: SearchArguments) -> dict[str, object]:
        """先整理聊天语境，再检索并返回阅读印象。

        Args:
            args: 模型选定的公开搜索词。

        Returns:
            阅读印象和来源或安全的配置错误，不返回原始搜索摘要。

        Raises:
            AgentError: 停止或节点预算失败。
            ValueError: 工作流输出非法。
            OSError: 搜索服务不可用。
        """
        key = self.settings.search_api_key.get_secret_value()
        if not key.strip():
            return await search_web(args.query, key)
        return await search_workflow(args.query, self.history, self.record,
                                     partial(search_web, args.query, key),
                                     self.websearch_model, self.settings, self.stop, character_system=self.character_system)

    async def interest_updates(self, args: CheckInterestArguments) -> dict[str, object]:
        """通过同一阅读工作流检查兴趣，仅整理成功后暂存检查状态。

        Args:
            args: 当前账号已有兴趣标识。

        Returns:
            整理后的印象、来源与暂存状态说明。

        Raises:
            ValueError: 兴趣不存在或节点结果无效。
            AgentError: 执行停止或预算失败。
            OSError: 搜索请求失败。
        """
        candidate = self.state.model_copy(deep=True)
        interest = next((item for item in candidate.interests if item.id == args.interest_id), None)
        if interest is None:
            raise ValueError('兴趣不存在')
        key = self.settings.search_api_key.get_secret_value()
        if not key.strip():
            return await search_web(interest.topic, key)
        result = await search_workflow(interest.topic + ' 最新进展', self.history, self.record,
            partial(check_interest_updates, candidate, args.interest_id, key),
            self.websearch_model, self.settings, self.stop, character_system=self.character_system)
        if 'error' in result:
            return result
        self.state.interests = candidate.interests
        return {**result, 'interest_id': interest.id, 'checked_at': interest.checked_at,
                'meaning': 'newly_seen_search_results', 'commit': 'on_run_completion'}
