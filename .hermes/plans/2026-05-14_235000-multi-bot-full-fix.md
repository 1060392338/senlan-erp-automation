# 多Bot实例化 + 全量修复 执行计划

## 目标
1. 多Bot架构：Bot A → 用户A, Bot B → 用户B，完全独立实例
2. 多轮对话：中断点自然语言反馈 + 会话历史留存
3. 代码质量：修复所有P0-P3问题，提取公共模式

## 改造范围

### ── Phase A: 多Bot实例化（核心架构） ──

| # | 文件 | 改动 |
|---|------|------|
| A1 | `services/__init__.py` | 导出 ServiceContainer + 保留ServiceRegistry(兼容) |
| A2 | `services/context.py` | 添加 `chat_history` 字段 + `user_id` 参数 |
| A3 | `workflows/erp_process/graph.py` | 删除 `_graph_instance` 单例 → 接受外部 checkpointer |
| A4 | `workflows/erp_process/agent.py` | 重写：接受 `service_container` 参数，每实例独立图 |
| A5 | `main.py` | 支持 `--bot-id` 参数，多 Bot 实例独立运行 |

### ── Phase B: 多轮对话（用户交互） ──

| # | 文件 | 改动 |
|---|------|------|
| B1 | `workflows/erp_process/state.py` | 添加 `user_message`, `chat_history` 状态字段 |
| B2 | `workflows/erp_process/nodes/process_reasoning.py` | 修复 `_adapt_template` 忽略 template_id |
| B3 | `workflows/erp_process/agent.py` | agent.run() 接受 user_message，中断点保存对话 |
| B4 | `workflows/erp_process/graph.py` | 添加对话节点：中断点保存+恢复上下文 |

### ── Phase C: 代码质量 ──

| # | 文件 | 改动 |
|---|------|------|
| C1 | `workflows/erp_process/nodes/*.py` | 魔数 checkpoint → `Checkpoint` 枚举 |
| C2 | `services/context.py` | `RequestContext.close()` 不关闭浏览器（暂停时） |
| C3 | `workflows/erp_process/nodes/sales_order.py` | 抽取公共元素查找逻辑 |
| C4 | `workflows/erp_process/_login.py` | 合并到 `login.py` |
| C5 | `workflows/erp_process/nodes/` | 创建 `ERPPageBase` 基类（可选） |

### ── Phase D: 测试验证 ──

| # | 文件 | 改动 |
|---|------|------|
| D1 | `tests/services/test_core.py` | 添加 ServiceContainer 测试 |
| D2 | `tests/workflows/test_multi_bot.py` | 新增多Bot隔离测试 |
| D3 | 全量regression | 45原有测试保持pass |

## 执行顺序

```
A1 → A2 → A3 → A4 → A5   (核心架构，串行依赖)
         ↓
B1 → B2 → B3 → B4         (对话功能，依赖A4)
         ↓
C1 → C2 → C3              (代码质量，可并行)
         ↓
D1 → D2 → D3              (测试验证)
```

## 风险控制
- 每步修改后立即编译验证
- ServiceRegistry 保留不删，保证兼容过渡
- 测试在每阶段结束后运行，即时修正
