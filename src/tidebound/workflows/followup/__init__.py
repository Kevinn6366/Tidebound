"""跟进工具进入摘要节点，验证后由业务入口暂存状态，随主 Run 提交。"""
from importlib import import_module

summarize = import_module('.N01-Summarize', __name__).summarize
