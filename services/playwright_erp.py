"""Playwright ERP 自动化 — 完整工艺填写+CNC回填

比 DrissionPage 优势：
- dblclick() 原生支持 VXE 编辑
- 下拉菜单 .el-select-dropdown 正确识别
- keyboard.type() 直接输入编辑值
- persistent context 自动保持登录态
"""

import json
import logging
import os
import time
from typing import Optional

log = logging.getLogger("playwright_erp")

ERP_BASE = "http://112.74.35.30"
USER_DATA_DIR = "data/chrome_data/playwright"

# 15道工艺工序
PROCESS_PLAN = [
    {"name": "铣床", "machine_hours": 2, "worker": "JINGDIAO铣床", "remark": "开粗;孔;牙"},
    {"name": "CNC 1", "machine_hours": 3, "worker": "JINGDIAO精雕", "remark": "开粗"},
    {"name": "热处理", "machine_hours": 0, "worker": "外协", "remark": "58-63HRC"},
    {"name": "快丝", "machine_hours": 2, "worker": "快走丝", "remark": "开粗;外形"},
    {"name": "大水磨", "machine_hours": 3, "worker": "OKAMOTO Sam-450", "remark": "磨六面"},
    {"name": "检测", "machine_hours": 1, "worker": "ZEISS CMM", "remark": "外形/直角"},
    {"name": "小磨床", "machine_hours": 2, "worker": "HOTMAN", "remark": "调直角;外形"},
    {"name": "CNC 2", "machine_hours": 4, "worker": "JINGDIAO精雕", "remark": "精加工"},
    {"name": "小磨床", "machine_hours": 2, "worker": "HOTMAN", "remark": "调变形"},
    {"name": "慢丝", "machine_hours": 3, "worker": "慢走丝", "remark": "割精密孔"},
    {"name": "EDM", "machine_hours": 4, "worker": "SODICK AD32LS", "remark": "孔;槽镜面"},
    {"name": "抛光", "machine_hours": 2, "worker": "手工", "remark": "黄色面2000#"},
    {"name": "总检", "machine_hours": 1, "worker": "ZEISS CMM", "remark": "全尺寸"},
    {"name": "TiN涂层", "machine_hours": 0, "worker": "外协", "remark": "表面处理"},
    {"name": "注意事项", "machine_hours": 0, "worker": "", "remark": "利角—严禁倒角"},
]


class PlaywrightERP:
    """Playwright ERP 交互封装"""

    def __init__(self):
        self._pw = None
        self._context = None
        self._page = None

    def start(self):
        """启动 Playwright + ERP 浏览器"""
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,
            viewport={"width": 1920, "height": 1080},
            locale="zh-CN",
        )
        self._browser = self._context.browser  # 保存browser引用
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        log.info("Playwright ERP 浏览器已启动")
        return self._page

    @property
    def page(self):
        return self._page

    def login_if_needed(self):
        """检查登录态，需要则登录"""
        page = self._page
        page.goto(f"{ERP_BASE}/", timeout=15000)
        time.sleep(4)

        if page.locator('input[name="username"]').count() > 0:
            log.info("需要登录...")
            page.fill('input[name="username"]', os.environ.get("ERP_473_USERNAME", "472"))
            page.fill('input[name="password"]', os.environ.get("ERP_473_PASSWORD", "123456"))
            page.click("span.login")
            time.sleep(5)
            # 保存storage_state供后续使用
            self._context.storage_state(path="data/chrome_data/erp_auth.json")
            log.info("登录完成")
            return True
        log.info("已有登录态")
        return False

    def navigate_to_craft(self):
        """导航到计划工艺页面"""
        page = self._page
        page.goto(f"{ERP_BASE}/#/Craftwork/steel_craftworkList/0210",
                  wait_until="domcontentloaded", timeout=15000)
        time.sleep(5)

        # 如果还在登录页，补一次登录
        self.login_if_needed()

        # 再次导航
        page.goto(f"{ERP_BASE}/#/Craftwork/steel_craftworkList/0210",
                  wait_until="domcontentloaded", timeout=15000)
        time.sleep(5)

        found = page.locator('input[placeholder="请输入生产单号"]').count() > 0
        log.info(f"到达计划工艺页面: {found}")
        return found

    def search_order(self, prod_no: str):
        """搜索生产单号（遍历 BOM/未发送/已发送）"""
        page = self._page
        for tab_name in ["BOM清单", "未发送", "已发送"]:
            try:
                # 切换radio标签
                tab_btn = page.locator(f"label:has(.el-radio-button__inner:text(\"{tab_name}\"))")
                if tab_btn.count() > 0:
                    tab_btn.first.click()
                    time.sleep(1)

                # 输入生产单号
                inp = page.locator('input[placeholder="请输入生产单号"]')
                if inp.count() > 0:
                    inp.fill(prod_no)
                    time.sleep(0.3)

                # 点击查询
                page.locator('button:has-text("查询")').first.click()
                time.sleep(3)

                # 检查是否找到
                if page.locator(f"text={prod_no}").count() > 0:
                    log.info(f"在 {tab_name} 下找到 {prod_no}")
                    return True
            except Exception as e:
                log.warning(f"{tab_name} 标签异常: {e}")
        log.warning(f"未找到 {prod_no}")
        return False

    def open_process_dialog(self):
        """全选 → 打开工艺管理弹窗（全JS）"""
        page = self._page
        opened = page.evaluate("""
            () => {
                // 勾选表头checkbox
                let cb = document.querySelector('.vxe-header--row .vxe-cell--checkbox');
                if (cb) { cb.click(); }

                // 点工艺管理按钮
                setTimeout(() => {
                    let btns = document.querySelectorAll('button');
                    for (let btn of btns) {
                        if (btn.textContent.trim() === '工艺管理') {
                            btn.click(); break;
                        }
                    }
                }, 500);
                return 'clicked';
            }
        """)
        time.sleep(6)

        # 验证弹窗
        check = page.evaluate("""
            () => {
                let dialogs = document.querySelectorAll('.el-dialog');
                for (let d of dialogs) {
                    let t = (d.querySelector('.el-dialog__title') || {}).textContent || '';
                    if (t.trim() === '工艺管理') return 'dialog_open';
                }
                return 'not_found';
            }
        """)
        log.info(f"工艺管理弹窗: {check}")
        return 'dialog_open' in check

    def fill_process_rows(self, process_plan: list):
        """填充工艺 — 3步：删行 → +号加行 → 全JS设值"""
        page = self._page
        count = len(process_plan)
        log.info(f"填充 {count} 行工序...")

        # 1. 删光VXE所有行（JS）
        page.evaluate("""
            () => {
                let d = null;
                for (let d2 of document.querySelectorAll('.el-dialog')) {
                    let t = (d2.querySelector('.el-dialog__title') || {}).textContent || '';
                    if (t.trim() === '工艺管理') { d = d2; break; }
                }
                let vm = d.querySelector('.vxe-grid, .vxe-table')?.__vue__;
                if (!vm) return;
                if (typeof vm.removeAll === 'function') vm.removeAll();
                else {
                    let rows = vm.tableData || vm.fullData || [];
                    if (rows.length > 0 && typeof vm.remove === 'function') vm.remove(rows.slice());
                }
            }
        """)
        time.sleep(1)

        # 2. 用VXE insert插入带数据的行
        result = page.evaluate(f"""
            () => {{
                let d = null;
                for (let d2 of document.querySelectorAll('.el-dialog')) {{
                    let t = (d2.querySelector('.el-dialog__title') || {{}}).textContent || '';
                    if (t.trim() === '工艺管理') {{ d = d2; break; }}
                }}
                let vm = d.querySelector('.vxe-grid, .vxe-table')?.__vue__;
                if (!vm) return 'no_vue';

                let data = {json.dumps(process_plan)};
                let rows = data.map(d => ({{
                    table_type: d['name'],
                    machine: d['machine_hours'],
                    plan_worker: d['worker'],
                    remark: d['remark'],
                }}));

                if (typeof vm.insert === 'function') {{
                    vm.insert(rows);
                }} else if (Array.isArray(vm.tableData)) {{
                    vm.tableData.push(...rows);
                }}

                if (typeof vm.commitEdit === 'function') vm.commitEdit();
                if (typeof vm.refreshColumn === 'function') vm.refreshColumn();

                let final = (vm.tableData || vm.fullData || []).length;
                return 'vxe_insert_' + rows.length + '_tableData_' + final;
            }}
        """)
        time.sleep(2)
        log.info(f"  插入行: {result}")

        final_rows = page.locator(".vxe-body--row").count()
        log.info(f"  DOM行数: {final_rows}")

        time.sleep(1)
        log.info("工序填充完成")

    def save_dialog(self):
        """保存 — Playwright native click (force=True 穿透Vue遮挡层) + toast确认"""
        page = self._page
        save_btn = page.locator(
            '.el-dialog:has(.el-dialog__title:text("工艺管理")) '
            '.el-dialog__footer button.el-button--primary'
        ).first
        if save_btn.count() == 0:
            log.warning("保存: 未找到按钮")
            return False

        save_btn.click(force=True, timeout=5000)
        log.info("保存: 按钮已点击，等待确认...")
        time.sleep(2)

        for _ in range(10):
            toast = page.evaluate("""() => {
                let t = document.querySelector('.el-message--success');
                return t ? t.textContent.trim() : '';
            }""")
            if toast:
                log.info(f"保存: ✓ {toast}")
                return True
            time.sleep(1)

        log.warning("保存: 未检测到成功提示")
        return False

    def close(self):
        """关闭浏览器"""
        try:
            if self._context:
                try: self._context.close()
                except: pass
            if self._browser:
                try: self._browser.close()
                except: pass
            if self._pw:
                self._pw.stop()
        except Exception as e:
            log.warning(f"关闭异常: {e}")


# ── 独立入口 ──
def run_fill_process(prod_no: str = "W20126051401", process_plan: list = None):
    """完整流程：登录 → 导航 → 搜索 → 弹窗 → 填充 → 保存"""
    if process_plan is None:
        process_plan = PROCESS_PLAN

    erp = PlaywrightERP()
    try:
        erp.start()
        erp.login_if_needed()

        if not erp.navigate_to_craft():
            log.error("导航失败")
            return False

        if not erp.search_order(prod_no):
            log.warning("搜索未命中，尝试继续...")

        if not erp.open_process_dialog():
            log.error("弹窗失败")
            return False

        erp.fill_process_rows(process_plan)
        saved = erp.save_dialog()
        log.info(f"计划工艺保存: {saved}")
        return saved
    finally:
        erp.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    run_fill_process()
