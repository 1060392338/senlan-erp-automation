# 架构约束（此处为 AI 不可违背的规则）

## 浏览器层

1. **端口 9222** — 与抖音音乐（9223）隔离，永不冲突
2. Chrome 启动参数必须包含 `--remote-allow-origins=*`（否则 CDP WebSocket 403）
3. `BrowserService.close()` 用 `page.quit()` 不能 `page.get("about:blank")`
4. DrissionPage 与 Chrome 147+ 的兼容性问题已由 `browser_service.py` 封装处理

## 并发层

1. **多Bot 完全隔离** — 每个 Bot 实例有独立 ServiceContainer、独立 Chrome 端口、独立 LangGraph 实例
2. `thread_id` 命名规范：`{bot}-{tenant}-{agent}-{run_id}`
3. 中断点仅在 Checkpoint.DRAWING_FETCHED(10) 和 CNC_GENERATED(20)

## 测试层

1. MagicMock 不抛异常 → DrissionPage 交互需 `isinstance` 守卫
2. 60 pass / 2 skip 是基线，新增代码不能降低通过率
3. 集成测试依赖 ERP + Chrome，本地跳过

## 安全层

1. 飞书 token 每 2h 过期（已自动刷新）
2. API Key 通过 `.env` 注入，不写死在 config.yaml
3. 密码通过 `${ERP_472_USERNAME}` 模板引用，不暴露明文

## 遗留问题（不许绕过，只能逐步修复）

1. ERP 页面选择器（`@name=customer` 等）猜的，联调时修正
2. 无集成测试
3. `_login.py` 和 `login.py` 重复（功能正常，未合并）
4. ERP 页面交互无基类抽象（3个文件重复元素查找模式）
