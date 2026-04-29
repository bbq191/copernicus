import logging
from pathlib import Path

import frontmatter

logger = logging.getLogger(__name__)

_FALLBACK_PROMPT = "你是一个会议助手，请根据以下转写文本生成会议纪要。"
_DEFAULT_TEMPLATE_ID = "universal"


class TemplateManager:
    def __init__(self, templates_dir: Path) -> None:
        self._templates_dir = templates_dir
        self._templates: dict[str, dict] = {}
        self._templates = self._scan()
        logger.info("Loaded %d template(s) from %s", len(self._templates), self._templates_dir)

    def _scan(self) -> dict[str, dict]:
        """扫描模板目录，构建并返回新的模板字典，不修改现有 self._templates。"""
        if not self._templates_dir.exists():
            logger.warning("Templates directory not found: %s", self._templates_dir)
            return {}

        result: dict[str, dict] = {}
        for path in self._templates_dir.glob("*.md"):
            try:
                post = frontmatter.load(str(path))
                template_id = post.metadata.get("id", path.stem)
                result[template_id] = {
                    "id": template_id,
                    "name": post.metadata.get("name", path.stem),
                    "description": post.metadata.get("description", ""),
                    "prompt": post.content.strip(),
                }
            except Exception as e:
                logger.error("Failed to load template %s: %s", path.name, e)

        return result

    def reload(self) -> int:
        """重新扫描模板目录，原子替换内存字典。返回加载的模板数量。

        在扫描完成之前 self._templates 保持不变，确保并发请求始终能读到完整的旧数据。
        """
        new_templates = self._scan()
        self._templates = new_templates  # 单次赋值，asyncio 单线程模型下原子可见
        logger.info(
            "Templates reloaded: %d template(s) from %s",
            len(new_templates),
            self._templates_dir,
        )
        return len(new_templates)

    def get_all_metadata(self) -> list[dict]:
        return [
            {"id": v["id"], "name": v["name"], "description": v["description"]}
            for v in self._templates.values()
        ]

    def get_prompt(self, template_id: str) -> str:
        template = self._templates.get(template_id)
        if template is None:
            fallback = self._templates.get(_DEFAULT_TEMPLATE_ID)
            if fallback:
                logger.warning(
                    "Template '%s' not found, falling back to '%s'",
                    template_id,
                    _DEFAULT_TEMPLATE_ID,
                )
                return fallback["prompt"]
            logger.warning(
                "Template '%s' not found and no default available, using minimal prompt",
                template_id,
            )
            return _FALLBACK_PROMPT
        return template["prompt"]
