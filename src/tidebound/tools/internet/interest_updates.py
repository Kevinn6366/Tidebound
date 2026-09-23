"""按需检查已保存兴趣，以成功提交的 URL 记录区分新增结果。"""
from datetime import UTC, datetime

from src.tidebound.storage.companion import CompanionState
from src.tidebound.tools.internet.client import search_web


async def check_interest_updates(state: CompanionState, interest_id: str, api_key: str) -> dict[str, object]:
    """查询一个兴趣的近况并暂存已见链接，不创建定时推送。

    Args:
        state: 当前 Run 独有的状态副本。
        interest_id: 属于当前账号的兴趣标识。
        api_key: 服务端搜索配置。

    Returns:
        新检索到的结果及检查时间；搜索失败时不推进检查状态。

    Raises:
        ValueError: 兴趣标识不存在或供应商数据非法。
        OSError: 网络失败。
    """
    interest = next((item for item in state.interests if item.id == interest_id), None)
    if interest is None:
        raise ValueError('兴趣不存在')
    result = await search_web(interest.topic + ' 最新进展', api_key)
    if 'error' in result:
        return result
    rows = result['results']
    updates = [row for row in rows if row['url'] not in interest.seen_urls]
    interest.seen_urls = list(dict.fromkeys([*interest.seen_urls, *(row['url'] for row in rows)]))[-100:]
    interest.checked_at = datetime.now(UTC).isoformat()
    return {'interest_id': interest.id, 'results': updates, 'checked_at': interest.checked_at,
            'meaning': 'newly_seen_search_results', 'untrusted': True, 'commit': 'on_run_completion'}
