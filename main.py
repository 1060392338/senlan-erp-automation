"""
森蓝精密 · ERP 工艺自动化 — 入口

多 Bot 架构：
  每个 Bot 实例 = 独立 ERPProcessAgent + ServiceContainer
  --bot-id 参数区分不同 Bot，加载对应配置

用法:
    # 全新运行
    python main.py --bot bot_a --tenant senlan_472 --agent erp_process_agent \
      --input '{"customer":"客户X","part_name":"Cutting blade","qty":2}'

    # 断点恢复 + 用户反馈
    python main.py --bot bot_a --resume --tenant senlan_472 --agent erp_process_agent \
      --run-id a1b2c3d4 --message "图纸在桌面上，用默认参数就行"

    # 查看信息
    python main.py --list
"""

import argparse
import json
import logging
import os
import re
import sys
import uuid
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from agents.supervisor import SupervisorAgent
from services.service_container import ServiceContainer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")


def load_env(env_path: str = ".env"):
    """加载 .env 文件到环境变量"""
    p = Path(env_path)
    if not p.exists():
        log.warning(f"{env_path} 不存在，从系统环境变量读取")
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
    log.info(f"{env_path} 已加载")


def load_config(config_path: str = "config.yaml") -> dict:
    """加载 YAML 配置，解析环境变量模板 ${VAR}"""
    import yaml
    p = Path(config_path)
    if not p.exists():
        log.warning("config.yaml 不存在")
        return {}
    raw = p.read_text(encoding="utf-8")

    def _resolve_env(match):
        var = match.group(1)
        default = match.group(2)
        return os.getenv(var, default) if default else os.getenv(var, "")

    raw = re.sub(r"\$\{(\w+)(?::([^}]*))?\}", _resolve_env, raw)
    config = yaml.safe_load(raw)
    log.info(f"配置加载: {list(config.keys()) if config else '空'}")
    return config or {}


def find_tenant(config: dict, tenant_id: str) -> Optional[dict]:
    for t in config.get("tenants", []):
        if t.get("id") == tenant_id:
            return t
    return None


def get_bot_services(config: dict, bot_id: str) -> ServiceContainer:
    """
    根据 bot_id 创建独立的 ServiceContainer。
    多 Bot 场景：Bot A / Bot B 各自独立服务实例。
    """
    bot_cfg = config.get("bots", {}).get(bot_id, {})
    services_cfg = config.get("services", {})

    # 合并 bot 级和全局级 service 配置
    merged = dict(services_cfg)
    if bot_cfg.get("services"):
        for k, v in bot_cfg["services"].items():
            if k in merged:
                merged[k].update(v) if isinstance(v, dict) else v
            else:
                merged[k] = v

    container = ServiceContainer({"services": merged})
    log.info(f"Bot '{bot_id}' 服务容器已创建: {container.list()}")
    return container


def main():
    parser = argparse.ArgumentParser(description="森蓝精密 ERP 工艺自动化")
    parser.add_argument("--bot", default="default", help="Bot ID，如 bot_a / bot_b")
    parser.add_argument("--tenant", default=None, help="租户 ID, e.g. senlan_472")
    parser.add_argument("--agent", default=None, help="工作流 Agent 名称")
    parser.add_argument("--input", default="{}", help="输入数据 JSON")
    parser.add_argument("--run-id", default=None, help="运行 ID")
    parser.add_argument("--resume", action="store_true", help="从断点恢复")
    parser.add_argument("--message", default=None, help="多轮对话：用户在中断点输入的回复")
    parser.add_argument("--list", action="store_true", help="列出租户和工作流")
    parser.add_argument("--user-id", default="default", help="用户 ID（多用户隔离）")
    args = parser.parse_args()

    load_env()
    config = load_config()

    # ── 列出信息 ──
    if args.list:
        tenants = config.get("tenants", [])
        print(f"租户 ({len(tenants)}):")
        for t in tenants:
            print(f"  {t['id']}: {t.get('display_name','')}")
        print()
        bots = config.get("bots", {})
        print(f"Bot ({len(bots)}):")
        for bid, bcfg in bots.items():
            print(f"  {bid}: tenant={bcfg.get('tenant','')}")
        print()
        supervisor = SupervisorAgent()
        print(f"工作流 ({len(supervisor.agents)}):")
        for name, agent in supervisor.agents.items():
            print(f"  {name}: {agent.agent_description}")
        return

    # ── 创建 Bot 级 ServiceContainer ──
    services = get_bot_services(config, args.bot)

    # ── 查找租户 ──
    tenant_config = None
    if args.tenant:
        tenant_config = find_tenant(config, args.tenant)
        if not tenant_config:
            print(f"错误: 未找到租户 '{args.tenant}'")
            sys.exit(1)
        if not tenant_config.get("enabled", True):
            print(f"错误: 租户 '{args.tenant}' 已禁用")
            sys.exit(1)

    # ── 运行工作流 ──
    if args.agent:
        supervisor = SupervisorAgent()
        agent_cls = supervisor.agents.get(args.agent)
        if not agent_cls:
            print(f"错误: 未找到工作流 '{args.agent}'")
            sys.exit(1)

        # 创建 agent 实例（传入独立 ServiceContainer）
        agent = type(agent_cls)(services=services)
        agent.input_schema = agent_cls.input_schema  # 保留 schema

        # 生成/使用 run_id
        run_id = args.run_id or uuid.uuid4().hex[:12]
        thread_id = f"{args.bot}-{args.tenant or 'default'}-{args.agent}-{run_id}"

        input_data = json.loads(args.input)

        log.info(
            f"运行: bot={args.bot}, tenant={args.tenant}, agent={args.agent}, "
            f"run_id={run_id}, resume={args.resume}, user={args.user_id}"
        )

        # 执行
        result = agent.run(
            input_data,
            thread_id=thread_id,
            tenant_config=tenant_config,
            resume=args.resume,
            user_id=args.user_id,
            user_message=args.message,
        )

        log.info(f"完成: run_id={run_id}")
        print(f"\n💡 断点恢复命令:\n  python main.py --bot {args.bot} --resume --tenant {args.tenant} "
              f"--agent {args.agent} --run-id {run_id} --user-id {args.user_id}\n")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
