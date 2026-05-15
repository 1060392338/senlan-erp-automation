"""节点: 获取图纸 + 飞书通知 Phase 1 完成"""

import logging
import os
from langchain_core.runnables import RunnableConfig
from workflows.erp_process.state import ERPState
from workflows.erp_process.state import Checkpoint

log = logging.getLogger("node.drawing_fetch")


def node_fetch_drawing(state: ERPState, config: RunnableConfig, services: dict | None = None) -> dict:
    """下载图纸 + 通知 Phase 1 完成"""
    ctx = config["configurable"]["ctx"]
    input_data = state.get("input", {})
    drawing_path = input_data.get("drawing_path", "")
    prod_no = state.get("prod_no", "")

    log.info(
        f"图纸获取: prod_no={prod_no}, "
        f"path={drawing_path or '(待上传)'}, session={ctx.session_id}"
    )

    # ── 1. 获取浏览器页面 ──
    page = None
    try:
        page = ctx.browser.get_page(session_id=ctx.session_id)
    except Exception as e:
        log.warning(f"获取浏览器页面失败: {e}")

    # ── 2. 如果已经提供了图纸路径，直接使用 ──
    final_drawing_path = drawing_path

    # ── 3. 尝试从 ERP 下载图纸 ──
    if page and prod_no:
        erp_url = ctx.erp_config.get("url", "http://112.74.35.30/")
        process_plan_url = f"{erp_url.rstrip('/')}/Plan/ProcessPlan?prod_no={prod_no}"

        try:
            log.info(f"导航到计划工艺页面搜索图纸: {process_plan_url}")
            page.get(process_plan_url)
            page.wait.load_complete(timeout=15)
            log.info("计划工艺页面加载完成，开始搜索附件/图纸区域")

            # ── 3a. 查找附件/上传区域 ──
            attachment_found = False
            try:
                # 尝试找到附件区域标题
                attachment_header = (
                    page.ele('@@text()=附件') or
                    page.ele('@@text()=图纸') or
                    page.ele('@@text()=文件') or
                    page.ele('@@text()=上传') or
                    page.ele('@@text()=2D图纸') or
                    page.ele('@@text()=下载')
                )
                if attachment_header:
                    log.info("找到附件/图纸区域标题")
                    attachment_found = True

                # 查找所有可能的下载链接
                download_links = page.eles('tag:a@@text()=下载') or page.eles('@@text()=下载')
                if not download_links:
                    download_links = page.eles('tag:a@@text()=查看') or page.eles('@@text()=查看')
                if not download_links:
                    download_links = page.eles('tag:img')  # 图片格式的图纸

                if download_links:
                    log.info(f"找到 {len(download_links)} 个可能的下载元素")
                    for link in download_links[:3]:  # 最多尝试前3个
                        try:
                            href = link.attr('href') or link.attr('src') or ''
                            if href and any(ext in href.lower() for ext in ['.pdf', '.png', '.jpg', '.jpeg', '.dwg', '.dxf']):
                                log.info(f"找到图纸附件链接: {href}")
                                attachment_found = True
                                break
                        except Exception:
                            continue
                else:
                    log.info("页面上未找到下载链接，图纸可能尚未上传")
            except Exception as e:
                log.warning(f"搜索附件区域失败: {e}")

            # ── 3b. 如果找到附件区域，尝试下载 ──
            if attachment_found and not final_drawing_path:
                # 创建下载目录
                download_dir = os.path.expanduser(
                    f"~/.hermes/senlan-automation/data/drawings/{ctx.run_id}"
                )
                os.makedirs(download_dir, exist_ok=True)

                try:
                    # 尝试点击下载链接
                    for link in download_links[:3]:
                        try:
                            href = link.attr('href') or ''
                            if href and not href.startswith('javascript'):
                                # 从链接获取文件名
                                filename = href.split('/')[-1].split('?')[0]
                                if not filename:
                                    filename = f"drawing_{prod_no}.pdf"
                                save_path = os.path.join(download_dir, filename)
                                # 记录图纸链接（实际下载可能需要额外配置）
                                final_drawing_path = href
                                log.info(f"找到图纸下载链接: {href}")
                                break
                        except Exception:
                            continue
                except Exception as e:
                    log.warning(f"下载图纸附件失败: {e}")

            # ── 3c. 检查页面是否包含图纸图片 ──
            if not final_drawing_path:
                try:
                    img_elements = page.eles('tag:img')
                    for img in img_elements:
                        src = img.attr('src') or ''
                        if any(kw in src.lower() for kw in ['drawing', 'dwg', '图纸', '2d']):
                            final_drawing_path = src
                            log.info(f"从页面图片元素找到图纸: {src}")
                            break
                except Exception as e:
                    log.warning(f"搜索页面图片失败: {e}")

        except Exception as e:
            log.warning(f"导航到计划工艺页面失败: {e}")
    else:
        if not page:
            log.warning("浏览器页面不可用，跳过 ERP 图纸下载")
        if not prod_no:
            log.warning("缺少生产单号，跳过 ERP 图纸下载")

    # ── 4. 如果依然没有图纸路径，记录提示 ──
    if not final_drawing_path:
        log.warning(
            "未能从 ERP 获取图纸，用户需手动上传。"
            "工作流将在 Phase 2 开始前暂停等待图纸。"
        )
        final_drawing_path = ""  # 清空，让后续节点处理

    # 飞书通知：Phase 1 完成（用户知道可以手动干预了）
    notify_on = ctx.tenant_config.get("notify_on", [])
    if ctx.notifier and "phase1_complete" in notify_on:
        try:
            ctx.notifier.notify_phase1_complete(ctx.display_name, prod_no)
        except Exception as e:
            log.warning(f"飞书通知失败: {e}")

    return {"drawing_url": final_drawing_path or "", "checkpoint": Checkpoint.DRAWING_FETCHED}
