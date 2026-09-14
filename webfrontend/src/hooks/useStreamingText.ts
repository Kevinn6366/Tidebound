import { useEffect, useRef, useState } from 'react';

/**
 * 将正在到达的 LLM 正文逐字显示，完成后继续显示队列中剩余文字。
 * @param text - 当前已收到的完整正文或分页正文。
 * @param identity - 回复与页码标识，切换消息时重置。
 * @param streaming - 当前是否仍在生成，历史消息直接展示。
 * @returns 已逐字展示的文本；不会生成模型尚未返回的内容。
 */
export function useStreamingText(text: string, identity: string, streaming: boolean): string {
  const [visible, setVisible] = useState('');
  const progress = useRef({ identity: '', count: 0, target: '', animate: false });
  useEffect(() => {
    const state = progress.current;
    if (state.identity !== identity) {
      state.identity = identity;
      state.count = 0;
      state.animate = streaming;
      state.target = '';
    }
    if (!text.startsWith(state.target)) state.count = 0;
    state.target = text;
    const characters = Array.from(text);
    let frame = 0;
    let last = 0;
    /** 随动画帧逐字消费已收到的正文，避免拆开 Unicode 代理对。 */
    function tick(now: number): void {
      if (!state.animate) state.count = characters.length;
      else if (now - last >= 20) { state.count = Math.min(state.count + 1, characters.length); last = now; }
      setVisible(characters.slice(0, state.count).join(''));
      if (state.count < characters.length) frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [text, identity, streaming]);
  return visible;
}
