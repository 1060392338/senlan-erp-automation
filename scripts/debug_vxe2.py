"""调试VXE弹窗结构 - 查dialog内表格是vxe-table还是vxe-grid"""
import time
from DrissionPage import ChromiumPage

page = ChromiumPage(addr_or_opts=9222)

page.get("http://112.74.35.30/")
time.sleep(3)
if 'Login' in page.url:
    u = page.ele('@name=username')
    if u: u.input("472")
    p = page.ele('@name=password')
    if p: p.input("123456")
    page.ele('t:span@@class=login').click()
    time.sleep(5)

page.get("http://112.74.35.30/#/Craftwork/steel_craftworkList/0210")
time.sleep(5)

# Search
inp = page.ele('@placeholder=请输入生产单号')
if inp: inp.input("W20126051401"); time.sleep(0.5)
page.ele('@@text()=查询').click(); time.sleep(3)

# Checkbox
page.ele('.vxe-cell--checkbox').click(); time.sleep(1)

# Open dialog
page.ele('@@text()=工艺管理').click(); time.sleep(5)

# Deep dive into dialog structure
info = page.run_js("""
let dialog = document.querySelector('.el-dialog');
if (!dialog) return {error: 'no dialog'};

let r = {};

// Dialog structure
r.dialog_classes = dialog.className;
r.dialog_children = dialog.children.length;

// Check the content area
let body = dialog.querySelector('.el-dialog__body');
if (body) {
    r.body_children = body.children.length;
    r.body_html_short = body.innerHTML.substring(0, 300);
    
    // Check for vxe-table or vxe-grid
    let vxeTable = body.querySelector('vxe-table');
    let vxeGrid = body.querySelector('vxe-grid');
    let hasVxe = body.querySelector('[class*=vxe]');
    r.has_vxe_table = !!vxeTable;
    r.has_vxe_grid = !!vxeGrid;
    r.has_vxe_class = !!hasVxe;
    
    // Check all elements with vxe in class
    let allVxe = body.querySelectorAll('[class*=vxe]');
    r.vxe_elements = [];
    allVxe.forEach(el => {
        let info = {
            tag: el.tagName,
            class: el.className.substring(0,60),
            id: el.id || '',
        };
        if (el.__vue__) {
            info.has_vue = true;
            info.vue_keys = Object.keys(el.__vue__).filter(k => 
                k.includes('data') || k.includes('Data') || k.includes('insert') || k.includes('setCell')
            ).slice(0,10);
        }
        r.vxe_elements.push(info);
    });
    
    // Check tables
    let tables = body.querySelectorAll('table');
    r.tables = tables.length;
    tables.forEach((t, i) => {
        if (i === 0) r.first_table_classes = t.className.substring(0,80);
    });
    
    // Check body wrapper
    let wrapper = body.querySelector('.vxe-table--body-wrapper');
    r.has_body_wrapper = !!wrapper;
}

return JSON.stringify(r, null, 2);
""")

print("=== Dialog VXE Structure ===")
print(info)
page.quit()
