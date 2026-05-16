#!/usr/bin/env python3
"""调试：打印视觉AI实际输出的特征并保存"""
import json, logging, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
logging.basicConfig(level=logging.INFO)

from services.llm_client import LLMClient
from services.prompt_service import PromptService
from workflows.erp_process.agents.vision_agent import VisionAgent

api_key = os.environ.get("DASHSCOPE_API_KEY", "")
llm = LLMClient(api_key=api_key)
prompt = PromptService()
vision = VisionAgent(llm=llm, prompt_service=prompt)

result = vision.analyze("data/drawing_W20126051401.pdf", "W20126051401")

print("\n=== 视觉AI输出 ===")
print(json.dumps(result, ensure_ascii=False, indent=2))

with open("data/last_vision_output.json", "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)
print("\n已保存: data/last_vision_output.json")
