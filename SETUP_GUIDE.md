# 森蓝ERP工艺自动化工作流 — 迁移配置指引

## 目录

1. [环境要求](#1-环境要求)
2. [依赖安装](#2-依赖安装)
3. [项目结构](#3-项目结构)
4. [文件清单](#4-文件清单)
5. [配置文件](#5-配置文件)
6. [API密钥](#6-api密钥)
7. [快速验证](#7-快速验证)
8. [常见问题](#8-常见问题)

---

## 1. 环境要求

| 组件 | 要求 |
|------|------|
| Python | ≥ 3.9 |
| 浏览器 | Chrome（本地安装） |
| 操作系统 | macOS / Linux / Windows |
| API | 阿里百炼(视觉) + DeepSeek(文本) |

## 2. 依赖安装

```bash
# 核心依赖
pip install playwright openai python-dotenv Pillow PyMuPDF

# 安装 Playwright 浏览器
playwright install chromium
# 或使用已安装的Chroma（channel="chrome"）
```

**注意**: 如果 `pip install` 在大陆网络下慢，可使用镜像：
```bash
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple playwright openai python-dotenv Pillow PyMuPDF
```

**PyMuPDF** 约 22MB，用于 PDF→PNG 转换（策略1，最快）。如果安装失败，脚本会自动降级到其他策略（sips / ImageMagick）。

## 3. 项目结构

```
~/.hermes/senlan-automation/
├── .env                          # API keys + 配置（不提交 Git）
├── MEMORY.md                     # 项目记忆文件（新Agent启动先读）
├── HANDOFF_TO_CLAUDE.md          # 交接文档
├── config/
│   └── dropdown_options.py       # 49个ERP工序选项
├── services/
│   ├── llm_client.py             # LLM网关（视觉+文本+PDF→base64）
│   ├── playwright_erp.py         # Playwright ERP封装
│   ├── browser_service.py        # 浏览器服务
│   └── prompt_service.py         # Jinja2提示词渲染
├── workflows/
│   └── erp_process/
│       ├── process_reasoning.py  # ⭐特征驱动推理引擎
│       ├── agents/
│       │   ├── vision_agent.py   # 视觉分析Agent
│       │   ├── cnc_agent.py      # CNC编程Agent
│       │   ├── review_agent.py   # 自审+交叉审查Agent
│       │   └── supervisor.py     # 监督Agent
│       └── prompts/              # Jinja2提示词模板
├── templates/prompts/
│   └── vision/
│       ├── analyze.j2            # 视觉分析提示词
│       ├── system.j2             # 视觉系统提示词
│       └── few_shot.j2           # 少样本示例
├── scripts/
│   ├── fill_by_vision.py         # ⭐全流程入口（主脚本）
│   ├── run_cnc_pipeline.py       # CNC编程流水线
│   └── cleanup_processes.py      # 清理多余工序行
├── data/
│   ├── chrome_data/playwright/   # Chrome持久化登录态
│   └── drawings/                 # 测试图纸
└── .hermes/plans/                # 历史规划文档
```

## 4. 文件清单

### 核心文件（必须）

| 文件 | 说明 | 修改频率 |
|------|------|---------|
| `scripts/fill_by_vision.py` | 入口脚本，命令行交互，浏览器操作 | 新功能时 |
| `workflows/erp_process/process_reasoning.py` | 特征→工序映射、排序、工时、备注 | 工艺规则调整 |
| `config/dropdown_options.py` | ERP 49道工序选项编码 | ERP新增工序时 |
| `.env` | API Keys | 更换API时 |

### Agent文件

| 文件 | 模型 | 说明 |
|------|------|------|
| `agents/vision_agent.py` | qwen-vl-max | 调用阿里百炼视觉分析图纸 |
| `agents/cnc_agent.py` | deepseek-v4-pro | 生成数控精车/镜面放电G代码 |
| `agents/review_agent.py` | deepseek-v4-pro | 自审+交叉审查CNC代码 |

### 提示词文件

| 文件 | 影响 |
|------|------|
| `templates/prompts/vision/analyze.j2` | 视觉AI提取的特征参数详细程度 |
| `templates/prompts/vision/system.j2` | 视觉AI的识别规则 |
| `templates/prompts/vision/few_shot.j2` | 少样本示例，影响识别质量 |

## 5. 配置文件

### `.env` 文件

在项目根目录创建 `.env`：

```bash
# 阿里百炼（视觉分析）
DASHSCOPE_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# DeepSeek（CNC编程、文本生成）
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# ERP账号密码
ERP_472_PASSWORD=123456
# 如需多账号: ERP_473_PASSWORD=xxx, ERP_474_PASSWORD=xxx
```

### 脚本参数

```bash
python3 scripts/fill_by_vision.py \
    --drawings-dir /Volumes/m2/erp/ \   # 图纸目录
    --prod-no C03026051501 \             # 生产单号（可选过滤）
    --parts 001,002 \                    # 零件号子集（可选过滤）
    --account 472 \                      # ERP账号
    --gen-cnc                            # 生成CNC代码（可选）
```

## 6. API密钥

| 平台 | 用途 | 获取方式 |
|------|------|---------|
| 阿里百炼(DashScope) | 视觉分析 qwen-vl-max | https://bailian.console.aliyun.com/ → API-KEY |
| DeepSeek | 文本生成 deepseek-v4-pro | https://platform.deepseek.com/ → API Keys |

**视觉API计费**: qwen-vl-max ¥1.6/百万输入tokens, ¥4/百万输出tokens。一次分析约 ¥0.03。

## 7. 快速验证

### 最小验证（单零件）

```bash
cd ~/.hermes/senlan-automation

# 检查环境
python3 -c "import playwright; print('playwright OK')"
python3 -c "import fitz; print('PyMuPDF OK')"
python3 -c "from dotenv import load_dotenv; print('dotenv OK')"

# 检查API密钥
cat .env | grep -E "DASHSCOPE|DEEPSEEK"

# 运行单零件流程
python3 scripts/fill_by_vision.py \
    --drawing /Volumes/m2/erp/C03026051501-001.pdf \
    --prod-no C03026051501 \
    --account 472
```

### 完整验证（多零件）

```bash
python3 scripts/fill_by_vision.py \
    --drawings-dir /Volumes/m2/erp/ \
    --prod-no C03026051501 \
    --account 472
```

### 预期输出

```
✅ 全流程完成! 成功 2/2
处理零件:
  C03026051501: {'001': 11道工序, '002': 10道工序}
```

## 8. 常见问题

### Q: 浏览器弹不出来？
A: 脚本使用 `headless=False` 显示Chrome窗口。确认Chrome已安装。如使用远程SSH，需要 `--headless` 模式（需改代码）。

### Q: 视觉分析一直卡住？
A: qwen-vl-max 约 3 分钟/次，这是正常API延迟。如果超过 5 分钟，检查 `DASHSCOPE_API_KEY` 是否有效。

### Q: ERP登录失败？
A: 确认账号密码正确。首次登录可能需要短信验证码。使用 `persistent_context` 可保持登录态。

### Q: 找不到生产单？
A: 遍历三个标签（未发送→BOM清单→已发送）。新同步的订单通常在「未发送」标签。

### Q: 弹窗保存后无法操作？
A: 脚本已设计为每个零件独立开浏览器，保存后关闭再开新的。这是当前稳定的方案。

### Q: 多零件处理零件号不匹配？
A: 确认图纸文件名格式为 `{生产单号}-{零件号}.pdf`。零件号可以是任意字符串（001/A1/M1），从文件名 `-` 后动态提取。

### Q: 如何加速？
A: 视觉分析是唯一瓶颈（~3min/张）。可换用 `qwen-vl-max-lite` 或批量处理。

---

> 最后更新: 2026-05-16
> 版本: V6
