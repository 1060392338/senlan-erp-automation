# HANDOFF — 森蓝ERP自动化全流程交接

## 项目状态：V5.5 ✅ 完整跑通

### 已验证流程
- **单零件模式**: `--drawing /path/to/pdf --prod-no W20126051401`
- **多零件模式**: `--drawings-dir /Volumes/m2/erp/ --prod-no C03026051501`
- 2026-05-16 实测 C03026051501 两个零件（001 未发送、002 已发送）全部填入保存成功

### 关键设计决策（5+轮皇帝纠正后的最终方案）

1. **文件名驱动匹配** — `(prod_no, part_no)` 从文件名 `{prod_no}-{part_no}.pdf` 动态提取
2. **零件号无格式限制** — 不硬编码 001/002，支持任意后缀
3. **独立浏览器** — 每个零件保存后关闭浏览器，避免弹窗遮罩残留
4. **跨标签搜索** — 每个零件遍历未发送→BOM清单→已发送三个标签
5. **工序排序修正** — 打孔优先级 25（放到热处理之后）
6. **工艺要求细化** — remark/task 重写，包含详细特征参数

### 修改过的文件
- `scripts/fill_by_vision.py` — 完整重构（501→678行）
- `workflows/erp_process/process_reasoning.py` — 排序/remark/task/qty安全
- `templates/prompts/vision/analyze.j2` — 提示词改善
- `services/llm_client.py` — 已安装PyMuPDF（无需改动代码）

### 不动过的文件
- `workflows/erp_process/agents/` — 视觉/CNC/审查 Agent 未改
- `config/dropdown_options.py` — 工序选项未改
- `services/playwright_erp.py` — 未改（但 fill_by_vision 直接操作 page）

### 性能
视觉API ≈ 3min/张（瓶颈），浏览器 ≈ 10-15s/零件。
如果要加速视觉，可用 qwen-vl-max-lite 代替 qwen-vl-max（可能更快但精度略低）。

### 下一步
- 配置 DeepSeek API key 后重新跑 CNC 编程流水线
- 飞书消息返回已完成
