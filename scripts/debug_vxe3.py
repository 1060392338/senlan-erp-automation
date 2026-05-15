"""查VXE弹窗的Vue实例有哪些数据属性"""
import time
from DrissionPage import ChromiumPage

page = ChromiumPage(addr_or_opts=9222)
page.get("http://112.74.35.30/")
time.sleep(3)
if 'Login' in page.url:
    page.ele('@name=username').input("472")
    page.ele('@name=password').input("123456")
    page.ele('t:span@@class=login').click()
    time.sleep(5)

page.get("http://112.74.35.30/#/Craftwork/steel_craftworkList/0210")
time.sleep(5)
page.ele('@placeholder=请输入生产单号').input("W20126051401")
time.sleep(0.5)
page.ele('@@text()=查询').click()
time.sleep(3)
page.ele('.vxe-cell--checkbox').click()
time.sleep(1)
page.ele('@@text()=工艺管理').click()
time.sleep(5)

# Check VXE Vue instance data properties
info = page.run_js('''
let dialogs = document.querySelectorAll(".el-dialog");
let dialog = null;
for (let d of dialogs) {
    let title = (d.querySelector(".el-dialog__title") || {}).textContent || "";
    if (title.trim() === "工艺管理") { dialog = d; break; }
}
if (!dialog) return "no dialog";

let body = dialog.querySelector(".el-dialog__body");
let vxeEl = body.querySelector("[class*=vxe]");
if (!vxeEl) return "no vxe: " + body.innerHTML.substring(0, 200);

let vm = vxeEl.__vue__;
if (!vm) return "no vue";

// Get all data-related properties
let keys = Object.getOwnPropertyNames(vm);
let dataKeys = keys.filter(k => {
    let val = vm[k];
    return Array.isArray(val) || (typeof val === "object" && val !== null && !(val instanceof Element));
}).slice(0, 40);

let info = {};
dataKeys.forEach(k => {
    let val = vm[k];
    if (Array.isArray(val)) {
        info[k] = "Array[" + val.length + "]";
        if (val.length > 0) {
            info[k + "_first"] = JSON.stringify(val[0]).substring(0, 100);
        }
    } else if (typeof val === "function") {
        info[k] = "function";
    } else if (typeof val === "object" && val !== null) {
        info[k] = "Object(" + Object.keys(val).length + " keys)";
    } else {
        info[k] = typeof val + ": " + String(val).substring(0, 50);
    }
});

return JSON.stringify(info, null, 2);
''')
print("=== VXE Vue data properties ===")
print(info)

# Also check methods
methods = page.run_js('''
let dialog = null;
for (let d of document.querySelectorAll(".el-dialog")) {
    let title = (d.querySelector(".el-dialog__title") || {}).textContent || "";
    if (title.trim() === "工艺管理") { dialog = d; break; }
}
let vm = dialog.querySelector(".el-dialog__body [class*=vxe]").__vue__;
let methodKeys = Object.getOwnPropertyNames(vm.__proto__ || {});
let vxeMethods = methodKeys.filter(k => k.includes("insert") || k.includes("data") || k.includes("row") || k.includes("cell") || k.includes("edit"));
return JSON.stringify(vxeMethods);
''')
print(f"VXE methods: {methods}")
page.quit()
