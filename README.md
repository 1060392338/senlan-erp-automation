# 🏭 森蓝精密 · ERP 工艺自动化系统

> 销售订单 → AI读2D图纸 → 五层工艺推理 → CNC代码生成 → ERP回填全部工序

**⚠️ 当前状态：项目已全面从 DrissionPage 迁移到 Playwright。**
已删除24个旧脚本，重写了核心服务层。详见 `HANDOFF_TO_CLAUDE.md`。

## 快速开始

```bash
# 1. 安装依赖
pip install playwright && playwright install chromium

# 2. 配置已在 .env 中（API Key + ERP密码）

# 3. 运行完整流程（推荐）
python3 scripts/fill_by_vision.py --prod-no W01626051501

# 4. 运行工作流
python main.py --bot bot_a --tenant senlan_472 --agent erp_process_agent \
  --input '{"prod_no":"W01626051501","customer":"客户X"}'

# 5. 查看可选租户和工作流
python main.py --list
```

## 入口脚本

```bash
# Playwright 完整流程（登录→导航→搜索→弹窗→填工序→保存）
python3 scripts/fill_by_vision.py --prod-no W01626051501

# 带图纸路径（启用阿里百炼视觉分析）
python3 scripts/fill_by_vision.py --drawing /path/to/图纸.jpg --prod-no W01626051501
```

## 架构

```
senlan-automation/
├── config/
│   ├── __init__.py
│   └── dropdown_options.py     ← ERP工序选项统一配置（49选项+映射）
├── scripts/
│   └── fill_by_vision.py       ← Playwright主入口
├── services/
│   ├── browser_service.py      ← Playwright浏览器工厂（含DrissionPage兼容层）
│   ├── playwright_erp.py       ← Playwright ERP交互封装
│   ├── llm_client.py           ← DashScope LLM网关
│   └── ...
├── workflows/erp_process/
│   ├── process_reasoning.py    ← 五层工艺推理引擎
│   ├── _login.py               ← Playwright登录逻辑
│   ├── nodes/
│   │   ├── process_filler.py   ← 填计划工艺
│   │   ├── routing_filler.py   ← [废弃] CNC代码通过飞书机器人返回
│   │   └── ...
│   ├── agents/
│   │   ├── vision_agent.py     ← 阿里百炼视觉分析
│   │   ├── cnc_agent.py        ← CNC编程
│   │   └── ...
├── .env                        ← 已配置真实凭据
├── HANDOFF_TO_CLAUDE.md        ← 项目交接文档
└── ARCHITECTURE.md             ← 架构约束
```

## 五层工艺推理引擎

`workflows/erp_process/process_reasoning.py`

| 层级 | 名称 | 实现 |
|:----:|------|------|
| L1 | 零件类型+材料 | 视觉读标题栏 → 方形/圆形决策 |
| L2 | 几何特征提取 | Qwen-VL + OCR → 孔/槽/螺纹/粗糙度 |
| L3 | 工序排序逻辑 | 5原则规则引擎（先粗后精/热处理分水岭/基准先行/慢丝在精铣后/表面处理最后） |
| L4 | 切削参数 | 材料+硬度→经验值→填入remark |
| L5 | 特殊要求 | Sharp edge/TiN/刻字→注意事项插入 |

**形状→工艺路线规则**：
- 方形→铣→磨→放电（15道工序）
- 圆形→车→磨→放电（8道工序）

**工序名到ERP下拉选项的映射**见 `process_reasoning.py:map_to_erp_processes()`

## ✅ 当前状态

VXE工序下拉选择 ✅ 已解决（直接操作VXE数据对象 `vm.getData()` 设置 `table_type`/`table_name` 绕过DOM下拉）。下一步：集成阿里百炼视觉分析 + LangGraph工作流端到端。

## 技术栈

| 组件 | 选型 |
|------|------|
| 浏览器 | **Playwright** (替代旧DrissionPage) |
| LLM | DashScope Qwen-Max / Qwen-VL |
| 视觉模型 | 阿里百炼 qwen3.6-plus |
| CNC模板 | Jinja2 |
| 通知 | 飞书 Webhook / API |
| 配置 | YAML + .env |
| Python | 3.9+ |
