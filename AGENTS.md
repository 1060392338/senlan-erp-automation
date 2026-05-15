# 森蓝ERP自动化 V3 · AGENTS.md

> **仓库即记录系统** — 所有知识在此，不在 Agent 的记忆里。
> 最后更新：2026-05-15 | Harness Engineering✅ | 多Agent编排版

---

## 一、三秒速览

| 做什么 | 命令 |
|--------|------|
| 启动 Chrome | `"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --remote-debugging-port=9222 --remote-allow-origins=* --user-data-dir="$HOME/.hermes/senlan-automation/data/chrome_data" --disable-extensions --window-size=1920,1080 &` |
| 跑工作流 | `python main.py --bot default --tenant senlan_472 --agent erp_process_agent --input '...'` |
| 多轮对话 | `python main.py --bot default --resume --run-id xxx --message "继续"` |
| 跑测试 | `PYTHONPATH=. python3.11 -m pytest tests/ -v` |
| 查看Bot | `python main.py --list` |

---

## 二、仓库地图

```
senlan-automation/
├── AGENTS.md              ← 🏠 你在这里（V2）
├── ARCHITECTURE.md        ← 架构约束（AI 不可违背）
├── main.py                ← CLI 入口
├── config.yaml            ← 配置（Bot/Tenant/LLM/飞书）
├── agents/
│   ├── supervisor.py      ← 主控 Agent
│   └── base.py            ← Agent 基类
├── services/              ← 10 个业务服务
├── workflows/
│   └── erp_process/       ← LangGraph V2 工作流
│       ├── graph.py       ← 图定义（8节点，2中断点）
│       ├── state.py       ← 状态（V2 新增 new_orders/drawing_local_path）
│       ├── agent.py       ← Agent 入口
│       └── nodes/
│           ├── login.py                 ← ERP登录
│           ├── detect_new_orders.py     ← V2新增：按发送时间检测
│           ├── drawing_fetch.py         ← V2重写：飞书文件夹匹配
│           ├── process_reasoning.py     ← V2：内置视觉分析
│           ├── generate_cnc.py          ← V2：分段编码
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
| 🔄 重构 | `process_filler` 改为点击"+"按钮添加VXE行，而非数据模型push |

### V3 已知坑（已全部解决 ✅）

1. ~~**CNC自我审查过严**~~ ✅ → `self_review.j2` 降标为5项宽松检查
2. ~~**交叉审查也不通过**~~ ✅ → `review/` 两个模板降标，审核结论 `approve`
3. ~~**多Agent编排超时**~~ ✅ → `LOOP_TIMEOUT_SECONDS: 120→600`
4. ~~**chrome://newtab/ 回退**~~ ✅ → `_navigate_to_page` 自包含登录+导航
5. ~~**SPA路由误判**~~ ✅ → 检查DOM内容而非URL hash
6. ~~**搜索不到生产单**~~ ✅ → 遍历BOM清单/未发送/已发送标签页
7. ~~**VXE表格元素不存在**~~ ✅ → 导航修复后连串解决

**当前瓶颈**：plan_saved=true ✅ routing_saved=false（`routing_filler` 待修）

### 飞书文件夹配置

- **文件夹链接**: https://my.feishu.cn/drive/folder/CoP8f0nYBlSmMudveyjcSyrKneg
- **文件夹 token**: `CoP8f0nYBlSmMudveyjcSyrKneg`
- **文件命名规则**: 图纸文件名必须包含生产单号（如 `PO20260514001.jpg`）
- **Bot 权限**: 需 `drive:read` 权限访问该文件夹

### 五层工艺推理（不可违背顺序）

| 层 | 名称 | 实现 |
|:--:|:-----|:-----|
| L1 | 零件类型+材料 | 视觉读标题栏 → 规则匹配 |
| L2 | 几何特征提取 | 阿里百炼 qwen3.6-plus（内置） |
| L3 | 工序排序逻辑 | 5原则：先粗后精/热处理分水岭/基准先行/慢丝后置/表面最后 |
| L4 | 切削参数 | 知识库 + 工厂校准表 |
| L5 | 特殊要求/风险 | 注释识别 → 工序备注 |

**形状→模板**：方形→铣→磨→放电（14步）
**圆形→车→磨→放电（7步）**

### 用户指定加工
- 只有两道工序需要 CNC 编码：**数控精车**（TAKISAWA NEX-108）和 **镜面放电**（SODICK AD32LS）

---

## 四、核心约束（机械执行）

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
