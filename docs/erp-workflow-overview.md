# ERP 工艺自动化 · 设计文档

## 整体流程

```
用户输入（客户/零件/数量）
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: Online ERP                                         │
│                                                             │
│ login_erp → create_order → fetch_drawing                    │
│                              ↕ interrupt_after              │
│               （暂停等待：用户确认图纸/手动上传）             │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: Offline AI                                         │
│                                                             │
│ template_match                                               │
│      │                                                      │
│      ├─（匹配到）→ process_reasoning（直接适配模板）        │
│      └─（未匹配）→ vision_analyze → process_reasoning       │
│                                          │                  │
│                                          ▼                  │
│                                   generate_cnc              │
│                                      ↕ interrupt_after      │
│                 （暂停等待：人工审核 CNC 代码）              │
└─────────────────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ Phase 3: Online ERP                                         │
│                                                             │
│ erp_reconnect → fill_process_plan → fill_routing_cnc → END  │
└─────────────────────────────────────────────────────────────┘
```

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

**create_order** — 创建销售订单
- 导航到 `/Sales/OrderCreate` → 填写客户/产品/数量/交期 → 提交
- 提取生产单号：4种策略（URL参数/页面元素/正则/关键词）
- 降级：浏览器不可用时自动生成模拟单号
- 返回: `{prod_no, checkpoint: 8}`

**fetch_drawing** — 获取2D图纸
- 导航到计划工艺页面 → 搜索附件区域
- 支持格式：PDF/PNG/JPG/DWG/DXF
- 降级：无附件时等待用户手动上传
- 飞书通知：Phase 1 完成
- 返回: `{drawing_url, checkpoint: 10}`

### Phase 2 节点

**template_match** — 匹配已有图纸模板
- 通过 DrawingRegistry 按零件名搜索
- 命中 → 跳过 Vision，直接走模板适配
- 未命中 → 走 Vision 分析
- 返回: `{matched_template, checkpoint: 15}`

**vision_analyze** — Qwen-VL 视觉分析
- 调用 DashScope Vision API 分析 2D 工程图
- 输出 L1 零件信息（名称/材料/硬度/涂层）
- 输出 L2 几何特征（外形/孔/螺纹/槽/斜面/利角）
- 输出 L5 特殊要求（刻字/涂层/注意事项）
- 注册到 DrawingRegistry
- 返回: `{part_info, features, checkpoint: 17}`

**process_reasoning** — 五层工艺推理
- L1：零件类型 → 选择工艺路线模板
- L2：几何特征 → 映射到加工手段
- L3：5原则排序工序
- L4：切削参数（知识库 RAG）
- L5：特殊注意事项注入
- 形状规则：方形→铣磨放电(14步)，圆形→车磨放电(7步)
- 返回: `{process_plan, checkpoint: 18}`

**generate_cnc** — CNC 代码生成
- 使用 Jinja2 模板渲染 TAKISAWA NEX-108 G 代码
- 生成 SODICK AD32LS EDM 镜面放电参数表
- 收集注意事项（利角/交期等）
- 飞书通知：CNC 待审核
- 返回: `{cnc_code, checkpoint: 20}`

### Phase 3 节点

**erp_reconnect** — 重新登录ERP
- Phase 2 耗时较长，session 可能过期
- 重新登录但不导航到特定页面
- 返回: `{checkpoint: 22}`

**fill_process_plan** — 回填计划工艺
- 导航到 `{erp_url}/Plan/ProcessPlan?prod_no={prod_no}`
- 找到工艺计划表格 → 填入14道工序 → 提交
- 支持表格布局和扁平输入框布局
- 返回: `{plan_saved, checkpoint: 25}`

**fill_routing_cnc** — 回填计划工序CNC代码
- 导航到 `{erp_url}/Plan/ProcessRouting?prod_no={prod_no}`
- 定位"数控精车"行 → 填入 TAKISAWA CNC 代码
- 定位"镜面放电"行 → 填入 SODICK EDM 参数
- 飞书通知：工作流完成
- 返回: `{routing_saved, cnc_saved, checkpoint: 30}`

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
