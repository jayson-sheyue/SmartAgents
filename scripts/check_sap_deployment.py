"""Validate exported SAP cloud configuration without RPCs, writes or secret output."""
import os
import argparse
import asyncio
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values


def validate_sap_deployment(env: Mapping[str, str]) -> None:
    enabled = (env.get("SAP_COMPUTER_USE_ENABLED") or "false").strip().lower()
    if enabled not in {"true", "1", "yes", "false", "0", "no", ""}:
        raise ValueError("SAP_COMPUTER_USE_ENABLED 应设为 true 或 false")
    if enabled not in {"true", "1", "yes"}:
        return
    url = urlsplit((env.get("SAP_COMPUTER_USE_WORKER_URL") or "").strip())
    if (url.scheme != "https" or not url.hostname or url.hostname in {"localhost", "127.0.0.1", "::1"}
            or url.username or url.password or url.query or url.fragment):
        raise ValueError("云端 SAP 已启用，但 SAP_COMPUTER_USE_WORKER_URL 不是云端可达的 HTTPS 服务地址；"
                         "Agent Engine 不能使用本机 localhost/127.0.0.1。请配置根 .env，不要复制本地 worker 地址。")
    if len((env.get("SAP_COMPUTER_USE_TOKEN") or "").strip()) < 32:
        raise ValueError("云端 SAP 已启用，但 SAP_COMPUTER_USE_TOKEN 未配置至少 32 字符令牌（与 worker 相同）")


async def validate_sap_online(env: Mapping[str, str], *, user: str | None = None) -> dict | None:
    """Read-only deployment gate; never start/restart the browser or a tunnel."""
    validate_sap_deployment(env)
    if (env.get("SAP_COMPUTER_USE_ENABLED") or "false").strip().lower() not in {"true", "1", "yes"}:
        return None
    from scripts.sap_local_bridge import probe
    cloud = env.get('SAP_BROWSER_EXECUTION_MODE') == 'cloud'
    if cloud:
        from smart_agents.sap_transport import worker_headers
        user = user or env.get('SAP_DEPLOY_CHECK_USER')
        if not user:
            raise ValueError('云端 SAP 部署检查需要 SAP_DEPLOY_CHECK_USER=tse:<实际 TSE 登录邮箱>，不需要本机节点。')
        url = env['SAP_COMPUTER_USE_WORKER_URL'].strip().rstrip('/')
        try:
            headers = await asyncio.to_thread(worker_headers, url, env['SAP_COMPUTER_USE_TOKEN'].strip(),
                iam=env.get('SAP_COMPUTER_USE_IAM_AUTH', 'true').lower() in {'true', '1', 'yes'}, allow_gcloud=True)
            async with httpx.AsyncClient(trust_env=False, timeout=15, follow_redirects=False) as client:
                response = await client.post(url+'/status', headers=headers, json={'user_id': user})
                response.raise_for_status()
                result = response.json()
            if result.get('ok') is not True or result.get('execution_location') != 'cloud_browser':
                raise ValueError('Unexpected cloud worker')
            return result
        except Exception:
            raise ValueError('云端 SAP 部署检查失败：请检查云端浏览器服务、IAM 权限、令牌与 TSE 身份；无需启动本机隧道。') from None
    if user is None:
        local = dotenv_values(Path(__file__).resolve().parents[1] / "env/local.env")
        users = [value.strip() for value in (local.get("SAP_WORKER_ALLOWED_USERS") or "").split(",") if value.strip()]
        if not users:
            raise ValueError("SAP 部署检查缺少本机绑定身份。请先运行 python -m scripts.sap_bridge_service start --tse-email <实际邮箱>。")
        user = users[0]
    try:
        return await probe(env["SAP_COMPUTER_USE_WORKER_URL"].strip().rstrip("/"),
                           env["SAP_COMPUTER_USE_TOKEN"].strip(), user)
    except (httpx.HTTPError, ValueError) as exc:
        # Do not echo exceptions containing request URLs, headers or credentials.
        raise ValueError("SAP HTTPS 部署检查失败，已阻止部署。请先启动/检查本机节点和隧道；"
                         "若地址改变，先同步根 .env。部署操作不会启动或重启本机服务。") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--online", action="store_true", help="只读验证 HTTPS 认证、绑定和可达性；失败阻止部署")
    args = parser.parse_args()
    try:
        validate_sap_deployment(os.environ)
        if args.online:
            asyncio.run(validate_sap_online(os.environ))
    except ValueError as exc:
        raise SystemExit(str(exc))
    enabled = (os.getenv("SAP_COMPUTER_USE_ENABLED") or "false").strip().lower() in {"true", "1", "yes"}
    print(("SAP HTTPS 认证与用户身份检查通过；未启动或重启浏览器。" if args.online else
           "SAP 配置检查通过（仍需验证 worker 联网与登录）") if enabled else
          "SAP 当前关闭：只提供连接诊断，查询/发票识别工具不会挂载。启用云端请配置根 .env 的 SAP 设置。")


if __name__ == "__main__":
    main()
