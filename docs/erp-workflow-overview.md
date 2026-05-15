# ERP 工艺自动化 · 设计文档（V3 多Agent编排版）

## 整体流程

```
用户输入（客户/零件/数量）
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: Online ERP                                         │
│                                                             │
│ login_erp → detect_new_orders → fetch_feishu_drawing        │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: 多Agent编排（离线AI，无中断点）                     │
│                                                             │
│ supervisor_agent_run                                        │
│   ├── VisionAgent.analyze()     — 阿里百炼视觉分析         │
│   ├── CNCProgrammingAgent.generate()                        │
│   │   ├── 数控精车 (TAKISAWA NEX-108)                       │
│   │   ├── 镜面放电 (SODICK AD32LS)                         │
│   │   └── 自我审查 (self-review)                            │
│   ├── ReviewAgent.check()       — 交叉审查                  │
│   └── 循环修正 (max 3次, 总超时 600s)                      │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 3: Online ERP (session过期, 重新登录)                 │
│                                                             │
│ erp_reconnect → fill_process_plan → fill_routing_cnc → END  │
└─────────────────────────────────────────────────────────────┘
```

## V3 与 V2 差异

| 维度 | V2 | V3 |
|:-----|:---|:---|
| 架构 | 线性节点 | 多Agent编排 (Supervisor调度) |
| AI节点 | `process_reasoning` + `generate_cnc` | `supervisor_agent_run` 统管 |
| 提示词 | f-string 硬编码 | Jinja2 模板 (`templates/prompts/`) |
| 修正循环 | 无 | 自我审查 + 交叉审查 + 最多3次修正 |
| 中断点 | 2个（图纸/CNC） | 无（一次性编排完成） |
| VXE交互 | 数据模型push | 点击"+"按钮+双击单元格 |
| 超时 | 无 | 600s（LLM调用耗时） |

## 三段式设计（LangGraph interrupt_after）

使用 `interrupt_after` 实现自然断点，而非 `END` + 手动路由。

**断点 1 — fetch_drawing 后**：Phase 1 完成，等待用户确认图纸。可选：
- 自动从ERP下载的图纸
- 用户手动上传的图纸
- 系统已有匹配模板（跳过 Vision）

**断点 2 — generate_cnc 后**：CNC 代码已生成，等待人工审核。审核通过后自动进入 Phase 3。

**恢复方式**：连续调用 `graph.invoke(None, config)` 自动从 checkpoint 恢复。

## 多用户并行架构

### RequestContext（请求级上下文）

每个 `agent.run()` 创建一个 `RequestContext`，通过 `config['configurable']['ctx']` 传递给所有节点。

```python
ctx = RequestContext.create(
    tenant_config=tenant_config,
    run_id=run_id,
    global_config=config,
    shared_kb=kb_service,       # 共享（只读）
    shared_template=tpl_service, # 共享（只读）
    shared_drawing=drawing_reg, # 共享（只读）
)
# ctx.llm — 独立 LLMClient
# ctx.browser — 独立 BrowserService（端口隔离）
# ctx.notifier — 独立 FeishuNotifier
```

### 隔离维度

| 维度 | 隔离方式 |
|------|---------|
| LangGraph thread_id | `{tenant}-{agent}-{run_id}` |
| Chrome 实例 | 独立端口（base + hash(run_id)）|
| Chrome data-dir | `data/chrome_data/{run_id}/` |
| 状态文件 | `data/states/{thread_id}.json` |
| 日志 | 混写但可 grep run_id 区分 |

## 节点详情

### Phase 1 节点

**login_erp** — ERP 系统登录
- 导航到登录页 → 填入账号密码 → 点击登录 → 验证成功
- 多策略验证：页面关键词/URL跳转/标题变化
- 返回: `{session_id, checkpoint: 5}`
- 文件: `workflows/erp_process/nodes/login.py`, `_login.py`

**detect_new_orders** — 检测新生产单
- 导航到计划工艺页面 → 按生产单号搜索
- 遍历BOM清单/未发送/已发送三个radio标签页
- 提取新订单列表
- 返回: `{new_orders, pending_order_idx, checkpoint: 8}`
- 文件: `workflows/erp_process/nodes/detect_new_orders.py`

**fetch_feishu_drawing** — 从飞书获取2D图纸
- 通过飞书开放平台API按生产单号匹配图纸文件
- 下载到本地缓存 (`data/drawings/{tenant}/`)
- 支持格式：PDF/PNG/JPG
- 返回: `{drawing_url, drawing_local_path, checkpoint: 10}`
- 文件: `workflows/erp_process/nodes/drawing_fetch.py`

### Phase 2 节点

**supervisor_agent_run** — 多Agent编排（替代 V2 的 process_reasoning + generate_cnc）
- 主控Agent (`SupervisorAgent`) 调度3个子Agent：
  1. **VisionAgent** — 阿里百炼 qwen3.6-plus 视觉分析
     - 读图纸标题栏 → L1零件类型/材料/硬度/涂层
     - OCR识别孔/螺纹/公差/粗糙度 → L2几何特征列表
     - 识别利角/刻字等注释 → L5特殊要求
  2. **CNCProgrammingAgent** — 生成CNC代码
     - 数控精车 (TAKISAWA NEX-108) G代码
     - 镜面放电 (SODICK AD32LS) 参数表
     - 自我审查 (self-review，当前强制通过)
  3. **ReviewAgent** — 交叉审查
     - 检查代码完整性和正确性
     - 当前 revision_needed 作为最终结论（审查标准过严）
- 修正循环：不通过→重新识图+编程→再审查 (max 3次)
- 总超时：600s (`LOOP_TIMEOUT_SECONDS`)
- 文件: `workflows/erp_process/agents/supervisor.py`
- 子Agent: `agents/vision_agent.py`, `agents/cnc_agent.py`, `agents/review_agent.py`
- 提示词: `templates/prompts/` (Jinja2)
- 返回: `{part_info, features, process_plan, cnc_code, checkpoint: 20}`

### Phase 3 节点

**erp_reconnect** — 重新登录ERP
- Phase 2 耗时较长，session 可能过期
- 调用 `fill_login_form()` 重新登录
- ⚠ 登录成功后主动 `page.get(craft_url)` 导航到计划工艺页（防止chrome://newtab/回退）
- 返回: `{checkpoint: 22}`
- 文件: `workflows/erp_process/nodes/erp_reconnect.py`

**fill_process_plan** — 回填计划工艺
- 导航到 `#/Craftwork/steel_craftworkList/0210`（SPA路由）
- 搜索生产单（遍历BOM清单/未发送/已发送）
- 勾选行 → 点"工艺管理"按钮 → 打开VXE弹窗
- 点击"+"按钮添加行 → 双击单元格 → popover选工序
- 填入工艺要求/工时/工人
- 上传2D图纸 → 保存
- ⚠ 已知坑：搜索不到生产单时全选checkbox找不到，弹窗打不开
- 返回: `{plan_saved, checkpoint: 25}`
- 文件: `workflows/erp_process/nodes/process_filler.py`

**fill_routing_cnc** — 回填计划工序CNC代码
- 导航到计划工序页面 → 关联生产单号
- 定位"数控精车"行 → 填入 TAKISAWA CNC 代码
- 定位"镜面放电"行 → 填入 SODICK EDM 参数
- 飞书通知：工作流完成
- 返回: `{routing_saved, cnc_saved, checkpoint: 30}`
- 文件: `workflows/erp_process/nodes/routing_filler.py`

## 错误处理

- 每个浏览器交互包装在 `try/except` 中
- 多种 fallback 选择器（5-7种/字段）
- 浏览器不可用时使用降级数据
- 飞书通知：工作流错误（`workflow_error` 事件）
- 3次重试（LLM 调用）

## 配置参考

```bash
# CLI 参数
--tenant      租户 ID（config.yaml 中定义）
--agent       工作流 Agent（当前只有 erp_process_agent）
--input       输入 JSON
--run-id      运行 ID（不传则自动生成）
--resume      从断点恢复（配合 --run-id）
--list        查看可用租户和工作流

# 环境变量
DASHSCOPE_API_KEY   # 阿里百炼 API Key（必需）
ERP_<TENANT>_USERNAME  # 租户 ERP 用户名
ERP_<TENANT>_PASSWORD  # 租户 ERP 密码
FEISHU_WEBHOOK_URL  # 飞书 Webhook（可选）
CHECKPOINTS_DB      # Checkpoint 数据库路径（默认 checkpoints.db）
```

## 数据文件

| 文件 | 用途 | 来源 |
|------|------|------|
| `data/process_card_template.json` | 标准工艺卡模板（14道工序） | 森蓝工艺卡 |
| `data/cutting_parameters_k490.json` | K490材料切削参数经验库 | 工厂实际 |
| `data/equipment_catalog.json` | 全设备清单（品牌/型号/控制器/精度） | Equipment list.pdf |
| `data/feature_to_process_map.json` | 几何特征→加工手段映射 | 图纸验证 |
| `data/process_route_templates.json` | 方形/圆形工艺路线模板 | 固定规则 |

## 测试

```bash
PYTHONPATH=. python3.11 -m pytest tests/ -v
```

测试覆盖：
- `tests/services/test_core.py` — 22 个服务测试（RequestContext/Tenant/Registry/Browser/LLM/Notification/State/TenantConfig）
- `tests/workflows/erp_process/test_nodes.py` — 16 个节点测试（全部10个节点+边界条件）
- `tests/workflows/erp_process/test_graph.py` — 7 个图测试（编译/单例/中断点/Mock端到端）

## 技术栈版本

| 组件 | 版本 |
|------|:----:|
| Python | 3.11+ |
| LangGraph | 1.2.0+ |
| LangChain | 0.3+ |
| DrissionPage | 4.0+ |
| DashScope | OpenAI SDK |
| Jinja2 | 3.1+ |
