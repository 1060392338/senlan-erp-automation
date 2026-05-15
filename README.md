# 🏭 森蓝精密 · ERP 工艺自动化系统

> 销售订单 → AI读2D图纸 → 工艺推理 → CNC代码生成 → ERP回填

## 快速开始

```bash
# 1. 安装依赖（Python 3.11 必需）
pip install -r requirements.txt

# 2. 配置密钥
cp .env.example .env
# 编辑 .env 填入 DASHSCOPE_API_KEY + ERP 账号密码

# 3. 运行工作流
python main.py --tenant senlan_472 --agent erp_process_agent \
  --input '{"customer":"客户X","part_name":"Cutting blade","qty":2}'

# 4. 断点恢复（Phase 1 → Phase 2，或 Phase 2 → Phase 3）
python main.py --resume --tenant senlan_472 --agent erp_process_agent \
  --run-id <自动生成的 run_id>

# 5. 查看可选租户和工作流
python main.py --list
```

## 架构

```
senlan-automation/
├── agents/           # Agent 层 — WorkflowAgent 统一接口 + Supervisor 调度
├── services/         # 共享基础设施
│   ├── context.py         # RequestContext（请求级隔离，多用户并行关键）
│   ├── llm_client.py      # DashScope LLM 网关（自动重试）
│   ├── browser_service.py # DrissionPage 浏览器工厂（端口隔离）
│   ├── kb_service.py      # 知识库 BM25+FAISS 混合检索
│   ├── template_service.py# Jinja2 CNC 模板引擎
│   ├── drawing_registry.py# 图纸特征登记簿
│   ├── notification_service.py # 飞书通知
│   └── state_service.py   # 状态持久化
├── workflows/        # 业务工作流
│   └── erp_process/  # ERP 工艺工作流（当前唯一）
│       ├── graph.py       # LangGraph 定义（interrupt_after 三段式）
│       ├── agent.py       # ERPProcessAgent 实现
│       ├── state.py       # ERPState TypedDict
│       ├── nodes/         # 10 个节点函数
│       └── pages/         # 3 个 ERP 页面封装
├── data/             # 数据文件
│   ├── documents/         # 知识库文档（md）
│   ├── cutting_params/   # K490 切削参数
│   ├── process_card_template.json
│   ├── cutting_parameters_k490.json
│   ├── equipment_catalog.json
│   ├── feature_to_process_map.json
│   └── process_route_templates.json
├── templates/        # CNC 代码模板（Jinja2）
│   ├── takisawa_nex108_finish.j2
│   ├── hardinge_51u_finish.j2
│   └── sodick_ad32ls_edm.j2
├── tests/            # 45 个测试
└── config.yaml       # 全局配置（多租户）
```

## LangGraph 三段式工作流

```
START → login_erp → create_order → fetch_drawing
                                     ↕ interrupt_after（等人确认图纸）
                                   → template_match → (vision_analyze? →) process_reasoning
                                   → generate_cnc
                                     ↕ interrupt_after（人工审核 CNC 代码）
                                   → erp_reconnect → fill_process_plan → fill_routing_cnc → END
```

**Phase 1 (Online ERP)** — 登录 → 创建销售订单 → 获取图纸
**Phase 2 (Offline AI)** — 模板匹配 → 视觉分析(可选) → 工艺推理 → CNC生成
**Phase 3 (Online ERP)** — 重新登录 → 回填计划工艺 → 回填CNC代码

## 多用户并行

每个 `--run-id` 独立的：
- **RequestContext**: 独立 LLMClient + BrowserService
- **Chrome 实例**: 独立端口 + 独立 user-data-dir
- **LangGraph thread_id**: `{tenant}-{agent}-{run_id}`
- **状态文件**: `data/states/{thread_id}.json`

```bash
# 用户 A
python main.py --tenant senlan_472 --agent erp_process_agent \
  --input '{"customer":"A","part_name":"Blade","qty":2}'

# 用户 B（同时）
python main.py --tenant senlan_472 --agent erp_process_agent \
  --input '{"customer":"B","part_name":"Die","qty":1}'
# 互不干扰 ✅
```

## 添加新租户

```yaml
# config.yaml 的 tenants 段
- id: new_tenant
  display_name: "新公司"
  erp:
    url: "http://112.74.35.30/"
    username: "${ERP_NEW_TENANT_USERNAME}"
    password: "${ERP_NEW_TENANT_PASSWORD}"
  feishu:
    notify_on: [workflow_start, workflow_complete]
```

```bash
# .env 加两行
ERP_NEW_TENANT_USERNAME=xxx
ERP_NEW_TENANT_PASSWORD=yyy
```

## 五层工艺推理

| 层级 | 名称 | 实现方式 |
|:----:|------|---------|
| L1 | 零件类型+材料 | 视觉读标题栏 + 规则匹配 |
| L2 | 几何特征提取 | DashScope Qwen-VL + OCR |
| L3 | 工序排序逻辑 | 5原则硬编码规则引擎 |
| L4 | 切削参数 | 知识库 RAG + 工厂校准表 |
| L5 | 特殊要求/风险 | 注释识别 → 工序备注插入 |

**形状→工艺路线规则**：
- 方形→铣→磨→放电（14步）
- 圆形→车→磨→放电（7步）

## 测试

```bash
PYTHONPATH=. python3.11 -m pytest tests/ -v
# 45 passed, 2 skipped
```

## 技术栈

| 组件 | 选型 |
|------|------|
| 框架 | LangGraph 1.2 |
| 浏览器 | DrissionPage (ChromiumPage) |
| LLM | DashScope Qwen-Max / Qwen-VL |
| 知识库 | LangChain BM25 + FAISS |
| CNC模板 | Jinja2 |
| 通知 | 飞书 Webhook / API |
| 配置 | YAML + .env |
| Python | 3.11+ |
