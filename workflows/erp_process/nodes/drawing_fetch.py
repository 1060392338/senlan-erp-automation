"""节点: 飞书共享文件夹匹配图纸

流程：
  1. 从 state 获取 new_orders 列表，取当前待处理的订单
  2. 访问飞书共享文档文件夹 (folder_token=CoP8f0nYBlSmMudveyjcSyrKneg)
  3. 按生产单号 (prod_no) 查找匹配的图纸文件
  4. 匹配成功 → 下载到本地 → 中断等待确认
  5. 匹配失败 → 飞书消息通知用户 → 中断等待
"""

import json
import logging
import os
import re
from typing import Optional
import requests
import tempfile
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState, Checkpoint

log = logging.getLogger("node.drawing_fetch")

# 飞书云空间 API 配置
FEISHU_DRIVE_BASE = "https://open.feishu.cn/open-apis/drive/v1"
FOLDER_TOKEN = "CoP8f0nYBlSmMudveyjcSyrKneg"  # 森蓝ERP图纸共享文件夹


def _get_feishu_token(ctx) -> Optional[str]:
    """从上下文中获取飞书 tenant_access_token"""
    # 优先从 tenant_config 获取
    feishu_config = ctx.tenant_config.get("feishu", {})
    token = feishu_config.get("tenant_access_token") or feishu_config.get("access_token")
    if token:
        return token

    # 从全局配置获取 app_id / app_secret 并申请 token
    app_id = ctx.global_config.get("feishu", {}).get("app_id", "")
    app_secret = ctx.global_config.get("feishu", {}).get("app_secret", "")
    if app_id and app_secret:
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": app_id, "app_secret": app_secret},
                timeout=10,
            )
            data = resp.json()
            return data.get("tenant_access_token")
        except Exception as e:
            log.warning(f"获取飞书 token 失败: {e}")

    log.warning("无法获取飞书 token，请检查 feishu 配置")
    return None


def _list_folder_files(token: str) -> list[dict]:
    """列出飞书共享文件夹中的所有文件"""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    all_files = []
    page_token = None
    while True:
        params = {
            "page_size": 50,
            "folder_token": FOLDER_TOKEN,
            "types": "file",
        }
        if page_token:
            params["page_token"] = page_token

        try:
            resp = requests.get(
                f"{FEISHU_DRIVE_BASE}/files",
                headers=headers,
                params=params,
                timeout=15,
            )
            data = resp.json()
            if data.get("code") != 0:
                log.warning(f"飞书列表文件失败: {data.get('msg', '')}")
                break

            result = data.get("data", {})
            files = result.get("files", [])
            all_files.extend(files)
            log.info(f"拉取到 {len(files)} 个文件")

            if not result.get("has_more"):
                break
            page_token = result.get("page_token")

        except Exception as e:
            log.warning(f"飞书 API 请求失败: {e}")
            break

    return all_files


def _match_drawing(files: list, prod_no: str) -> Optional[dict]:
    """按生产单号匹配图纸文件（文件名包含 prod_no）"""
    for f in files:
        name = f.get("name", "")
        # 文件名匹配：精确匹配或包含生产单号
        if prod_no in name:
            log.info(f"图纸匹配成功: {name} (prod_no={prod_no})")
            return f

    log.info(f"未找到匹配 {prod_no} 的图纸文件")
    return None


def _download_file(token: str, file_token: str) -> Optional[bytes]:
    """下载飞书文件"""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(
            f"{FEISHU_DRIVE_BASE}/medias/{file_token}/download",
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.content
        log.warning(f"下载文件失败: HTTP {resp.status_code}")
    except Exception as e:
        log.warning(f"下载文件异常: {e}")
    return None


def node_fetch_drawing(state: ERPState, config: RunnableConfig, services: Optional[dict] = None) -> dict:
    """飞书文件夹匹配图纸"""
    ctx = config["configurable"]["ctx"]
    input_data = state.get("input", {})
    new_orders = state.get("new_orders", [])
    pending_idx = state.get("pending_order_idx", 0)

    # ── 0. 确定当前要处理的订单（优先使用 input.prod_no） ──
    prod_no = input_data.get("prod_no", "")
    if not prod_no and pending_idx < len(new_orders):
        prod_no = new_orders[pending_idx].get("prod_no", "")
    if not prod_no:
        log.info("无生产单号，跳过图纸匹配")
        return {"checkpoint": Checkpoint.DRAWING_FETCHED}

    # ── 0.5. 检查是否已有本地图纸路径（跳过飞书） ──
    if input_data.get("drawing_path"):
        drawing_path = input_data["drawing_path"]
        if os.path.exists(drawing_path):
            log.info(f"使用输入中指定的本地图纸路径: {drawing_path}")
            return {
                "prod_no": prod_no,
                "drawing_url": None,
                "drawing_local_path": drawing_path,
                "drawing_matched": True,
                "checkpoint": Checkpoint.DRAWING_FETCHED,
            }

    # ── 1. 确定当前要处理的订单 ──
    if pending_idx >= len(new_orders):
        log.info("所有订单已处理完毕")
        return {"checkpoint": Checkpoint.DRAWING_FETCHED}

    current_order = new_orders[pending_idx]
    prod_no = current_order.get("prod_no", "")
    log.info(f"处理订单 [{pending_idx + 1}/{len(new_orders)}]: prod_no={prod_no}")

    # ── 2. 获取飞书 token ──
    feishu_token = _get_feishu_token(ctx)
    if not feishu_token:
        log.warning("无法连接飞书，跳过图纸匹配")
        return {
            "prod_no": prod_no,
            "drawing_url": None,
            "drawing_local_path": None,
            "drawing_matched": False,
            "checkpoint": Checkpoint.DRAWING_FETCHED,
            "errors": ["飞书 token 获取失败"],
        }

    # ── 3. 列出文件夹文件，按生产单号匹配 ──
    files = _list_folder_files(feishu_token)
    matched_file = _match_drawing(files, prod_no)

    if not matched_file:
        # 匹配失败 → 通知用户
        log.info(f"未找到 {prod_no} 的图纸，发送飞书通知")
        if ctx.notifier:
            try:
                msg = (
                    f"⚠️ **图纸匹配失败**\\n\\n"
                    f"**生产单号**: {prod_no}\\n"
                    f"**当前进度**: {pending_idx + 1}/{len(new_orders)}\\n\\n"
                    f"在飞书共享文件夹中未找到匹配的图纸文件。\\n"
                    f"请将图纸上传到飞书文件夹，文件名需包含生产单号 {prod_no}。\\n"
                    f"上传后回复「继续」重试。"
                )
                ctx.notifier.send_text(msg)
            except Exception as e:
                log.warning(f"飞书通知失败: {e}")

        return {
            "prod_no": prod_no,
            "drawing_url": None,
            "drawing_local_path": None,
            "drawing_matched": False,
            "checkpoint": Checkpoint.DRAWING_FETCHED,
        }

    # ── 4. 下载图纸到本地 ──
    file_token = matched_file.get("file_token", matched_file.get("token", ""))
    file_name = matched_file.get("name", f"{prod_no}.jpg")
    file_data = _download_file(feishu_token, file_token)

    if file_data:
        # 保存到临时目录
        temp_dir = tempfile.mkdtemp(prefix="senlan_drawing_")
        ext = os.path.splitext(file_name)[1] or ".jpg"
        local_path = os.path.join(temp_dir, f"{prod_no}{ext}")
        with open(local_path, "wb") as f:
            f.write(file_data)
        log.info(f"图纸已下载: {local_path} ({len(file_data)} bytes)")
    else:
        local_path = None
        log.warning("图纸下载失败")

    # ── 5. 记录图纸URL（飞书文件链接） ──
    feishu_file_url = f"https://my.feishu.cn/drive/file/{file_token}" if file_token else None

    log.info(f"图纸匹配成功: prod_no={prod_no}, file={file_name}")
    return {
        "prod_no": prod_no,
        "drawing_url": feishu_file_url,
        "drawing_local_path": local_path,
        "drawing_matched": True,
        "checkpoint": Checkpoint.DRAWING_FETCHED,
    }
