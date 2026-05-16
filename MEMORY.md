# 森蓝ERP自动化 — 项目记忆

> **首次读取**: 任何 Agent 启动本项目，先读 `SENLAN-SKILL.md`（完整 Skill 文档）。
> **此文件仅存放 SENLAN-SKILL.md 未覆盖的跨会话上下文。**

---

## 当前状态（2026-05-16）

**版本**: V6 — 并行CNC+模块化重构 ✅
**账号**: 472（默认，`--account` 指定）
**ERP**: http://112.74.35.30
**路径**: `~/.hermes/senlan-automation/`

## 模型

| 用途 | 模型 | API |
|------|------|-----|
| 视觉分析 | qwen3.6-plus (阿里百炼) | DashScope |
| 文本生成/CNC | deepseek-v4-pro | DeepSeek |

## 跨 Agent 共享上下文

machemes 和 maccloude 通过飞书群（`oc_69882b0f58f95c75de82a97e4decabd7`）同步上下文。
machemes 启动时扫群最近 20 条消息接上 maccloude 的思考过程。

## Git 红线

**没有陛下明确允许，不可以私自 git push。** push 前必须先问。

## 已知问题（待修复）

1. **飞书通知 400 错误** — `_send_feishu_notification()` 返回 HTTP 400。暂不管。
2. **LangChain 弃用警告** — `langchain.retrievers` → `langchain_community.retrievers` 等 6 处。
3. **`test_fill` 超时** — 需要浏览器环境，CI 跳过。
