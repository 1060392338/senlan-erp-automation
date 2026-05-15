"""PromptService — 统一提示词渲染服务

所有子Agent通过此服务加载和渲染 Jinja2 提示词模板。
模板路径: templates/prompts/{agent_name}/{template_name}.j2
"""

import logging
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, TemplateNotFound

log = logging.getLogger("prompt_service")


class PromptService:
    """统一提示词渲染入口"""

    def __init__(self, prompt_dir: str = "templates/prompts"):
        self._dir = Path(prompt_dir)
        self._env = Environment(
            loader=FileSystemLoader(str(self._dir)),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, path: str, **kwargs) -> str:
        """渲染指定模板

        Args:
            path: 模板路径相对于 prompts/ 目录，如 "vision/analyze.j2"
            **kwargs: 模板变量

        Returns:
            渲染后的文本
        """
        try:
            template = self._env.get_template(path)
            return template.render(**kwargs)
        except TemplateNotFound:
            log.warning(f"模板不存在: {path}")
            return ""
        except Exception as e:
            log.warning(f"模板渲染失败 {path}: {e}")
            return ""

    def render_messages(
        self, agent: str, template_name: str = "analyze", **kwargs
    ) -> list[dict]:
        """渲染完整的 OpenAI messages 列表（system + user）

        Args:
            agent: Agent 名称（子目录名），如 "vision"
            template_name: 模板名（不含 .j2），默认 "analyze"
            **kwargs: 模板变量

        Returns:
            [{"role": "system", "content": "..."},
             {"role": "user", "content": "..."}]
        """
        messages = []

        # System prompt
        system = self.render(f"{agent}/system.j2", **kwargs)
        if system:
            messages.append({"role": "system", "content": system})

        # User prompt
        user = self.render(f"{agent}/{template_name}.j2", **kwargs)
        if user:
            messages.append({"role": "user", "content": user})

        return messages

    def render_vision_messages(
        self, image_url: str, **kwargs
    ) -> list[dict]:
        """渲染视觉分析 messages（含图片）

        Args:
            image_url: 图片 URL 或本地路径
            **kwargs: 模板变量

        Returns:
            [{"role": "system", ...},
             {"role": "user", "content": [{"type":"text"}, {"type":"image_url"}]}]
        """
        messages = []

        system = self.render("vision/system.j2", **kwargs)
        if system:
            messages.append({"role": "system", "content": system})

        # 渲染 few_shot
        few_shot = self.render("vision/few_shot.j2", **kwargs)

        # 渲染 analyze 模板
        user_text = self.render("vision/analyze.j2", few_shot=few_shot, **kwargs)

        if user_text:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            })

        return messages
