#!/usr/bin/env python3
"""选行 → 点击工艺管理 → 查看弹窗"""
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
""")
time.sleep(0.5)

p.run_js("""
let btns = document.querySelectorAll('button');
for(let btn of btns) {
    let spans = btn.querySelectorAll('span');
    for(let span of spans) {
        if(span.textContent.trim() === '查询') {
            btn.click();
            return;
        }
    }
}
""")
time.sleep(3)

# APPROACH 1: Click the checkbox on the row
print("=== APPROACH 1: Click row checkbox ===")
r = p.run_js("""
let rows = document.querySelectorAll('.vxe-body--row');
for(let row of rows) {
    if(row.textContent.includes('W20126051401')) {
        // Find checkbox in column 1
        let checkbox = row.querySelector('.vxe-cell--checkbox');
        if(checkbox) { checkbox.click(); return 'checkbox clicked'; }
        // Try clicking the row itself
        row.click(); return 'row clicked';
    }
}
return 'row not found';
""")
print(f"  {r}")
time.sleep(1.5)

# Click 工艺管理 button
print("\n=== Click 工艺管理 ===")
r2 = p.run_js("""
let btns = document.querySelectorAll('button');
for(let btn of btns) {
    let spans = btn.querySelectorAll('span');
    for(let span of spans) {
        if(span.textContent.trim() === '工艺管理') {
            btn.click();
            return '工艺管理 clicked';
        }
    }
}
return 'not found';
""")
print(f"  {r2}")
time.sleep(2)

# Check for dialog
r3 = p.run_js("""
let dialogs = document.querySelectorAll('.el-dialog');
let info = [];
dialogs.forEach(d => {
    let display = window.getComputedStyle(d).display;
    let title = d.querySelector('.el-dialog__title');
    let body = d.querySelector('.el-dialog__body');
    let isVisible = display !== 'none' && !d.className.includes('__close');
    if(isVisible) {
        info.push({
            title: title ? title.textContent.trim() : '(no title)',
            bodyText: body ? body.textContent.trim().substring(0,300) : '(no body)',
            w: d.offsetWidth,
            h: d.offsetHeight
        });
    }
});
return JSON.stringify(info);
""")
print(f"  Dialogs: {r3[:500]}")

# APPROACH 2: Double click the row
if not r3 or r3 == '[]':
    print("\n=== APPROACH 2: Double click row ===")
    p.run_js("""
    let rows = document.querySelectorAll('.vxe-body--row');
    for(let row of rows) {
        if(row.textContent.includes('W20126051401')) {
            // Try dblclick on the production order number cell
            let cells = row.querySelectorAll('.vxe-cell');
            // Click the production order number cell (col 2)
            row.dispatchEvent(new MouseEvent('dblclick', {bubbles: true}));
            return 'row dblclicked';
        }
    }
    """)
    time.sleep(2)
    r4 = p.run_js("""
    let dialogs = document.querySelectorAll('.el-dialog');
    let info = [];
    dialogs.forEach(d => {
        let display = window.getComputedStyle(d).display;
        let title = d.querySelector('.el-dialog__title');
        if(display !== 'none') {
            info.push({
                title: title ? title.textContent.trim() : '(no title)',
                bodyPreview: (d.querySelector('.el-dialog__body') || {}).innerHTML?.substring(0,200) || ''
            });
        }
    });
    return JSON.stringify(info);
    """)
    print(f"  After dblclick: {r4[:500]}")

# APPROACH 3: Click the edit icon in column 0 (first column)
if not r3 or r3 == '[]':
    print("\n=== APPROACH 3: Click first column ===")
    p.run_js("""
    let rows = document.querySelectorAll('.vxe-body--row');
    for(let row of rows) {
        if(row.textContent.includes('W20126051401')) {
            let firstCell = row.querySelector('td');
            if(firstCell) {
                // Click on the ellipsis/settings icon
                let icon = firstCell.querySelector('.el-icon-s-tools') || firstCell.querySelector('i') || firstCell.querySelector('span');
                if(icon) { icon.click(); return 'icon clicked'; }
                firstCell.click(); return 'first cell clicked';
            }
        }
    }
    """)
    time.sleep(2)
    r5 = p.run_js("""
    let dialogs = document.querySelectorAll('.el-dialog, .el-drawer, [class*=popup], [class*=popover]');
    let info = [];
    dialogs.forEach(d => {
        if(window.getComputedStyle(d).display !== 'none') {
            info.push({
                class: d.className.substring(0,60),
                text: (d.textContent || '').trim().substring(0,100)
            });
        }
    });
    return JSON.stringify(info);
    """)
    print(f"  After first col: {r5[:500]}")

# Finally, also try 临时工艺 button approach  
if not r3 or r3 == '[]':
    print("\n=== APPROACH 4: 临时工艺 ===")
    p.run_js("""
    let btns = document.querySelectorAll('button');
    for(let btn of btns) {
        let spans = btn.querySelectorAll('span');
        for(let span of spans) {
            if(span.textContent.trim() === '临时工艺') {
                btn.click(); return '临时工艺 clicked';
            }
        }
    }
    """)
    time.sleep(2)
    r6 = p.run_js("""
    let dialogs = document.querySelectorAll('.el-dialog');
    let info = [];
    dialogs.forEach(d => {
        if(window.getComputedStyle(d).display !== 'none') {
            info.push({
                title: (d.querySelector('.el-dialog__title') || {}).textContent || '',
                bodyPreview: (d.querySelector('.el-dialog__body') || {}).innerHTML?.substring(0,200) || ''
            });
        }
    });
    return JSON.stringify(info);
    """)
    print(f"  临时工艺 dialogs: {r6[:500]}")

p.quit()
print("\nDONE")
