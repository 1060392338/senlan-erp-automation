#!/usr/bin/env python3
"""测试编辑VXE表格单元格"""
import time, sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from DrissionPage import ChromiumPage, ChromiumOptions

co = ChromiumOptions()
co.set_user_data_path('/tmp/senlan_chrome_472')
co.set_argument('--remote-allow-origins=*')
co.set_argument('--no-sandbox')
co.set_argument('--window-size=1920,1080')
co.set_timeouts(base=8, page_load=10, script=5)
p = ChromiumPage(co)

p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
time.sleep(0.5)
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
time.sleep(3)
p.run_js("window.location.hash = '#/Craftwork/steel_craftworkList/0210'")
time.sleep(4)

# Search
p.run_js("""
let inp = document.querySelector('input[placeholder="请输入生产单号"]');
if(inp) {
    let ns = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    ns.call(inp, 'W20126051401');
    inp.dispatchEvent(new Event('input', {bubbles:true}));
    inp.dispatchEvent(new Event('change', {bubbles:true}));
}
let btns = document.querySelectorAll('button');
for(let btn of btns) {
    for(let span of btn.querySelectorAll('span')) {
        if(span.textContent.trim() === '查询') { btn.click(); return; }
    }
}
""")
time.sleep(3)

# Open 工艺管理 dialog
p.run_js("""
let rows = document.querySelectorAll('.vxe-body--row');
for(let row of rows) {
    if(row.textContent.includes('W20126051401')) {
        let checkbox = row.querySelector('.vxe-cell--checkbox');
        if(checkbox) checkbox.click();
        break;
    }
}
""")
time.sleep(1)
p.run_js("""
let btns = document.querySelectorAll('button');
for(let btn of btns) {
    for(let span of btn.querySelectorAll('span')) {
        if(span.textContent.trim() === '工艺管理') { btn.click(); return; }
    }
}
""")
time.sleep(4)

# Test 1: Try to find VXE grid instance
test1 = p.run_js("""
// Try to access VXE table instance
let grid = document.querySelector('.vxe-grid');
if(grid && grid.__vue__) {
    return 'vue found on grid';
}
// Try to find the grid's proxy/instance
let tables = document.querySelectorAll('.vxe-table');
let info = [];
tables.forEach(t => {
    let xid = t.getAttribute('xid');
    info.push(xid);
});
return 'tables: ' + JSON.stringify(info);
""")
print("=== Test 1: VXE Instance ===")
print(test1)

# Test 2: Click on the 工序 cell (first row, 4th column - table_type)
test2 = p.run_js("""
let bodyWrapper = document.querySelector('.vxe-table--body-wrapper');
if(!bodyWrapper) return 'no body wrapper';
let firstBodyRow = bodyWrapper.querySelector('.vxe-body--row');
if(!firstBodyRow) return 'no body row';

// Find the 工序 cell (4th td, class table_type)
let cells = firstBodyRow.querySelectorAll('td');
let tableTypeCell = null;
cells.forEach(c => {
    if(c.classList.contains('table_type')) tableTypeCell = c;
});

if(!tableTypeCell) return 'no table_type cell found';
// Check classes
let cellClasses = tableTypeCell.className;
let cellHTML = tableTypeCell.innerHTML.substring(0, 200);
return 'classes: ' + cellClasses + '\\nhtml: ' + cellHTML;
""")
print("\n=== Test 2: 工序 Cell ===")
print(test2)

# Test 3: Click the 工序 cell and see what happens
test3 = p.run_js("""
let bodyWrapper = document.querySelector('.vxe-table--body-wrapper');
let firstBodyRow = bodyWrapper.querySelector('.vxe-body--row');
let cells = firstBodyRow.querySelectorAll('td');
let tableTypeCell = null;
cells.forEach(c => {
    if(c.classList.contains('table_type')) tableTypeCell = c;
});
if(!tableTypeCell) return 'no cell';
// First double-click to enter edit mode
// VXE uses dblclick to edit
tableTypeCell.dispatchEvent(new MouseEvent('dblclick', {bubbles: true, detail: 2}));
return 'dblclicked';
""")
time.sleep(2)

# Check what appeared
test4 = p.run_js("""
let bodyWrapper = document.querySelector('.vxe-table--body-wrapper');
let firstBodyRow = bodyWrapper.querySelector('.vxe-body--row');
let cells = firstBodyRow.querySelectorAll('td');
let tableTypeCell = null;
cells.forEach(c => {
    if(c.classList.contains('table_type')) tableTypeCell = c;
});
if(!tableTypeCell) return 'no cell';
return 'after dblclick html: ' + tableTypeCell.innerHTML.substring(0, 1000);
""")
print("\n=== Test 3: After dblclick ===")
print(test4)

# Test 4: Try click (single) instead
time.sleep(1)
test5 = p.run_js("""
let bodyWrapper = document.querySelector('.vxe-table--body-wrapper');
let firstBodyRow = bodyWrapper.querySelector('.vxe-body--row');
let cells = firstBodyRow.querySelectorAll('td');
let tableTypeCell = null;
cells.forEach(c => {
    if(c.classList.contains('table_type')) tableTypeCell = c;
});
if(!tableTypeCell) return 'no cell';
// Click on the cell content area
let cellDiv = tableTypeCell.querySelector('.vxe-cell');
if(cellDiv) cellDiv.click();
else tableTypeCell.click();
return 'clicked';
""")
time.sleep(2)
test6 = p.run_js("""
let bodyWrapper = document.querySelector('.vxe-table--body-wrapper');
let firstBodyRow = bodyWrapper.querySelector('.vxe-body--row');
let cells = firstBodyRow.querySelectorAll('td');
let tableTypeCell = null;
cells.forEach(c => {
    if(c.classList.contains('table_type')) tableTypeCell = c;
});
if(!tableTypeCell) return 'no cell';
return 'after click html: ' + tableTypeCell.innerHTML.substring(0, 1000);
""")
print("\n=== Test 4: After single click ===")
print(test6)

# Test 5: Check for any popover/popup that appeared globally
test7 = p.run_js("""
let popups = document.querySelectorAll('.el-popover, .vxe-table--edit-wrapper, [class*=edit], [class*=editable], [class*=popup]');
let info = [];
popups.forEach(p => {
    if(window.getComputedStyle(p).display !== 'none') {
        info.push({
            class: p.className.substring(0, 60),
            html: p.innerHTML.substring(0, 200),
            text: p.textContent.trim().substring(0, 100)
        });
    }
});
return JSON.stringify(info);
""")
print("\n=== Test 5: Popups after click ===")
print(test7[:1000])

p.quit()
print("\nDONE")
