# 森蓝ERP自动化 — 新机器配置指引 V6

## 目录

1. [环境要求](#1-环境要求)
2. [拉取项目](#2-拉取项目)
3. [安装依赖](#3-安装依赖)
4. [配置 API Key](#4-配置-api-key)
5. [启动 Chrome](#5-启动-chrome)
6. [快速验证](#6-快速验证)
7. [首次运行全流程](#7-首次运行全流程)
8. [常见问题](#8-常见问题)

---

## 1. 环境要求

| 组件 | 要求 |
|------|------|
| Python | ≥ 3.9 |
| Chrome | 已安装（本地版，非 Chromium） |
| 操作系统 | macOS（Linux/Windows 理论兼容，未测试） |
| API | 阿里百炼(视觉) + DeepSeek(文本) |
| Git | 有 GitHub 仓库访问权限 |

## 2. 拉取项目

```bash
cd ~/.hermes
git clone https://github.com/1060392338/senlan-erp-automation.git
cd senlan-automation
```

## 3. 安装依赖

```bash
# 核心依赖
pip install playwright openai python-dotenv Pillow PyMuPDF

# 大陆网络慢时用清华镜像：
pip install -i https://pypi.tuna.tsinghua.edu.cn/simple playwright openai python-dotenv Pillow PyMuPDF

# 安装 Playwright 浏览器
playwright install chromium
```

**PyMuPDF** 约 22MB，用于 PDF→PNG。安装失败会自动降级到其他策略（sips/macOS内置、ImageMagick）。

## 4. 配置 API Key

在项目根目录创建 `.env`：

```bash
# 阿里百炼（视觉分析，从 https://bailian.console.aliyun.com/ 获取）
DASHSCOPE_API_KEY=sk-xxxx

# DeepSeek（文本生成/CNC编程，从 https://platform.deepseek.com/ 获取）
DEEPSEEK_API_KEY=sk-xxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1

# ERP账号密码
ERP_472_PASSWORD=123456
# 多账号: ERP_473_PASSWORD=xxx
```

**.env 是敏感文件，不要提交到 Git**（已在 `.gitignore` 中排除）。

## 5. 启动 Chrome

CNC 编程流水线（`run_cnc_pipeline.py`）不需要浏览器。
但 ERP 流程（`fill_by_vision.py`）需要带 CDP 端口的 Chrome。

```bash
# 启动 Chrome 持久化实例（端口 9222）
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    --remote-debugging-port=9222 \
    --remote-allow-origins=* \
    --user-data-dir="$HOME/.hermes/senlan-automation/data/chrome_data/playwright" \
    --disable-extensions \
    --window-size=1920,1080 &
```

首次启动需要手动登录 ERP（http://112.74.35.30），账号 472 / 密码 123456。
登录成功后浏览器保持打开，后续自动化复用登录态。

> **注意**: `--remote-debugging-port=9222` 和 `--remote-allow-origins=*` 必须同时带，否则 CDP WebSocket 返回 403。

## 6. 快速验证

```bash
cd ~/.hermes/senlan-automation

# 检查环境
python3 -c "import playwright; print('playwright OK')"
python3 -c "import fitz; print('PyMuPDF OK')"
python3 -c "from dotenv import load_dotenv; print('dotenv OK')"

# 检查 API key
cat .env | grep -E "DASHSCOPE|DEEPSEEK"

# 检查 Chrome 端口
curl -s http://localhost:9222/json/version | python3 -c "import sys,json; print(json.load(sys.stdin).get('Browser','❌ Chrome not running'))"

# 跑单元测试（< 1min）
python3 -m pytest tests/ -v -k "not test_fill" --tb=short
```

期望输出：
- playwright OK ✅
- PyMuPDF OK ✅ 
- dotenv OK ✅
- API key 有值 ✅
- Chrome 端口返回浏览器版本信息 ✅
- 117 passed ✅

## 7. 首次运行全流程

### 7.1 准备图纸

图纸 PDF 放到任意目录，文件名格式：
```
{生产单号}-{零件号}.pdf
示例:
  C03026051501-001.pdf
  C03026051501-002.pdf
  W20126051401.pdf        (无零件号)
```

### 7.2 全自动流程（一条命令）

```bash
cd ~/.hermes/senlan-automation

# 扫描图纸目录 → 视觉分析 → 推理 → 填ERP → CNC编程
python3 scripts/fill_by_vision.py \
    --drawings-dir /path/to/drawings \
    --prod-no C03026051501 \
    --account 472
```

自动完成：
1. 扫描目录 → 文件名提取 `(prod_no, part_no)` 对
2. 视觉分析（阿里百炼 qwen3.6-plus，每张 ~3min）
3. 特征推理 → 确定工序顺序+参数
4. Playwright ERP → 搜索行 → 弹窗填充 → 保存
5. CNC 编程流水线（精车+放电并行编程 → 自审 → 交叉审查）
6. 保存结果到 `data/cnc_{prod_no}-{part_no}.json`

### 7.3 单独跑 CNC 编程

如果已有分析缓存（`data/analysis_cache_{prod_no}.json`），可单独重跑 CNC：

```bash
python3 scripts/run_cnc_pipeline.py --prod-no C03026051501
```

### 7.4 完整流程图

```
图纸PDF → 文件名解析(prod_no, part_no)
  → 批量视觉分析(qwen3.6-plus)
  → 特征驱动推理(5层模型)
  → ERP浏览器操作(填计划工艺)
  → CNC编程流水线:
      精车 ──┐ 并行
      放电 ──┘  → 自审 → 交叉审查
  → 保存 data/cnc_{prod_no}-{part_no}.json
```

## 8. 常见问题

### Q: Chrome 连不上 CDP 端口？
A: 检查启动命令是否带了 `--remote-debugging-port=9222 --remote-allow-origins=*`。两个 flag 缺一不可。用 `curl http://localhost:9222/json/version` 测试。

### Q: ERP 登录失败？
A: 首次登录需要短信验证码。Chrome 持久化登录态后，下次自动复用。密码在 `.env` 文件 `ERP_{account}_PASSWORD`。

### Q: 视觉分析一直卡住？
A: qwen3.6-plus 正常延迟约 2-3 分钟/张。超过 5 分钟检查 `DASHSCOPE_API_KEY` 是否有效。

### Q: 找不到生产单？
A: 脚本自动遍历三个标签页：未发送 → BOM清单 → 已发送。新同步的单通常在「未发送」。

### Q: CNC 编程卡在 LLM 调用？
A: DeepSeek API 响应慢是正常的（精车 ~110s，放电 ~140s）。精车+放电并行等 LLM，总约 2-3 分钟。用 `notify_on_complete` 后台模式运行，避免 terminal timeout。

### Q: 如何重装/重置？
A: 删除 `data/chrome_data/playwright/` 目录清空登录态，重新启动 Chrome 登录。

---

> 最后更新: 2026-05-16
> 版本: V6
