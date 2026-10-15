"""Start a bound local SAP worker + Quick Tunnel; never deploy cloud services."""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import sys
import tempfile

import httpx
from dotenv import dotenv_values

from scripts.check_sap_deployment import validate_sap_deployment
from smart_agents.env_runtime import load_runtime_env
from domains.sap.golden_path import DEMO_URL
from domains.sap.policy import tenant_url

ROOT = Path(__file__).resolve().parents[1]
BRIDGE_DIR = ROOT / ".sap_bridge"
CLOUD_ENV = BRIDGE_DIR / "cloud.env"
URL_PATTERN = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com\b")


def tse_user(email: str) -> str:
    email = email.strip().lower()
    if not re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", email) or len(email) > 254:
        raise ValueError("请填写实际 TSE 登录邮箱")
    return "tse:" + email


def update_env(path: Path, updates: dict[str, str]) -> None:
    """Atomic private file update; preserve all unrelated keys/comments."""
    if path.is_symlink():
        raise ValueError("配置文件不能是符号链接")
    for key, value in updates.items():
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or any(c in value for c in "\r\n\x00"):
            raise ValueError("配置键和值必须为单行")
    lines = path.read_text().splitlines() if path.exists() else []
    remaining = dict(updates)
    output = []
    for line in lines:
        match = re.match(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]*)\s*=", line)
        key = match.group(1) if match else None
        if key in updates:
            if key in remaining:
                value = remaining.pop(key).replace("\\", "\\\\").replace("'", "\\'")
                output.append(f"{key}='{value}'")
        else:
            output.append(line)
    for key, value in remaining.items():
        value = value.replace("\\", "\\\\").replace("'", "\\'")
        output.append(f"{key}='{value}'")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".sap-env-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write("\n".join(output) + "\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


async def probe(url: str, token: str, user: str) -> dict:
    async with httpx.AsyncClient(trust_env=False, timeout=10, follow_redirects=False) as client:
        health = await client.get(url + "/health")
        health.raise_for_status()
        payload = health.json()
        if payload.get("service") != "sap_computer_use" or payload.get("bridge_protocol") != 1:
            raise ValueError("端口上的服务不是新版 SAP 本机节点；请换 --port 或关闭旧服务后再启动")
        response = await client.post(url + "/status", headers={"Authorization": "Bearer " + token}, json={"user_id": user})
        if response.status_code == 401:
            raise ValueError("SAP 节点令牌不一致")
        if response.status_code == 403:
            raise ValueError("此 TSE 邮箱尚未绑定到该节点，请重新启动节点配置")
        response.raise_for_status()
        data = response.json()
        if not data.get("ok") or data.get("user_bound") is not True:
            raise ValueError("节点尚未配置用户绑定，禁止发布 HTTPS 接入")
        return data


def publish_configuration(url: str, token: str, *, sync_root: bool) -> None:
    values = {"SAP_COMPUTER_USE_ENABLED": "true", "SAP_COMPUTER_USE_WORKER_URL": url,
              "SAP_COMPUTER_USE_TOKEN": token,
              "INVOICE_RECOGNITION_MODEL": os.getenv("INVOICE_RECOGNITION_MODEL", "gemini-3.8-flash")}
    validate_sap_deployment(values)
    update_env(CLOUD_ENV, values)
    if sync_root:
        update_env(ROOT / ".env", values)
        # Direct ADK/Python deployments read the agent folder's .env, whereas
        # the shell deployment regenerates it from root .env. Keep an existing
        # packaged config in sync so either path does not reuse an expired tunnel.
        agent_env = ROOT / "smart_agents/.env"
        if agent_env.is_file():
            update_env(agent_env, values)


async def tunnel_url(process) -> str:
    async def read():
        while line := await process.stdout.readline():
            match = URL_PATTERN.search(line.decode(errors="replace"))
            if match:
                return match.group(0)
        raise ValueError("cloudflared 已退出，未生成 HTTPS 地址；请检查网络")
    try:
        return await asyncio.wait_for(read(), 45)
    except asyncio.TimeoutError:
        raise ValueError("45 秒内未生成隧道地址；请检查 cloudflared 与网络") from None


async def stop(process):
    if process is None or process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), 15)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()


async def main():
    parser = argparse.ArgumentParser(description="云端 SmartAgents → 本机 SAP 专用浏览器")
    parser.add_argument("--tse-email", required=True, help="允许调用本机浏览器的 TSE 登录邮箱")
    parser.add_argument("--port", type=int, default=8011, help="默认避开旧版 worker 的 8010 端口")
    parser.add_argument("--sync-cloud-env", action="store_true", help="仅更新根 .env 的 SAP 配置，不部署")
    parser.add_argument("--check-only", action="store_true", help="验证上次生成的 HTTPS 通道，不启动或改配置")
    parser.add_argument("--instance-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    user = tse_user(args.tse_email)
    if not 1024 <= args.port <= 65535:
        parser.error("端口必须为 1024–65535")
    load_runtime_env()
    if args.check_only:
        values = dotenv_values(CLOUD_ENV)
        validate_sap_deployment(values)
        if not values.get("SAP_COMPUTER_USE_WORKER_URL"):
            raise ValueError("尚未生成云端配置，请先启动本机接入")
        result = await probe(values["SAP_COMPUTER_USE_WORKER_URL"], values.get("SAP_COMPUTER_USE_TOKEN", ""), user)
        print(result.get("message", "HTTPS 通道已连接"), flush=True)
        return
    cloudflared = shutil.which("cloudflared")
    if not cloudflared:
        raise ValueError("未找到 cloudflared，请先安装后重试")
    token = os.getenv("SAP_COMPUTER_USE_TOKEN", "").strip() or secrets.token_urlsafe(32)
    if len(token) < 32:
        raise ValueError("现有 SAP_COMPUTER_USE_TOKEN 少于 32 字符，请更正配置")
    local_url = f"http://127.0.0.1:{args.port}"
    worker = tunnel = None
    stopping = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        asyncio.get_running_loop().add_signal_handler(sig, stopping.set)
    try:
        try:
            await probe(local_url, token, user)
            print("复用已运行且完成用户绑定的本机 SAP 节点。", flush=True)
            previous = dotenv_values(CLOUD_ENV)
            if previous.get("SAP_COMPUTER_USE_TOKEN") == token and previous.get("SAP_COMPUTER_USE_WORKER_URL"):
                try:
                    await probe(previous["SAP_COMPUTER_USE_WORKER_URL"], token, user)
                except (httpx.HTTPError, ValueError):
                    pass
                else:
                    if args.sync_cloud_env:
                        publish_configuration(previous["SAP_COMPUTER_USE_WORKER_URL"], token, sync_root=True)
                    print("现有 HTTPS 通道健康，复用原地址；未启动新隧道、未重启浏览器。", flush=True)
                    return
        except httpx.ConnectError:
            sap_url = os.getenv("SAP_BROWSER_URL", "").strip() or DEMO_URL
            tenant_url(sap_url)
            if "#" not in sap_url or sap_url.split("#", 1)[1] in {"", "Shell-home"}:
                sap_url = sap_url.split("#", 1)[0] + "#PurchaseOrder-manage"
            updates = {"SAP_COMPUTER_USE_ENABLED": "true", "SAP_COMPUTER_USE_WORKER_URL": local_url,
                       "SAP_COMPUTER_USE_PORT": str(args.port), "SAP_COMPUTER_USE_TOKEN": token,
                       "SAP_WORKER_ALLOWED_USERS": user,
                       "SAP_BROWSER_URL": sap_url,
                       "SAP_COMPUTER_USE_GOLDEN_PATH": "true", "SAP_COMPUTER_USE_DEMO_MODE": "computer-use"}
            update_env(ROOT / "env/local.env", updates)
            worker = await asyncio.create_subprocess_exec(sys.executable, "-m", "services.sap_computer_use.server", cwd=ROOT)
            for attempt in range(30):
                if worker.returncode is not None:
                    raise ValueError("SAP worker 启动失败，请检查上方日志")
                try:
                    await probe(local_url, token, user)
                    break
                except httpx.ConnectError:
                    await asyncio.sleep(.5)
            else:
                raise ValueError("本机 worker 未在 15 秒内就绪")
        BRIDGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        BRIDGE_DIR.chmod(0o700)
        tunnel_config = BRIDGE_DIR / "quick-tunnel.yml"
        tunnel_config.write_text("{}\n")
        tunnel_config.chmod(0o600)
        tunnel = await asyncio.create_subprocess_exec(cloudflared, "tunnel", "--config", str(tunnel_config),
            "--no-autoupdate", "--protocol", "http2", "--url", local_url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        url = await tunnel_url(tunnel)
        # Drain provider logs without leaking them or blocking its process pipe.
        async def drain():
            while line := await tunnel.stdout.readline():
                # Keep useful connection events without logging provider credentials.
                if b" ERR " in line or b"error=" in line:
                    print("SAP 隧道报告网络错误；请运行后台节点 status 检查。未自动更换地址。", flush=True)
                elif b"Registered tunnel connection" in line:
                    print("SAP 隧道连接已建立/恢复。", flush=True)
        reader = asyncio.create_task(drain())
        print("HTTPS 地址已生成，正在验证令牌认证和邮箱绑定…", flush=True)
        for attempt in range(8):
            try:
                await probe(url, token, user)
                break
            except (httpx.HTTPError, ValueError):
                if attempt == 7:
                    raise ValueError("隧道地址已生成，但 HTTPS 验证失败；未写入云端配置，请检查网络/隧道") from None
                await asyncio.sleep(2)
        publish_configuration(url, token, sync_root=args.sync_cloud_env)
        print(f"SAP_COMPUTER_USE_WORKER_URL={url}\n云端配置已保存：{CLOUD_ENV}\n"
              + ("根 .env 和已有 smart_agents/.env 的 SAP 配置也已同步。\n" if args.sync_cloud_env else "")
              + "令牌已保存但不会打印；没有执行云端部署。\n"
                "请保持此终端运行；更新 Agent Engine 后，在 TSE 发送‘连接 SAP’，再在本机专用窗口亲自登录。", flush=True)
        tasks = [asyncio.create_task(stopping.wait()), asyncio.create_task(tunnel.wait())]
        if worker:
            tasks.append(asyncio.create_task(worker.wait()))
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        if not stopping.is_set():
            raise ValueError("本机节点或隧道已退出，HTTPS 通道中断；请重新启动")
        reader.cancel()
    finally:
        await stop(tunnel)
        await stop(worker)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (ValueError, httpx.HTTPError) as exc:
        # Never print request headers, cloud credentials, response body, or token.
        print(str(exc) if isinstance(exc, ValueError) else "SAP 通道请求失败，请检查网络与服务配置。", file=sys.stderr)
        raise SystemExit(1)
