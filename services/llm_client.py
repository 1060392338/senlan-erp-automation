"""
LLMClient — 统一的 LLM 网关

封装 DashScope 千问 API，统一处理：
- 503 重试（指数退避 + 抖动）
- 限流排队
- 成本统计（预留）

支持任意模型：qwen-max / qwen-vl-max / deepseek-chat
"""

import json
import os
import random
import time
from typing import Any, Optional
from openai import OpenAI


class LLMClient:
    def __init__(
        self,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        api_key: str = None,
        default_model: str = "deepseek-v4-pro",
        max_retries: int = 6,
        vision_model: str = "qwen-vl-max",
        deepseek_base_url: str = None,
        deepseek_api_key: str = None,
    ):
        self._base_url = base_url
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self.vision_model = vision_model
        # DeepSeek 独立配置
        self._deepseek_base_url = deepseek_base_url or os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
        )
        self._deepseek_api_key = deepseek_api_key or os.environ.get(
            "DEEPSEEK_API_KEY", api_key
        )
        self._client: Optional[OpenAI] = None
        self._deepseek_client: Optional[OpenAI] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(base_url=self._base_url, api_key=self._api_key)
        return self._client

    @property
    def deepseek_client(self) -> OpenAI:
        """DeepSeek API 客户端（用于 deepseek-* 系列模型）"""
        if self._deepseek_client is None:
            self._deepseek_client = OpenAI(
                base_url=self._deepseek_base_url,
                api_key=self._deepseek_api_key,
            )
        return self._deepseek_client

    def _get_client(self, model: str) -> OpenAI:
        """根据模型名自动选择客户端"""
        if "deepseek" in (model or "").lower():
            return self.deepseek_client
        return self.client

    def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.3,
        response_format: Optional[dict] = None,
    ) -> str:
        """LLM 调用，自动重试。deepseek模型走独立客户端"""
        model = model or self._default_model
        active_client = self._get_client(model)
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
                resp = active_client.chat.completions.create(**kwargs)
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
        """视觉分析（兼容旧接口）"""
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

    @staticmethod
    def _make_image_url(path_or_url: str) -> str:
        """将本地文件或 URL 转为 API 可用的 image_url

        支持：本地图片（PNG/JPEG/BMP/TIFF）、PDF（自动转PNG）、
              http/https URL、已有 data: URL

        PDF 转 PNG 策略（按优先级，自动回退）：
        1. PyMuPDF (fitz) — 纯Python，跨平台，零外部依赖
        2. pdf2image — 需要 poppler，跨平台
        3. sips — macOS 内置
        4. magick/convert — ImageMagick，跨平台
        """
        import base64, mimetypes, os, logging, subprocess, tempfile

        log = logging.getLogger("llm_client._make_image_url")

        # 已经是 URL 或 data URI
        if path_or_url.startswith(("http://", "https://", "data:")):
            return path_or_url

        path = os.path.abspath(path_or_url)
        if not os.path.exists(path):
            raise FileNotFoundError(f"图纸文件不存在: {path}")

        ext = os.path.splitext(path)[1].lower()

        # ── PDF 转 PNG ──
        if ext == ".pdf":
            png_data = LLMClient._pdf_to_png(path)
            if png_data:
                b64 = base64.b64encode(png_data).decode("ascii")
                return f"data:image/png;base64,{b64}"
            log.warning("所有PDF转PNG策略均失败，使用降级数据")
            raise RuntimeError("PDF 转 PNG 失败，无法进行视觉分析")

        # ── 图片文件 ──
        with open(path, "rb") as f:
            raw = f.read()
        mime_map = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".bmp": "image/bmp", ".tiff": "image/tiff", ".tif": "image/tiff",
        }
        mime = mime_map.get(ext) or mimetypes.guess_type(path)[0] or "application/octet-stream"
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def _pdf_to_png(pdf_path: str):
        """PDF 转 PNG 字节数据，多策略回退"""
        import logging, subprocess, tempfile, os
        log = logging.getLogger("llm_client._pdf_to_png")

        # 策略1: PyMuPDF (fitz) — 最快，跨平台，零依赖
        try:
            import fitz
            log.info("  [策略1] 使用 PyMuPDF...")
            doc = fitz.open(pdf_path)
            page = doc[0]
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            doc.close()
            log.info(f"  PyMuPDF 完成: {len(img_bytes)} bytes")
            return img_bytes
        except ImportError:
            log.info("  PyMuPDF 未安装")
        except Exception as e:
            log.warning(f"  PyMuPDF 失败: {e}")

        # 策略2: pdf2image — 需要 poppler
        try:
            from pdf2image import convert_from_path
            log.info("  [策略2] 使用 pdf2image...")
            # 先试试能不能找到 poppler
            import subprocess as sp
            has_poppler = sp.run(["pdftoppm", "-v"],
                                 capture_output=True, timeout=5).returncode == 0
            if has_poppler:
                images = convert_from_path(pdf_path, dpi=200,
                                            first_page=1, last_page=1)
                if images:
                    import io
                    buf = io.BytesIO()
                    images[0].save(buf, format="PNG")
                    log.info(f"  pdf2image 完成: {buf.tell()} bytes")
                    return buf.getvalue()
            else:
                log.info("  poppler 未安装")
        except ImportError:
            log.info("  pdf2image 未安装")
        except Exception as e:
            log.warning(f"  pdf2image 失败: {e}")

        # 策略3: sips (macOS 内置)
        try:
            log.info("  [策略3] 使用 sips (macOS)...")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                r = subprocess.run(
                    ["sips", "-s", "format", "png", "--resampleWidth", "2000",
                     pdf_path, "--out", tmp_path],
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode == 0:
                    with open(tmp_path, "rb") as f:
                        data = f.read()
                    log.info(f"  sips 完成: {len(data)} bytes")
                    return data
                log.warning(f"  sips 返回非零: {r.stderr}")
            except FileNotFoundError:
                log.info("  sips 命令不存在（非 macOS）")
            except Exception as e:
                log.warning(f"  sips 失败: {e}")
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            log.warning(f"  sips 策略异常: {e}")

        # 策略4: ImageMagick convert
        try:
            log.info("  [策略4] 使用 ImageMagick convert...")
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                r = subprocess.run(
                    ["convert", "-density", "200", "-quality", "90",
                     pdf_path + "[0]", tmp_path],
                    capture_output=True, text=True, timeout=30,
                )
                if r.returncode == 0:
                    with open(tmp_path, "rb") as f:
                        data = f.read()
                    log.info(f"  ImageMagick 完成: {len(data)} bytes")
                    return data
            except FileNotFoundError:
                log.info("  ImageMagick 未安装")
            except Exception as e:
                log.warning(f"  ImageMagick 失败: {e}")
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        except Exception as e:
            log.warning(f"  ImageMagick 策略异常: {e}")

        return None

    def vision_with_system(
        self,
        image_url: str,
        system_prompt: str,
        user_prompt: str,
        model: str = "qwen-vl-max",
    ) -> str:
        """带 system prompt 的视觉分析

        自动处理本地文件路径 → base64 data URI 编码。
        支持图片（PNG/JPEG/BMP）和 PDF 文件。
        """
        url = self._make_image_url(image_url)
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user_prompt},
                    {"type": "image_url", "image_url": {"url": url}},
                ],
            },
        ]
        return self.chat(messages, model=model)
