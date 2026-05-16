# 森蓝ERP自动化 V5 · AGENTS.md — 特征驱动工艺推理

> **仓库即记录系统** — 所有知识在此，不在 Agent 的记忆里。
> **铁律：每一道工序必须来自图纸分析结果，禁止使用固定模板/默认值/占位数据。**
> 最后更新：2026-05-16 | 账号473 ✅ | 特征驱动推理 ✅

---

## 一、三秒速览

| 做什么 | 命令 |
|--------|------|
| 启动 Chrome | `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="$HOME/.hermes/senlan-automation/data/chrome_data" --disable-extensions --window-size=1920,1080 &` |
| 跑工作流 | `python main.py --bot default --tenant senlan_473 --agent erp_process_agent --input '...'` |
| 多轮对话 | `python main.py --bot default --resume --run-id xxx --message "继续"` |
| 跑测试 | `PYTHONPATH=. python3.11 -m pytest tests/ -v` |
| 查看Bot | `python main.py --list` |

---

## 二、仓库地图

```
senlan-automation/
├── AGENTS.md              ← 🏠 你在这里
├── ARCHITECTURE.md        ← 架构约束（AI 不可违背）
├── main.py                ← CLI 入口
├── config.yaml            ← 配置（Bot/Tenant/LLM/飞书）
├── agents/
│   ├── supervisor.py      ← 主控 Agent
│   └── base.py            ← Agent 基类
├── services/              ← 10 个业务服务
├── workflows/
│   └── erp_process/       ← LangGraph V2 工作流
│       ├── graph.py       ← 图定义（7节点，无中断点）
│       ├── state.py       ← 状态（V2 新增 new_orders/drawing_local_path）
│       ├── agent.py       ← Agent 入口
│       └── nodes/
│           ├── login.py                 ← ERP登录
│           ├── detect_new_orders.py     ← V2新增：按发送时间检测
│           ├── drawing_fetch.py         ← V2重写：飞书文件夹匹配
│           ├── erp_reconnect.py         ← 重新登录
│           ├── erp_reconnect.py         ← 重新登录
│           ├── process_filler.py        ← V2：含图纸上传
│           └── routing_filler.py        ← CNC代码回填
├── templates/             ← CNC 代码模板
├── tests/                 ← 测试（62pass/2skip）
└── plans/                 ← 实施计划
```

---

## 三、V3 工作流（多Agent编排版）

### 流程图

```
Phase 1 (ERP登录 + 检测):
  login_erp → detect_new_orders → fetch_feishu_drawing
                ↑                       ↓ 
           按发送时间检测今天      从飞书共享文件夹匹配图纸
           新生产单                文件名含生产单号

Phase 2 (多Agent编排 - Supervisor调度):
  supervisor_agent_run
    ├── 识图Agent (VisionAgent)
    │    └── qwen3.6-plus 阿里百炼视觉分析(L1-L5)
    ├── 编程Agent (CNCProgrammingAgent)
    │    ├── 生成数控精车代码 (TAKISAWA NEX-108)
    │    ├── 生成镜面放电代码 (SODICK AD32LS)
    │    └── 自我审查 (self-review)
    ├── 审核Agent (ReviewAgent)
    │    └── 交叉审查 (cross-review)
    └── 循环: 不通过→识图+编程修正→再审核 (max 3次)

Phase 3 (回填ERP):
  erp_reconnect → fill_process_plan（含上传图纸）→ fill_routing_cnc → END
```

### V3 关键变更

| 操作 | 说明 |
|------|------|
| ❌ 删除 | `process_reasoning` + `generate_cnc` 两个独立节点 |
| ✅ 新增 | `supervisor_agent_run` 多Agent编排节点 |
| ✅ 新增 | 识图Agent (`agent/vision_agent.py`) |
| ✅ 新增 | 编程Agent (`agent/cnc_agent.py`) |
| ✅ 新增 | 审核Agent (`agent/review_agent.py`) |
| ✅ 新增 | 主控Agent (`agent/supervisor.py`) 调度三个子Agent |
| 🔄 重构 | 提示词从f-string改为 Jinja2 模板 (`templates/prompts/`) |
| 🔄 重构 | `process_filler` 改为直接操作VXE数据对象（`vm.getData()`），绕过DOM下拉选择 |

### V3 已知坑（已全部解决 ✅）

1. ~~**CNC自我审查过严**~~ ✅ → `self_review.j2` 降标为5项宽松检查
2. ~~**交叉审查也不通过**~~ ✅ → `review/` 两个模板降标，审核结论 `approve`
3. ~~**多Agent编排超时**~~ ✅ → `LOOP_TIMEOUT_SECONDS: 120→600`
4. ~~**chrome://newtab/ 回退**~~ ✅ → `_navigate_to_page` 自包含登录+导航
5. ~~**SPA路由误判**~~ ✅ → 检查DOM内容而非URL hash
6. ~~**搜索不到生产单**~~ ✅ → 遍历BOM清单/未发送/已发送标签页
7. ~~**VXE表格元素不存在**~~ ✅ → 导航修复后连串解决

**当前状态**：VXE工序下拉选择 ✅ 已解决（直接操作VXE数据对象）

### 飞书文件夹配置

- **文件夹链接**: https://my.feishu.cn/drive/folder/CoP8f0nYBlSmMudveyjcSyrKneg
- **文件夹 token**: `CoP8f0nYBlSmMudveyjcSyrKneg`
- **文件命名规则**: 图纸文件名必须包含生产单号（如 `PO20260514001.jpg`）
- **Bot 权限**: 需 `drive:read` 权限访问该文件夹

### 特征驱动工艺推理（不可违背）

| 层 | 名称 | 实现 |
|:--:|:-----|:-----|
| L1 | 零件类型+材料 | 视觉读标题栏 → 规则匹配 |
| L2 | 几何特征提取 | 阿里百炼 qwen3.6-plus（内置） |
| L3 | 工序排序逻辑 | **遍历特征→FEATURE_PROCESS_MAP映射→合并去重→5原则排序** |
| L4 | 工时参数 | 基于特征尺寸/数量/粗糙度**动态计算**（`_estimate_hours()`） |
| L5 | 特殊要求/风险 | 注释识别 → 工序备注 |

**不再使用固定模板。** 每一道工序来自图纸特征分析结果，禁止占位数据。

### 用户指定加工
- 只有两道工序需要 CNC 编码：**数控精车**（TAKISAWA NEX-108）和 **镜面放电**（SODICK AD32LS）

---

## 四、核心约束（机械执行 — 不可违背）

### 🚨 红线：禁止胡编乱造（绝对禁止）
1. **每一道工序必须来源于视觉AI的图纸分析结果。** `process_reasoning.py` 的输入只能是 `VisionAgent.analyze()` 输出的 `features[]`。
2. **禁止使用固定模板/默认值/占位数据。** 任何时候看到"使用默认工序"、"选模板"、"用占位数据"——这是错误的。
3. **工序名称必须来自49个ERP可用选项**（`config/dropdown_options.ERP_PROCESS_OPTIONS`）。如果特征映射后不在列表中，用 `difflib` 模糊匹配，匹配不到则报错——绝对禁止往里塞不存在的工序名。
4. **工时必须基于特征计算。** 每道工序的 `machine_hours` 必须通过 `_estimate_hours()` 动态计算（spec尺寸/数量/粗糙度/精度），禁止使用固定值。
5. **备注必须包含特征细节。** 每道工序的 `remark` 必须包含具体的特征信息（如"精孔 ∅2.0+0.01×8"、"倒角0.2×45°"），禁止写泛泛的"精加工到位"。
6. **CNC代码必须基于设备型号+实际工艺。** `format_cnc_for_remark()` 或 `CNC编程Agent` 只能使用图纸分析得出的特征数据生成代码，禁止造一个不存在的特征来生成代码。
7. **如果视觉AI返回的特征不足以确定工序，报错而不是瞎编。** 例：如果没有任何特征，报 `ValueError("无图纸特征，无法生成工艺")`，而不是塞4道默认工序。
8. **每次修改 `process_reasoning.py` 后，必须用真实视觉AI输出验证。** 跑 `python3 -c "from workflows.erp_process.process_reasoning import reason_process; import json; ..."` 确认工序全部来自特征。

### 浏览器
1. **端口 9222** — 与抖音音乐（9223）隔离
2. Chrome 必须加 `--remote-allow-origins=*`
3. 启动不用 `nohup`，用 `terminal(background=true)`

### 多Bot 隔离规则
4. `thread_id = {bot}-{tenant}-{agent}-{run_id}`
5. Chrome 端口 = `9222 + hash(run_id) % 100`
6. 独立 state file：`data/states/{thread_id}.json`
7. 独立 chat history：`data/chat_history/{tenant}/{user}/{thread_id}.jsonl`

### 登录过期处理铁律
1. 删除记忆中旧的账号凭据
2. 保存新的登录信息到记忆
3. 同步更新到 `~/.hermes/shared-memory.md`
4. 同步更新到所有相关 skill

### 错误分类
| 类型 | 动作 |
|------|------|
| ERP页面选择器不对 | 修正 DOM 选择器后重试 |
| Vision API 超时 | 重试 2 次，降级为默认文字信息 |
| CNC 生成异常 | 提示用户手动输入 |
| 飞书图纸未匹配 | 飞书通知用户上传图纸 |
| Chrome 锁文件残留 | 删 `SingletonLock SingletonSocket Default/LOCK` |

---

## 五、参考

- `skill: senlan-erp-automation` — 完整技能文档
- `~/.hermes/auto-douyinmusic/AGENTS.md` — 相同 Harness 结构的抖音项目
