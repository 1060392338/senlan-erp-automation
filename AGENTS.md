# 森蓝ERP自动化 · AGENTS.md

> **仓库即记录系统** — 所有知识在此，不在 Agent 的记忆里。
> 最后更新：2026-05-14 | Harness Engineering✅

---

## 一、三秒速览

| 做什么 | 命令 |
|--------|------|
| 启动 Chrome | `bash scripts/start_chrome.sh`（端口9222） |
| 跑工作流 | `python main.py --bot default --tenant senlan_472 --agent erp_process_agent --input '...'` |
| 多轮对话 | `python main.py --bot default --resume --run-id xxx --message "CNC OK"` |
| 跑测试 | `PYTHONPATH=. python3.11 -m pytest tests/ -v` |
| 查看Bot | `python main.py --list` |

---

## 二、仓库地图

```
senlan-automation/
├── AGENTS.md              ← 🏠 你在这里
├── ARCHITECTURE.md        ← 架构约束（AI 不可违背）
├── main.py                ← CLI 入口
├── config.yaml            ← 配置（Bot/Tenant/LLM）
├── agents/
│   ├── supervisor.py      ← 主控 Agent
│   └── base.py            ← Agent 基类
├── services/              ← 10 个业务服务
│   ├── browser_service.py ← Chrome 浏览器控制（端口9222）
│   ├── service_container.py ← 实例级容器（v3.0 核心）
│   ├── chat_history.py    ← 多轮对话历史
│   ├── tenant_context.py  ← 租户上下文
│   └── ...
├── workflows/             ← LangGraph 工作流
├── docs/
│   ├── erp-workflow-overview.md  ← 🔑 ERP工作流设计文档
│   └── implementation-plan.md    ← n8n系统的实现计划（另一项目）
├── templates/             ← CNC 代码模板
├── tests/                 ← 测试（60pass/2skip）
└── plans/                 ← 实施计划
```

---

## 三、核心约束（机械执行）

### 浏览器
1. **端口 9222** — 与抖音音乐（9223）隔离
2. Chrome 必须加 `--remote-allow-origins=*`
3. `BrowserService.close()` 用 `page.quit()` 不是 `page.get("about:blank")`

### 多Bot 隔离规则
4. `thread_id = {bot}-{tenant}-{agent}-{run_id}`
5. Chrome 端口 = `9222 + hash(run_id) % 100`
6. 独立 state file：`data/states/{thread_id}.json`
7. 独立 chat history：`data/chat_history/{tenant}/{user}/{thread_id}.jsonl`

### 五层工艺推理（不可违背顺序）
| 层 | 名称 | 实现 |
|:--:|:-----|:-----|
| L1 | 零件类型+材料 | 视觉读标题栏 → 规则匹配 |
| L2 | 几何特征提取 | DashScope Qwen-VL + OCR |
| L3 | 工序排序逻辑 | 5原则：先粗后精/热处理分水岭/基准先行/慢丝后置/表面最后 |
| L4 | 切削参数 | 知识库 + 工厂校准表 |
| L5 | 特殊要求/风险 | 注释识别 → 工序备注 |

形状→模板：**方形→铣→磨→放电（14步）**；**圆形→车→磨→放电（7步）**

### 错误分类
| 类型 | 动作 |
|------|------|
| ERP页面选择器不对 | 修正 DOM 选择器后重试 |
| Vision API 超时 | 重试 2 次，降级为文字描述 |
| CNC 生成异常 | 提示用户手动输入 |

---

## 四、参考

- `skill: senlan-erp-automation` — 完整技能文档
- `~/.hermes/auto-douyinmusic/AGENTS.md` — 相同 Harness 结构的抖音项目
- `github.com/deusyu/harness-engineering` — 本仓库遵循的工程范式
