"""按 master.yaml 加载本地 bundle，不访问远端或执行动态模板。"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.tidebound.errors import AgentError


class UniqueKeyLoader(yaml.SafeLoader):
    """拒绝重复映射键，避免配置被 YAML 静默覆盖。"""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[object, object]:
        """构造唯一键映射。

        Args:
            node: YAML 映射节点。
            deep: 是否递归构造子节点。

        Returns:
            无重复键的映射。

        Raises:
            ValueError: 同一映射出现重复键。
        """
        result: dict[object, object] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise ValueError("配置键必须是唯一字符串")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    variant: str
    name: str
    segments: list[Segment] = Field(min_length=1)


class Language(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: str
    variants: list[Variant] = Field(min_length=1)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompts: dict[str, list[Language]]


@dataclass(frozen=True)
class PromptBundle:
    """解析后的静态提示词及其来源。"""

    name: str
    content: str
    files: tuple[Path, ...]


def load_character_bundle(root: Path) -> PromptBundle:
    """加载独立的角色提示词，不附带工具使用规则。

    Args:
        root: 包含 master.yaml 的提示词目录。

    Returns:
        角色包正文及文件来源。

    Raises:
        AgentError: 角色包或 manifest 不合法。
    """
    return load_prompt_bundles(root, ("chat.character",))


def load_chat_system(root: Path) -> PromptBundle:
    """加载角色、安全约定及可选世界观，组装主对话的初始 system。

    Args:
        root: 同时包含角色和系统安全 bundle 的提示词根目录。

    Returns:
        按角色、安全约定、世界观顺序组合的正文和文件来源，名称沿用角色包。

    Raises:
        AgentError: 任一必需 bundle 缺失或不合法。
    """
    return load_prompt_bundles(root, ("chat.character", "chat.safety", "world.worldview"))


def load_tool_injections(root: Path, purposes: tuple[str, ...]) -> str:
    """加载本批工具调用对应的临时规则，供下一次模型请求使用。

    Args:
        root: 包含 master.yaml 的提示词目录。
        purposes: 已调用工具声明的注入标识，按调用顺序去重。

    Returns:
        拼接后的工具规则；无标识时返回空文本。

    Raises:
        AgentError: 注入标识、manifest 或规则文件不合法。
    """
    if not purposes:
        return ""
    if any(not purpose.startswith("tools.injection.") for purpose in purposes):
        raise AgentError("invalid_prompt_bundle", "工具注入标识非法。", 503)
    return load_prompt_bundles(root, purposes).content


def load_prompt_bundles(root: Path, purposes: tuple[str, ...]) -> PromptBundle:
    """按逻辑标识加载静态提示词包并保留来源。

    Args:
        root: 包含 master.yaml 的提示词根目录。
        purposes: 非空的包标识列表，按顺序去重拼接。

    Returns:
        选中包的内容与文件来源，名称取第一个包；世界观缺失或为空时不追加正文。

    Raises:
        AgentError: 标识缺失、manifest、路径或模板不合法。
    """
    try:
        root = root.resolve(strict=True)
        manifest = Manifest.model_validate(yaml.load(
            (root / "master.yaml").read_text(encoding="utf-8"), Loader=UniqueKeyLoader,
        ))
        if "chat.character" not in manifest.prompts or any(
            purpose not in {"chat.character", "chat.safety", "chat.meet", "world.worldview",
                            "context.compaction", "context.injection.summary", "workflow.followup", "companion.rules",
                            "tools.websearch.context", "tools.websearch.impression", "tools.websearch.reaction"}
            and not purpose.startswith("tools.injection.")
            for purpose in manifest.prompts
        ):
            raise ValueError("不支持的提示词 purpose")
        variants: dict[str, Variant] = {}
        names: set[str] = set()
        for purpose, languages in manifest.prompts.items():
            if len(languages) != 1 or languages[0].language != "zh" or len(languages[0].variants) != 1:
                raise ValueError("每个 purpose 只支持一个中文默认包")
            variant = languages[0].variants[0]
            if variant.variant != "-" or not variant.name.strip() or variant.name in names:
                raise ValueError("包名称重复或默认变体非法")
            variants[purpose] = variant
            names.add(variant.name)
        if not purposes or any(purpose not in variants and purpose != "world.worldview" for purpose in purposes):
            raise ValueError("工具注入 purpose 非法或缺失")
        files: list[Path] = []
        parts: list[str] = []
        for purpose in dict.fromkeys(purposes):
            if purpose not in variants:
                continue
            for segment in variants[purpose].segments:
                path, content = load_prompt_segment(root, segment, purpose=purpose)
                if path in files:
                    raise ValueError("提示词文件重复引用")
                files.append(path)
                if content:
                    parts.append(content)
        first = variants.get(purposes[0])
        return PromptBundle(first.name if first else purposes[0], "\n\n".join(parts), tuple(files))
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
        raise AgentError("invalid_prompt_bundle", "提示词包无法加载，请检查 master.yaml 与引用文件。", 503) from error


def load_prompt_segment(root: Path, segment: Segment, *, purpose: str) -> tuple[Path, str]:
    """读取范围内的静态提示词文件并去除版本注释。

    Args:
        root: 已解析的提示词根目录。
        segment: manifest 中待加载的文件引用。
        purpose: 所属包的逻辑标识，仅世界观允许文件缺失或正文为空。

    Returns:
        真实文件路径与去除版本注释后的正文。

    Raises:
        OSError: 文件无法读取。
        ValueError: 引用越界、类型非法、正文为空或包含动态模板。
    """
    if not segment.content.startswith("@"):
        raise ValueError("segment 必须引用文件")
    path = (root / segment.content[1:]).resolve()
    if not path.is_relative_to(root) or path.suffix != ".md":
        raise ValueError("文件越界或类型非法")
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if purpose != "world.worldview":
            raise
        return path, ""
    content = re.sub(r"\{\{/\*.*?\*/\}\}", "", content, flags=re.DOTALL).strip()
    if (not content and purpose != "world.worldview") or "{{" in content or "}}" in content:
        raise ValueError("内容为空或使用了尚未支持的动态模板")
    return path, content
