"""按 master.yaml 加载本地 bundle，不访问远端或执行动态模板。"""

import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.errors import AgentError


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
    """校验并加载唯一的中文 chat.character 默认包。

    Args:
        root: 可整体替换的提示词目录，必须包含 master.yaml。

    Returns:
        按 segment 顺序组装且去掉版本注释的提示词。

    Raises:
        AgentError: manifest、路径、名称或模板不符合首版支持范围。
    """
    try:
        root = root.resolve(strict=True)
        manifest = Manifest.model_validate(yaml.load((root / "master.yaml").read_text(encoding="utf-8"), Loader=UniqueKeyLoader))
        if set(manifest.prompts) != {"chat.character"}:
            raise ValueError("首版只支持 chat.character")
        languages = manifest.prompts["chat.character"]
        if len(languages) != 1 or languages[0].language != "zh" or len(languages[0].variants) != 1:
            raise ValueError("首版只支持一个中文默认包")
        variant = languages[0].variants[0]
        if variant.variant != "-" or not variant.name.strip():
            raise ValueError("包名称或默认变体非法")
        files: list[Path] = []
        parts: list[str] = []
        for segment in variant.segments:
            if not segment.content.startswith("@"):
                raise ValueError("segment 必须引用文件")
            path = (root / segment.content[1:]).resolve(strict=True)
            if not path.is_relative_to(root) or path.suffix != ".md" or path in files:
                raise ValueError("文件越界、重复或类型非法")
            content = path.read_text(encoding="utf-8")
            content = re.sub(r"\{\{/\*.*?\*/\}\}", "", content, flags=re.DOTALL).strip()
            if not content or "{{" in content or "}}" in content:
                raise ValueError("内容为空或使用了尚未支持的动态模板")
            files.append(path)
            parts.append(content)
        return PromptBundle(variant.name, "\n\n".join(parts), tuple(files))
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as error:
        raise AgentError("invalid_prompt_bundle", "角色提示词包无法加载，请检查 master.yaml 与引用文件。", 503) from error
