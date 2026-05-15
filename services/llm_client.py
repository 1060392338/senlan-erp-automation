"""
LLMClient — 统一的 LLM 网关

封装 DashScope 千问 API，统一处理：
- 503 重试（指数退避 + 抖动）
- 限流排队
- 成本统计（预留）

支持任意模型：qwen-max / qwen-vl-max / deepseek-chat
"""

import json
import random
import time
from typing import Any, Optional
from openai import OpenAI


class LLMClient:
    def __init__(
        self,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key: str = None,
        default_model: str = "qwen-max",
        max_retries: int = 6,
        vision_model: str = "qwen-vl-max",
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self.vision_model = vision_model
        self._client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._client

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        response_format: Optional[dict] = None,
    ) -> str:
        """LLM 调用，自动重试"""
        model = model or self._default_model
        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                kwargs = {
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                }
                if response_format:
                    kwargs["response_format"] = response_format
                resp = self.client.chat.completions.create(**kwargs)
                return resp.choices[0].message.content

            except Exception as e:
                last_error = e
                err_str = str(e)
                if "503" in err_str or "too busy" in err_str.lower():
                    wait = (2**attempt) * random.uniform(0.8, 1.2)
                    time.sleep(wait)
                elif attempt < self._max_retries:
                    time.sleep(2)
                else:
                    raise

        raise last_error  # type: ignore

    def chat_json(self, messages: list[dict], model: Optional[str] = None) -> dict:
        """返回 JSON 格式响应"""
        text = self.chat(messages, model=model, response_format={"type": "json_object"})
        return json.loads(text)

    def vision(
        self, image_url: str, prompt: str, model: str = "qwen-vl-max"
    ) -> str:
        """视觉分析"""
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ]
        return self.chat(messages, model=model)
