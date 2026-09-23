"""本地开发终端调试输出，仅展示模型公开返回的字段。"""
import re
import sys


class TerminalDebug:
    """按阶段流式输出，保留请求标签，不输出请求头或系统提示词。"""

    def __init__(self, enabled: bool, label: str) -> None:
        self.enabled = enabled
        self.label = label
        self.phase = ""

    def write(self, phase: str, text: str) -> None:
        """将接口返回的增量内容立即写入终端。

        Args:
            phase: 思考、回复、工具或执行状态等阶段名。
            text: 要显示的增量内容，终端控制字符会被移除。
        """
        if not self.enabled or not text:
            return
        if phase != self.phase:
            sys.stderr.write(f"\n[{self.label}] {phase}\n")
            self.phase = phase
        sys.stderr.write(re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", text))
        sys.stderr.flush()
