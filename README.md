# 🏭 森蓝精密 · ERP 工艺自动化系统 V6.2

> AI 读 2D 工程图 → 五层特征驱动推理 → ERP 自动填工序 → CNC 代码并行生成（自审+交叉审查） → 飞书全量返回 G 代码

## 一条命令全自动

```bash
cd ~/.hermes/senlan-automation

# 全流程：扫图纸 → 视觉分析 → 填ERP → 并行CNC编程 → 保存结果
python3 scripts/fill_by_vision.py --drawings-dir /path/to/drawings --account 472

# 指定单号+零件子集
python3 scripts/fill_by_vision.py --drawings-dir /path --prod-no C03026051501 --parts 001,002 --account 472

# 单独重跑 CNC（已有分析缓存时）
python3 scripts/run_cnc_pipeline.py --prod-no C03026051501
```

## 核心流程

```
图纸PDF (目录自动扫描)
  → {生产单号-零件号.pdf} 文件名驱动匹配
  → PyMuPDF 转 PNG (~0.1s)
  → 阿里百炼 qwen3.6-plus 视觉分析 (~3min/张, 第二次从缓存跳过)
  → 特征驱动推理引擎 (922行):
      L1: 零件类型+材料 (圆件/方件/异形)
      L2: 16种几何特征 → 工序映射
      L3: 5原则排序 (热处分水岭/粗前精后/基准先行/慢丝在后/表面最后)
      L4: 工时估算 (尺寸×数量×粗糙度自适应)
      L5: 特殊要求 (刻字/利角/TiN涂层 → 嵌入工序备注)
  → 保存分析缓存 (data/analysis_cache_{prod_no}.json)
  → ERP浏览器操作 (Playwright launch_persistent_context):
      遍历标签页 (未发送→BOM清单→已发送)
      按 生产单号+零件号 双条件匹配行
      开弹窗 → 填全部工序 → 保存 → 关闭浏览器
  → CNC 编程流水线 (并行模式，每零件精车+放电同时调LLM):
      读取分析缓存中真实的 part_info / features
      CNC Agent → G代码生成 → 自审 → 交叉审查
      保存 data/cnc_{prod_no}-{part_no}.json
  → 飞书私聊全量返回 G 代码
```

## 多零件生产单

| 文件命名 | 含义 |
|----------|------|
| `C03026051501-001.pdf` | 生产单 C03026051501, 零件号 001 |
| `C03026051501-002.pdf` | 生产单 C03026051501, 零件号 002 |
| `W20126051401.pdf` | 单零件, 无零件号 |

设计关键：
- 文件名驱动：`(prod_no, part_no)` 用第一个 `-` 切分提取
- 跨 3 标签搜索：未发送 → BOM 清单 → 已发送
- 独立浏览器：每零件保存后关闭，避免弹窗遮罩残留
- 零件号无格式限制：001/002/A1/M1 均可
- 缺图纸报错终止，不跳过

## 项目结构

```
senlan-automation/
├── scripts/
│   ├── fill_by_vision.py          ⭐ 全流程入口 (705行)
│   ├── run_cnc_pipeline.py         CNC 编程流水线
│   └── vision_service.py           VisionService 分析+缓存 (226行)
├── workflows/erp_process/
│   ├── process_reasoning.py        ⭐ 特征驱动推理引擎 (922行)
│   ├── graph.py                    LangGraph 编排 (124行)
│   ├── agents/cnc_agent.py         CNC 编程 Agent
│   ├── nodes/                      图谱节点
│   └── state.py                    状态定义
├── services/
│   ├── playwright_erp.py           Playwright ERP 封装
│   ├── llm_client.py               LLM 网关 (DashScope + DeepSeek 双路由)
│   ├── browser_service.py          浏览器服务 (launch_persistent_context)
│   ├── notification_service.py     飞书通知
│   ├── drawing_registry.py         图纸注册
│   ├── kb_service.py               知识库服务
│   ├── template_service.py         Jinja2 模板引擎
│   ├── prompt_service.py           提示词服务
│   ├── service_container.py        服务容器
│   ├── context.py                  执行上下文
│   ├── tenant_context.py           租户配置
│   └── state_service.py            状态持久化
├── config/
│   └── dropdown_options.py         49个ERP工序选项
├── config.yaml                     账号/工作流配置
├── templates/prompts/
│   ├── vision/                     视觉分析 (analyze/system/few_shot)
│   ├── cnc/                        CNC 编程 (turning/edm/self_review + few_shot)
│   └── review/                     审查 (cross_check/system)
├── data/                           ← 分析缓存/CNC输出/Chrome持久化
├── tests/
│   ├── test_reasoning.py           process_reasoning 单元测试
│   └── services/                   服务层测试
├── .env                            ← API Keys + ERP 密码 (不上传git)
├── SENLAN-SKILL.md                 ← 主 Skill 文档 (全量知识)
├── SETUP_GUIDE.md                  新机器配置指引
├── MEMORY.md                       跨 Agent 速查
└── README.md                       本文件
```

## CNC 编程并行架构

每个零件的数控精车 和 镜面放电 两道工序**并行调用 LLM**（ThreadPoolExecutor）：

```
零件001 ─┬─ 数控精车 LLM (~110s) ── 自审 ──┐
           │                                    │
           └─ 镜面放电 LLM (~200s) ── 自审 ────┤
                                                 ↓
                                           交叉审查 → cnc_001.json
                                                 ↓
零件002 ─┬─ 数控精车 LLM (~110s) ── 自审 ──┐
           │                                    │
           └─ 镜面放电 LLM (~200s) ── 自审 ────┤
                                                 ↓
                                           交叉审查 → cnc_002.json
```

总耗时约 7min（并行），串行需 12min，提速 ~37%。且并行时 LLM 输出更详尽（代码量 ↑2-3x）。

## 模型

| 用途 | 模型 | API | 环境变量 |
|------|------|-----|---------|
| 视觉分析 | qwen3.6-plus (阿里百炼) | DashScope | DASHSCOPE_API_KEY |
| 文本/编程 | deepseek-v4-pro | DeepSeek | DEEPSEEK_API_KEY |
| ERP 登录 | — | — | ERP_{account}_PASSWORD |

## 红线

- ❌ 禁止胡编乱造工序（必须来自图纸分析结果）
- ❌ 禁止使用模板/占位数据/fallback 工艺
- ❌ 禁止操作非目标生产单
- ❌ 禁止 CNC 代码无参考瞎编 — 必须基于真实特征+设备参数
- ❌ 禁止 git push 未经允许
- ❌ 禁止零件号硬编码（必须从文件名动态提取）

## 技术栈

| 组件 | 选型 |
|------|------|
| 浏览器自动化 | Playwright (launch_persistent_context, channel=chrome) |
| LLM 视觉 | 阿里百炼 DashScope (qwen3.6-plus) |
| LLM 文本 | DeepSeek (v4-pro) |
| 工作流引擎 | LangGraph |
| PDF→PNG | PyMuPDF |
| 通知 | 飞书 API (用户私聊) |
| 配置 | .env (load_dotenv 自动加载) |
| Python | 3.9+ |
| 测试 | pytest, 117 个单元测试 ✅ |

> 新机器配置见 `SETUP_GUIDE.md` | 完整知识库见 `SENLAN-SKILL.md` | 跨 Agent 速查见 `MEMORY.md`
