---
name: senlan-erp-automation
description: 森蓝ERP工艺全自动化工作流 — 多零件支持 + 文件名驱动匹配 + 独立浏览器
version: 5.5.2
author: Hermes Agent
metadata:
  hermes:
    tags: [erp, automation, cnc, vision, playwright, feishu, multi-part]
related_skills:
  - workflow-runner
  - openclaw-troubleshooting
  - feishu-bypass-terminal
  - systematic-debugging
  - karpathy-coding-principles
---

# 森蓝ERP自动化 V5.5 — 多零件生产单元全支持

## 相关 Skills（新用户必读）

本项目依赖以下 skills，新用户首次使用时 AI 需加载确认：

| Skill | 用途 | Hermes | OpenClaw |
|-------|------|--------|----------|
| `senlan-erp-automation` | 主技能 — 全流程 | `skill_view()` | 自动 |
| `workflow-runner` | OpenClaw 注册工作流 | 可选 | 必需 |
| `openclaw-troubleshooting` | Gateway 故障排查 | — | 运行前检查 |
| `feishu-bypass-terminal` | 绕过飞书拦截 terminal | API模式必需 | — |
| `systematic-debugging` | 标准排查流程 | 推荐 | 推荐 |
| `karpathy-coding-principles` | AI 编程准则 | 开发代码时 | — |

> OpenClaw 用户：运行前检查 gateway（`openclaw-troubleshooting`），首次运行用 `workflow-runner` 注册工作流。

---

## 🤖 AI 行为准则（严禁违反）

本项目的代码已完整实现完整工作流。AI 执行时必须遵守以下规则：

### 核心原则：遵循已有代码，不自主发挥

1. **通读代码后执行** — Step 3 必须执行，不得跳过。AI 必须先阅读 `scripts/fill_by_vision.py`、`process_reasoning.py`、`playwright_erp.py` 等核心文件，理解现有逻辑后再执行。
2. **不自己编流程** — 项目代码里已经有登录、搜索、读图、推理、填表、保存、CNC编程的完整实现。AI 的职责是**调用现有代码**，不是重新发明一套。
3. **不自由发挥逻辑** — 工序推理用 `process_reasoning.py` 的引擎，不需要 AI 自己写一套排序规则。视觉分析用 `vision_prompt.py` 的提示词。页面操作用 `playwright_erp.py` 的方法。
4. **不篡改参数** — 项目已配置好的默认值（账号472、密码123456、阿里百炼endpoint等）不要自己改。除非用户明确要求。
5. **流程卡点才是问答时机** — 只在以下场景询问用户：
   - 图纸目录不存在或为空
   - API Key 未配置
   - 生产单号在 ERP 搜索不到
   - 报错后同类修复重试 3 次仍未解决
   - CNC 编程交叉审查未通过需要人工确认
   其他一切流程自动化执行，不要问"可以吗""对不对"这类废话。

### 违反后果
- 自由发挥 = 串改已验证的正确流程 → 用户发现后必须回滚重来
- 不必要的询问打断用户 → 降低自动化程度
- 不读代码直接干 → 可能遗漏重要改动

---

## ⚡ 新系统适配 5步工作流（Hermes / OpenClaw 通用）

### Step 1 — 用户配置 API Key
用户提供：
- **阿里百炼 API Key**（视觉分析，qwen3.6-plus）
- **DeepSeek / 大模型 API Key**（工艺推理、CNC编程）

配置方式：写入 `.env` 文件（路径 `~/.hermes/senlan-automation/.env`）

### Step 2 — 用户提供图纸路径
- 用户指定图纸目录，命名约定 `{生产单号}-{零件号}.pdf`
- 单零件可省略零件号：`{生产单号}.pdf`
- 系统自动扫描并列出匹配的生产单号

### Step 3 — AI 通读代码理清流程
执行前先阅读以下核心文件（Hermes 用 `read_file`，OpenClaw 用 skill 加载）：

| 文件 | 作用 |
|------|------|
| `scripts/fill_by_vision.py` | 全流程入口 |
| `services/playwright_erp.py` | ERP页面交互 |
| `workflows/erp_process/process_reasoning.py` | 特征驱动推理引擎 |
| `workflows/erp_process/prompts/vision_prompt.py` | 视觉分析提示词 |
| `services/llm_client.py` | 双 provider 路由 |
| `scripts/run_cnc_pipeline.py` | CNC 编程流水线 |
| `config/dropdown_options.py` | 工序选项映射 |
| `SETUP_GUIDE.md` | 环境配置指引 |
| `MEMORY.md` | 踩坑速查 |

阅读完成后输出**执行计划摘要**给用户确认。

### Step 4 — 执行流程
```bash
cd ~/.hermes/senlan-automation
python3 scripts/fill_by_vision.py \
    --drawings-dir /path/to/drawings \
    --prod-no C03026051501 \
    --account 472
```

### Step 5 — CNC 代码全量返回飞书（必须）

流程完成后，CNC 代码必须**全量返回**到用户飞书私聊，不是只发摘要/通知。

**发送内容**（每项都是完整的，不能省略G代码正文）：
- 生产单号 + 零件号标识
- 工序名称：**数控精车**（TAKISAWA NEX-108）
  - G代码正文（Markdown 代码块，完整可复制上机）
  - 刀具/转速/进给参数说明
- 工序名称：**镜面放电**（SODICK AD32LS）
  - G代码正文（Markdown 代码块，完整可复制上机）
  - 电参数/电极说明
- 质量报告摘要（自审通过/交叉审查 verdict）

**实现方式**：
- 运行完 `fill_by_vision.py` 后，读取 `data/cnc_pipeline_result.json`
- 用飞书 API 发送两段完整 G代码（`POST /open-apis/im/v1/messages`，msg_type=text）
- 不要只发文件路径或 JSON 摘要，用户要的是**直接能看的 G 代码**

## 双执行环境

| 环境 | 特点 | 适用场景 |
|------|------|---------|
| **Hermes** | 当前会话 terminal 跑，实时输出 | 首次执行、调试、修正 |
| **OpenClaw** | workflow-runner 注册，可定时/按需 | 生产环境、批量运行 |

两个 Agent 通过 `~/.hermes/shared-memory.md` 共享上下文状态、决策和钥匙信息。

---

> **铁律：每一道工序必须来自图纸分析结果。禁止使用固定模板/默认值/占位数据。禁止胡编乱造。特征不足时报错而不是瞎编。**

## 项目位置
`~/.hermes/senlan-automation/`

## 模型配置

| 用途 | 模型 | API | 环境变量 |
|------|------|-----|---------|
| 视觉分析 | **qwen3.6-plus** (阿里百炼) | DashScope | `DASHSCOPE_API_KEY` |
| 文本生成 | **deepseek-v4-pro** | DeepSeek | `DEEPSEEK_API_KEY` |

## 一键运行

```bash
cd ~/.hermes/senlan-automation

# 多零件模式：扫目录自动匹配
python3 scripts/fill_by_vision.py --drawings-dir /Volumes/m2/erp/ --account 472

# 单张图纸（旧版兼容）
python3 scripts/fill_by_vision.py --drawing /path/to/pdf --prod-no W20126051401 --account 472
```

## 多零件核心设计

### 文件名约定
`{生产单号}-{零件号}.pdf`，用第一个 `-` 切分

| 文件名 | 生产单号 | 零件号 |
|--------|---------|--------|
| `C03026051501-001.pdf` | C03026051501 | 001 |
| `C03026051501-A1.pdf` | C03026051501 | A1 |
| `W20126051401.pdf` | W20126051401 | None |
| `W20126051401-001.pdf` | W20126051401 | 001 |

零件号无格式限制，从文件名动态解析。

### 流程

1. 扫描图纸目录 → `{prod_no: {part_no: pdf_path}}`
2. 批量视觉分析 + 推理（不依赖浏览器）
3. 对每个 `(prod_no, part_no)` 对：
   a. 新开浏览器 → 登录 → 导航到计划工艺
   b. 遍历标签页（未发送→BOM清单→已发送），搜索匹配行
   c. 选中 → 开弹窗 → 填工序 → 保存 → 关浏览器

### 为什么独立浏览器

保存工艺后页面残留 `el-dialog__wrapper` 遮罩层拦截鼠标事件。Playwright 的 `.click()` 被遮罩拦截。即使 JS `remove()` 移除 DOM，稳定性检测仍被拦截。
→ **每个零件保存后关闭整个浏览器**，下个零件重新开（persistent_context 保持登录态）。

### 行定位

```javascript
// 动态查"零件号"列索引
const headers = document.querySelectorAll('.vxe-header--row .vxe-cell--title');
let partCol = -1;
Array.from(headers).forEach((h, i) => {
    if (h.textContent.trim() === '零件号') partCol = i;
});
// 双条件匹配
for (let row of document.querySelectorAll('.vxe-body--row')) {
    let cells = row.querySelectorAll('td .vxe-cell');
    let prodCell = cells[2]?.textContent.trim();
    let partCell = cells[partCol]?.textContent.trim();
    if (prodCell === prodNo && partCell === partNo) { /* 找到 */ }
}
```

## 设计演进（完整决策树，避免重复踩坑）

| 版本 | 方案 | 问题 | 皇帝纠正 |
|------|------|------|---------|
| V1 | 硬编码 001/002 后缀，写死 `--prod-no` | "新图纸不叫 001" | 零件号从文件名动态提取 |
| V2 | 从文件名动态提取 prod_no 和 part_no | "生产单号也要从文件名自动提取" | 用 `-` 切分提取两段 |
| V3 | 文件名决定单/多零件模式 | 带后缀可能是单零件 | 单/多由ERP行数决定 |
| V4 | ERP行数决定模式+图纸完整性校验 | 多零件可能在不同标签页 | "匹配不上就跳过?"→缺图必须报错终止 |
| V5 | 文件名驱动逐对搜索所有标签页 | 弹窗遮罩拦截下一零件操作 | "完成时关闭浏览器重新执行" |

## 工序排序规则

```
粗加工(车床/铣床) [10]
↓
热处理 [20] ← 分水岭
↓
打孔 [25] ← 修正：必须在热处理后（淬硬材料）
↓
磨削 [30-34]
↓
精加工(数控精车/CNC精锣) [40-41]
↓
慢走丝/EDM [50-56]
↓
雕刻 [60]
↓
抛光 [70]
↓
出货全检 [80]
↓
表面处理 [90]
↓
生产入库 [100]
```

## 通用模式：Playwright + Vue/Element UI 弹窗遮罩层

这是 **Playwright + Vue/Element UI 应用** 的通用问题，不限于本 ERP：

1. **症状**：`Locator.click()` 超时 30s，日志显示 `<div class="el-dialog__header">` 子树的 `<div class="el-dialog__wrapper">` intercepts pointer events
2. **原因**：Element UI 的 `el-dialog` 关闭后，`el-dialog__wrapper` DOM 节点仍残留。Playwright 的点击稳定性检查检测到该元素覆盖在目标按钮上方，无限重试。
3. **三种解决策略**（按可靠性排序）：
   - **策略 A（最可靠）**：关闭整个 browser context，重新打开新的 persistent_context。代价 ~5 秒重建。推荐用于自动化流水线。
   - **策略 B（有时有效）**：`page.evaluate()` 执行 JS `document.querySelectorAll('.el-dialog__wrapper, .v-modal, .el-overlay').forEach(d => d.remove())`。清除残留 DOM。
   - **策略 C（应急）**：用 `page.evaluate()` 直接 JS 触发 click 替代 Playwright Locator.click()。适用于不需要 Playwright 原生等待的场景（如点击查询按钮）。
4. **可靠判断**：如果策略 B/C 仍失败，立即切换策略 A。不要在失败策略上循环。

## 通用模式：AI 视觉输出类型安全

阿里百炼/DeepSeek 视觉分析返回的字段可能是任意类型，不能假设为 int/str：

```python
# qty 安全转换
qty_raw = part_info.get("qty", 1)
if isinstance(qty_raw, str):
    try: qty = int(qty_raw)
    except: qty = 1
else:
    qty = int(qty_raw) if qty_raw else 1

# roughness 安全拼接（可能是 float/int）
sorted(str(r) for r in roughness_set)   # 不是 sorted(roughness_set)

# 打孔优先级修正
PROCESS_PRIORITY["打孔"] = 25  # 放热处理之后
```

## process_reasoning.py 类型安全（必加）

视觉AI返回的数据类型不可靠，以下位置必须加类型转换：

### qty 安全
```python
qty_raw = part_info.get("qty", 1)
if isinstance(qty_raw, str):
    try: qty = int(qty_raw)
    except: qty = 1
else:
    qty = int(qty_raw) if qty_raw else 1
```

### roughness 安全（多处）
```python
sorted(str(r) for r in roughness_set)   # 不是 sorted(roughness_set)
sorted(str(r) for r in rough_vals)      # 不是 sorted(rough_vals)
```

### 打孔优先级修正
`PROCESS_PRIORITY["打孔"]` 从 15 → 25（放热处理之后，淬硬材料钻孔需硬质合金）

## 工艺要求改进（2026-05-16）

每个工序的 remark 和 task 包含：
- 材料+硬度
- 外形具体尺寸+公差
- 斜面/倒角/R角具体规格+粗糙度
- 割修次数（粗糙度Ra≤0.4→割1修3, Ra≤1.0→割1修2, 其他→割1修1）
- 淬硬后钻孔提示
- 加工参数建议

## 通用模式：VXE 表格按多列匹配行

VXE 表格中按多列条件匹配特定行，不依赖某一列在固定索引位置：

```python
# 1. 读表头
headers = page.evaluate('''
    Array.from(document.querySelectorAll('.vxe-header--row .vxe-cell--title'))
        .map(h => h.textContent.trim())
''')
part_col = headers.index("零件号")  # 动态查找列位置

# 2. 逐行匹配 BOTH 条件
rows_data = page.evaluate(f'''
    () => {{
        const rows = document.querySelectorAll('.vxe-body--row');
        const headers = document.querySelectorAll('.vxe-header--row .vxe-cell--title');
        const hdrText = Array.from(headers).map(h => h.textContent.trim());
        const partCol = hdrText.indexOf('零件号');
        const results = [];
        for(let i = 0; i < rows.length; i++) {{
            const cells = rows[i].querySelectorAll('td .vxe-cell');
            const prodCell = (cells[2]?.textContent||'').trim();
            if(prodCell !== '{prod_no}') continue;
            const partCell = partCol >= 0 ? (cells[partCol]?.textContent||'').trim() : '';
            results.push({{ri: i, partNo: partCell}});
        }}
        return JSON.stringify(results);
    }}
''')
```

## 飞书通知（脚本自包含）

脚本末尾调用飞书 API，不依赖第三方 SDK：
```python
# 1. 获取 token
POST https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal
# 2. 发消息
POST https://open.feishu.cn/open-apis/im/v1/messages
   receive_id=ou_xxxx, msg_type=text, content=JSON
```

## CNCCNCCNC CNC Pipeline — Critical Rules（2026-05-16 纠正的重大问题）

### 🚨 历史教训：硬编码假数据陷阱

`run_cnc_pipeline.py` 原本有硬编码 `PART_INFO`（STRIPPER RING/S-7）和 `FEATURES`，每次运行都生成无关零件的G代码。
**这是严重错误** — CNC 代码必须严格基于图纸视觉分析的结果。

**修复方案**：
1. `fill_by_vision.py` 新增 `_save_analysis_cache()` — 每张图纸分析后持久化 `part_info`/`features`/`special_reqs` 到 `data/analysis_cache_{prod_no}.json`
2. `run_cnc_pipeline.py` 去掉硬编码，改为接收 `--prod-no`（从缓存加载）或 `--part-info-json`/`--features-json`（直接传参）
3. 所有 CNC 提示词模板添加铁律：**只加工特征列表中明确列出的特征，没有的特征不准自己编**

### 正确运行方式

```bash
# 1. 先跑 ERP 流程（生成分析缓存）
python3 scripts/fill_by_vision.py --drawings-dir /path --prod-no XXX --account 472

# 2. 再跑 CNC 流水线（从缓存读取真实图纸数据）
python3 scripts/run_cnc_pipeline.py --prod-no XXX

# 或者不经过缓存，直接传真实数据
python3 scripts/run_cnc_pipeline.py \
    --prod-no XXX --part-no 001 \
    --part-info-json '{"name":"前模镶件","material":"STAVAX ESR",...}' \
    --features-json '[...]'
```

### CNC 代码 → 飞书发送

脚本内置的 `_send_feishu_notification()` 可能返回 400（凭据或格式问题）。
**推荐用 Hermes 的 `send_message` 工具发送 CNC 代码到飞书 DM**：

```
target = "feishu:oc_98be2905a0e66f1d96b31dda7acb40b9"  # 用户私聊
message = "包含完整 G 代码 Markdown 代码块的消息"
send_message(target=target, message=message)
```

### 铁律 — 提示词模板层面

以下模板全部添加了"禁止虚构特征"约束：

| 模板文件 | 约束内容 |
|----------|---------|
| `templates/prompts/cnc/system.j2` | 铁律 #0: "严禁无参考乱编造"，TBD标记法 |
| `templates/prompts/cnc/turning.j2` | "只加工下面明确列出的特征" |
| `templates/prompts/cnc/edm.j2` | "只加工下面明确列出的特征" |
| `templates/prompts/cnc/self_review.j2` | 检查项 #0: "不虚构特征" |
| `templates/prompts/review/cross_check.j2` | "虚构特征→revision_needed" |

### 自审+交叉审查双重防线

生成 CNC 代码后经过两道审查：
1. **自审（self_review）**：LLM 自我检查代码、特征真实性、语法安全性
2. **交叉审查（cross_review）**：识图结果 vs CNC 代码对照检查，特征覆盖度、虚构特征检测
3. 任何一道审查不通过 → 标记为 `revision_needed` 或 `fail`，用户确认后才发飞书

视觉分析每次调用约 3 分钟（API 延迟）。浏览器操作约 10-15 秒/零件。
10 零件 ≈ 32 分钟。

## 红线

- ❌ 禁止固定模板/占位数据
- ❌ 禁止无图纸塞工序
- ❌ 禁止操作非目标生产单
- ❌ 禁止 git push 未经允许
- ❌ 禁止零件号硬编码（必须从文件名动态提取）
- ❌ **禁止 CNC 代码无参考瞎编** — CNC 编程必须基于图纸视觉分析得出的特征数据+实际设备参数。LLM 不能自己发明特征来凑 G 代码。`run_cnc_pipeline.py` 必须接收真实的 `part_info`、`features`、`special_reqs`，禁止硬编码假数据

## 踩坑速查

| 坑 | 解决 |
|----|------|
| VXE insert/remove 不生效 | 用 `vm.getData()` 直接改字段 |
| 弹窗遮罩拦截点击 | 每个零件独立开浏览器 |
| 零件跨标签(001在未发送/002在已发送) | 逐零件遍历全部3个标签 |
| `qty` 为字符串(如"5+5"或"模糊:未标注") | `try: int(qty) except: 1` |
| `roughness` 为float/int(如0.63) | `str(r)` 转换后 join |
| 打孔在热处理前 | 优先级从 15→25 移到热处理后 |
| _generate_remark() 报 TypeError | roughness_set/rough_vals 加 `str(r)` |
| CNC审查过严 | 已降标 5 项宽松检查 |
| 搜索不到订单 | 遍历未发送→BOM清单→已发送 |
