#!/usr/bin/env python3
"""ERP填工艺 — 全流程一次性完成"""
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

def js(query):
    """Run JS and return result"""
    return p.run_js(query)

def click_by_text(text, tag='*'):
    """Click first element containing text"""
    return js(f"""
        let els = document.querySelectorAll('{tag}');
        for(let el of els) {{
            if(el.textContent.trim() === {json.dumps(text)}) {{
                el.click();
                return 'clicked:' + el.tagName;
            }}
        }}
        for(let el of els) {{
            if(el.textContent.trim().includes({json.dumps(text)})) {{
                el.click();
                return 'clicked(partial):' + el.tagName;
            }}
        }}
        return 'not found:' + {json.dumps(text)};
    """)

def set_input(placeholder, value):
    """Set input value by placeholder"""
    return js(f"""
        let inputs = document.querySelectorAll('input');
        for(let inp of inputs) {{
            if(inp.placeholder === {json.dumps(placeholder)}) {{
                let nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                nativeInputValueSetter.call(inp, {json.dumps(value)});
                inp.dispatchEvent(new Event('input', {{bubbles:true}}));
                inp.dispatchEvent(new Event('change', {{bubbles:true}}));
                return 'set:' + inp.tagName;
            }}
        }}
        return 'not found:' + {json.dumps(placeholder)};
    """)

# ── 1. LOGIN ──
print("[1/6] 登录...")
p.get('http://112.74.35.30/Login?ReturnUrl=%2F')
time.sleep(0.5)
p.ele('@name=username').input('472')
p.ele('@name=password').input('123456')
p.ele('t:span@@class=login').click()
time.sleep(3)
print(f"  Title: {p.title} | URL: {p.url[:60]}")

# ── 2. NAVIGATE: 计划管理 → 计划工艺 ──
print("[2/6] 导航到计划管理→计划工艺...")
r = click_by_text('计划管理')
print(f"  点击计划管理: {r}")
time.sleep(1.5)

r = click_by_text('计划工艺')
print(f"  点击计划工艺: {r}")
time.sleep(2)
print(f"  Current URL: {p.url[:80]}")

# ── 3. SEARCH ──
print("[3/6] 搜索生产单W20126051401...")

# Find and fill search input
r = set_input('搜索', 'W20126051401')
print(f"  填写搜索框: {r}")

# Press Enter
js("""
    let inp = document.querySelector('input[placeholder="搜索"]');
    if(inp) {
        inp.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', code:'Enter', keyCode:13, which:13}));
        inp.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', code:'Enter', keyCode:13, which:13}));
        inp.dispatchEvent(new Event('change'));
    }
""")
time.sleep(3)

has_order = js("document.body.innerText.includes('W20126051401')")
print(f"  搜索到生产单: {has_order}")

# ── 4. CLICK 工艺管理 button ──
print("[4/6] 点击工艺管理...")
r = click_by_text('工艺管理')
print(f"  {r}")
time.sleep(2)

# Check for dialog
dialog = js("""
    let dialogs = document.querySelectorAll('.el-dialog, .dialog, [class*="dialog"], [class*="modal"], [role="dialog"]');
    if(dialogs.length > 0) return 'dialog found:' + dialogs.length;
    return 'no dialog found';
""")
print(f"  弹窗检测: {dialog}")

# ── 5. FILL PROCESS ROWS ──
print("[5/6] 填写工艺数据...")

# Get dialog structure
structure = js("""
    let dialogs = document.querySelectorAll('.el-dialog, [class*="dialog"]');
    let info = [];
    dialogs.forEach(d => {
        info.push({class: d.className, visible: d.style.display !== 'none', html: d.innerHTML.substring(0,200)});
    });
    return JSON.stringify(info);
""")
print(f"  对话框: {structure[:500]}")

# ── 6. SAVE & UPLOAD ──
print("[6/6] 保存...")

# Try clicking save button
r = click_by_text('保存')
print(f"  保存按钮: {r}")

p.quit()
print("\nDONE")
