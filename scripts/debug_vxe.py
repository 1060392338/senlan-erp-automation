"""调试VXE表格：确认弹窗内VXE的DOM结构和data绑定"""
import json, sys, time, os
from DrissionPage import ChromiumPage

# 连接已有Chrome
page = ChromiumPage(addr_or_opts=9222)

# 登录
page.get("http://112.74.35.30/")
time.sleep(3)

if 'Login' in page.url:
    # 登录
    u = page.ele('@name=username')
    if u: u.input("472")
    p = page.ele('@name=password')
    if p: p.input("123456")
    btn = page.ele('t:span@@class=login') or page.ele('@type=submit')
    if btn: btn.click()
    time.sleep(5)

# 导航到计划工艺
page.get("http://112.74.35.30/#/Craftwork/steel_craftworkList/0210")
time.sleep(5)

# 搜索生产单
inp = page.ele('@placeholder=请输入生产单号')
if inp:
    inp.input("W20126051401")
    time.sleep(0.5)
    q = page.ele('@@text()=查询')
    if q: q.click()
    time.sleep(3)

# 全选
cb = page.ele('.vxe-cell--checkbox')
if cb:
    cb.click()
    time.sleep(1)

# 打开工艺管理
gm = page.ele('@@text()=工艺管理')
if gm:
    gm.click()
    time.sleep(5)

# === 分析弹窗内VXE结构 ===
info = page.run_js("""
let dialog = document.querySelector('.el-dialog');
if (!dialog) return {error: 'no_dialog'};

let result = {};

// 1. Find vxe-grid inside dialog
let grid = dialog.querySelector('.vxe-grid');
result.has_grid = !!grid;
if (!grid) return result;

// 2. Check __vue__
let vm = grid.__vue__;
result.has_vue = !!vm;
if (vm) {
    result.has_fullData = Array.isArray(vm.fullData);
    result.fullData_len = (vm.fullData || []).length;
    result.has_tableData = Array.isArray(vm.tableData);
    result.tableData_len = (vm.tableData || []).length;
    
    // Try other common VXE data properties
    Object.keys(vm).forEach(k => {
        if (k.includes('data') || k.includes('Data') || k.includes('record') || k.includes('Row')) {
            let v = vm[k];
            if (Array.isArray(v)) result['prop_' + k] = v.length;
        }
    });
}

// 3. Check DOM rows
let bodyTable = dialog.querySelector('.vxe-table--body-wrapper table');
result.has_body_table = !!bodyTable;
if (bodyTable) {
    let rows = bodyTable.querySelectorAll('.vxe-body--row');
    result.dom_rows = rows.length;
    
    // Check each row's cells
    let firstRow = rows[0];
    if (firstRow) {
        let cells = firstRow.querySelectorAll('td');
        result.cells_per_row = cells.length;
        result.cell_classes = [];
        cells.forEach((c, i) => {
            result.cell_classes.push(c.className);
        });
    }
}

// 4. Check header columns
let headerTable = dialog.querySelector('.vxe-table--header-wrapper table');
result.has_header_table = !!headerTable;
if (headerTable) {
    let headers = headerTable.querySelectorAll('th');
    result.header_count = headers.length;
    let headerInfo = [];
    headers.forEach((th, i) => {
        let text = (th.querySelector('.vxe-cell--title') || {}).textContent || '';
        let field = th.getAttribute('data-field') || '';
        headerInfo.push({idx: i, field: field, title: text.trim()});
    });
    result.headers = headerInfo;
}

// 5. Check for vxe-input or other edit controls
let inputs = dialog.querySelectorAll('.vxe-input, vxe-input, input, select');
result.edit_inputs = inputs.length;
result.edit_types = [];
inputs.forEach(el => {
    let tag = el.tagName;
    let type = el.getAttribute('type') || el.className;
    result.edit_types.push(tag + ':' + type);
});

// 6. Check popover/select
let popovers = dialog.querySelectorAll('.vxe-select--panel, .el-scrollbar, .vxe-table--tooltip-wrapper, .el-popover, .el-select-dropdown');
result.popovers = popovers.length;

return JSON.stringify(result, null, 2);
""")

print("=== VXE 弹窗结构 ===")
print(info)
print()
print(f"URL: {page.url}")

# 试试双击第一个行的工序单元格
click_test = page.run_js("""
let dialog = document.querySelector('.el-dialog');
let bodyTable = dialog.querySelector('.vxe-table--body-wrapper table');
let firstRow = bodyTable.querySelector('.vxe-body--row');
let cells = firstRow.querySelectorAll('td');

// Find the table_type column (first data column)
let info = [];
cells.forEach((c, i) => {
    let text = (c.textContent || '').trim();
    info.push({idx: i, text: text.substring(0,50), class: c.className});
});

// Double-click the first editable cell
let targetCell = cells[1] || cells[0];  // skip row-number if any
if (targetCell) {
    targetCell.dispatchEvent(new MouseEvent('dblclick', {bubbles: true, detail: 2}));
}

return JSON.stringify(info);
""")
print(f"Cells: {click_test}")
time.sleep(2)

# 看双击后有没有输入控件出现
after = page.run_js("""
let dialog = document.querySelector('.el-dialog');
let inputs = dialog.querySelectorAll('input, select, .vxe-input--inner');
return 'inputs_after_dblclick: ' + inputs.length + ' types: ' + Array.from(inputs).slice(0,5).map(i => i.tagName + '.' + (i.className || '')).join(', ');
""")
print(after)

# 退出
page.quit()
