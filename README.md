| # 🏭 森蓝精密 · ERP 工艺自动化系统 V6

> AI读2D工程图 → 五层特征驱动推理 → ERP自动填入全部工序 → CNC代码生成（真实图纸数据驱动） → 飞书全量返回G代码

## 快速开始

```bash
cd ~/.hermes/senlan-automation

# 全流程：扫图纸→视觉分析→填ERP→自动调CNC编程→保存结果
# 一条命令搞定（含CNC代码生成+自审+交叉审查）
python3 scripts/fill_by_vision.py --drawings-dir /Volumes/m2/erp/ --account 472

# 指定单号+零件子集
python3 scripts/fill_by_vision.py --drawings-dir /Volumes/m2/erp/ --prod-no C03026051501 --parts 001,002 --account 472

# 单独跑 CNC 编程（已有分析缓存时）
python3 scripts/run_cnc_pipeline.py --prod-no C03026051501
```

**无需手动 export 环境变量** — `.env` 由脚本自动加载。

## 核心流程

```
图纸PDF (目录扫描)
  → { 生产单号-零件号.pdf } 文件名驱动匹配
  → PyMuPDF 转 PNG (~0.1s)
  → 阿里百炼 qwen-vl-max 视觉分析 (~3min/张)
  → 特征驱动推理引擎:
      L1: 零件类型 + 材料 (圆件/方件)
      L2: 几何特征 → 工序映射 (16种特征类型)
      L3: 5原则排序 (热处分水岭/粗前精后/基准先行/慢丝在后/表面最后)
      L4: 工时估算 (按尺寸/数量/粗糙度自适应)
      L5: 特殊要求 (刻字/利角/涂层)
  → ERP浏览器操作:
      遍历标签页 (未发送→BOM清单→已发送)
      按 生产单号+零件号 双条件匹配行
      开弹窗 → 填全部工序 → 保存
  → 飞书私聊通知完成状态
```

## 多零件生产单支持

| 文件命名 | 含义 |
|----------|------|
| `C03026051501-001.pdf` | 生产单 C03026051501, 零件号 001 |
| `C03026051501-002.pdf` | 生产单 C03026051501, 零件号 002 |
| `C03026051501-A1.pdf` | 生产单 C03026051501, 零件号 A1 |
| `W20126051401.pdf` | 单零件, 无零件号 |

**关键设计**：
- 文件名驱动： `(prod_no, part_no)` 从文件名用第一个 `-` 切分提取
- 跨标签搜索：每个零件遍历全部三个标签页
- 独立浏览器：每零件保存后关闭浏览器，避免弹窗遮罩残留
- 零件号无格式限制：001/002/A1/M1 均可

## 项目结构

```
senlan-automation/
├── scripts/
│   └── fill_by_vision.py          ⭐ 全流程入口（678行）
├── workflows/erp_process/
│   ├── process_reasoning.py       ⭐ 特征驱动推理引擎（728行）
│   ├── agents/
│   │   ├── vision_agent.py        ← 阿里百炼视觉分析
│   │   ├── cnc_agent.py           ← CNC编程Agent
│   │   └── review_agent.py        ← 自审+交叉审查
│   └── prompts/                   ← Jinja2提示词模板
├── config/
│   └── dropdown_options.py        ← 49个ERP工序选项
├── services/
│   ├── llm_client.py              ← LLM网关（PDF→base64）
│   └── playwright_erp.py          ← Playwright ERP封装
├── templates/prompts/vision/
│   ├── analyze.j2                 ← 视觉分析提示词
│   ├── system.j2                  ← 视觉系统提示词
│   └── few_shot.j2                ← 少样本示例
├── .env                           ← API Keys（不上传git）
├── SETUP_GUIDE.md                 ← 新机器配置指引\n└── MEMORY.md                      ← 项目记忆（跨会话）
```

## 五层推理引擎

`workflows/erp_process/process_reasoning.py`

| 层级 | 名称 | 实现 |
|:----:|------|------|
| L1 | 零件类型 | 视觉读标题栏 → 圆件/方件/异形 + ASTAVA ESR/S136/K490 |
| L2 | 特征提取 | 16种特征类型 → FEATURE_PROCESS_MAP 映射到工序 |
| L3 | 排序规则 | 热处分水岭(<25粗加工/25热处理/≥25精加工) |
| L4 | 工时估算 | 尺寸×数量×粗糙度自适应，英制自动检测×25.4 |
| L5 | 特殊要求 | Sharp edge/TiN/刻字 → 嵌入对应工序备注 |

## 模型配置

| 用途 | 模型 | API |
|------|------|-----|
| 视觉分析 | qwen3.6-plus (阿里百炼) | DashScope |
| 文本/编程 | deepseek-v4-pro | DeepSeek |

## 红线

- ❌ 禁止胡编乱造工序（必须来自图纸分析结果）
- ❌ 禁止使用模板/占位数据/fallback工艺
- ❌ 禁止操作非目标生产单
- ❌ 禁止 git push 未经允许

## 技术栈

| 组件 | 选型 |
|------|------|
| 浏览器自动化 | Playwright (persistent_context) |
| LLM视觉 | 阿里百炼 qwen3.6-plus |
| LLM文本 | DeepSeek v4-pro |
| PDF→PNG | PyMuPDF (策略1) |
| 通知 | 飞书 API (用户私聊) |
| 配置 | .env (load_dotenv自动加载) |
| Python | 3.9+ |

> 完整迁移配置指南见 `SETUP_GUIDE.md`
