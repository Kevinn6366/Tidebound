export interface ChatMessageInput {
  content: string;
  attachments: { type: string; name: string; data: string }[];
}

/**
 * 将对话框输入发送至 backend 的接口，不组装提示词或模型请求。
 * @param input - 用户正文及附件，不含旧历史、模型密钥或系统提示词。
 * @returns 请求处理完成时兑现；当前后端为空实现，因此返回明确错误。
 * @throws 后端未接入、响应非法或网络失败时抛出错误。
 */
export async function submitChatMessage(input: ChatMessageInput): Promise<void> {
  const response = await fetch('/api/chat/messages', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input), credentials: 'same-origin',
  });
  const data: unknown = await response.json();
  if (!response.ok && typeof data === 'object' && data !== null && 'detail' in data) {
    const detail: unknown = data.detail;
    if (typeof detail === 'object' && detail !== null && 'message' in detail && typeof detail.message === 'string') {
      throw new Error(detail.message);
    }
  }
  throw new Error(response.ok ? '对话后端尚未提供合法响应' : `发送失败（${response.status}）`);
}
