"""Explicit local SAP background service. No cloud deployment or automatic URL rotation."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid

import httpx
from dotenv import dotenv_values
from scripts.sap_local_bridge import ROOT, BRIDGE_DIR, CLOUD_ENV, probe, tse_user
from scripts.check_sap_deployment import validate_sap_deployment

RECORD = BRIDGE_DIR / 'service.json'
LOG = BRIDGE_DIR / 'service.log'
LOCK = BRIDGE_DIR / 'service-control.lock'


def private_directory():
    if BRIDGE_DIR.is_symlink():
        raise ValueError('SAP service directory must not be a symlink')
    BRIDGE_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    BRIDGE_DIR.chmod(0o700)


@contextmanager
def control_lock():
    private_directory()
    if LOCK.is_symlink(): raise ValueError('Invalid service lock')
    fd=os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    except BlockingIOError:
        raise ValueError('另一个启动/停止操作正在执行，请稍后再试。') from None
    finally:
        os.close(fd)


def record():
    try:
        if RECORD.is_symlink(): raise ValueError('Invalid service record')
        return json.loads(RECORD.read_text())
    except FileNotFoundError:
        return None


def is_owned_running(info):
    if not isinstance(info, dict) or type(info.get('pid')) is not int or info['pid'] <= 1:
        return False
    nonce=info.get('instance_id')
    if not isinstance(nonce,str) or len(nonce)!=32:
        return False
    result=subprocess.run(['ps','-p',str(info['pid']),'-o','command='],capture_output=True,text=True)
    command=result.stdout.strip()
    return result.returncode==0 and '-m scripts.sap_local_bridge' in command and '--instance-id '+nonce in command


def save_record(pid,nonce):
    if RECORD.is_symlink(): raise ValueError('Invalid service record')
    fd=os.open(RECORD,os.O_CREAT|os.O_WRONLY|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump({'pid':pid,'instance_id':nonce},stream)
    RECORD.chmod(0o600)


def configured_user(email):
    if email: return tse_user(email)
    values=dotenv_values(ROOT / 'env/local.env')
    users=[u.strip() for u in (values.get('SAP_WORKER_ALLOWED_USERS') or '').split(',') if u.strip()]
    if len(users)!=1 or not users[0].startswith('tse:'):
        raise ValueError('请提供 --tse-email <实际 TSE 登录邮箱>')
    return tse_user(users[0][4:])


async def check(user):
    values=dotenv_values(CLOUD_ENV)
    validate_sap_deployment(values)
    if not values.get('SAP_COMPUTER_USE_WORKER_URL'):
        raise ValueError('尚无 HTTPS 配置，请先 start。')
    result=await probe(values['SAP_COMPUTER_USE_WORKER_URL'],values.get('SAP_COMPUTER_USE_TOKEN',''),user)
    root=dotenv_values(ROOT / '.env')
    if any(root.get(k)!=values.get(k) for k in ('SAP_COMPUTER_USE_WORKER_URL','SAP_COMPUTER_USE_TOKEN')):
        raise ValueError('根 .env 与当前后台节点配置不一致，请同步后部署。')
    return result


async def start(user,port):
    info=record()
    if is_owned_running(info):
        await check(user)
        print('后台 SAP 节点已在运行，复用现有 HTTPS 地址；没有重启。',flush=True)
        return
    # Do not create a second Quick Tunnel while an unmanaged foreground node is healthy.
    local=dotenv_values(ROOT / 'env/local.env')
    try:
        await probe(f'http://127.0.0.1:{port}',local.get('SAP_COMPUTER_USE_TOKEN',''),user)
    except httpx.ConnectError:
        pass
    else:
        raise ValueError('检测到已有前台 SAP 节点。请先正常停止其启动器，再用 start 切换后台；不会自动更换现有地址。')
    if LOG.is_symlink(): raise ValueError('Invalid service log')
    nonce=uuid.uuid4().hex
    args=[sys.executable,'-u','-m','scripts.sap_local_bridge','--tse-email',user[4:],
          '--port',str(port),'--sync-cloud-env','--instance-id',nonce]
    fd=os.open(LOG,os.O_CREAT|os.O_WRONLY|os.O_APPEND,0o600)
    with os.fdopen(fd,'ab',buffering=0) as log:
        process=subprocess.Popen(args,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    save_record(process.pid,nonce)
    if sys.platform=='darwin' and Path('/usr/bin/caffeinate').is_file():
        subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(process.pid)],stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    print('已启动独立后台节点，正在验证 HTTPS 通道…',flush=True)
    deadline=time.monotonic()+100
    while time.monotonic()<deadline:
        if process.poll() is not None:
            raise ValueError('后台节点启动失败；请查看 .sap_bridge/service.log。未执行云端部署。')
        try:
            await check(user)
            print('后台 SAP 节点与 HTTPS 通道已就绪。关闭此命令的终端不会停止节点。',flush=True)
            print('日志：'+str(LOG)+'\n未执行云端部署。',flush=True)
            return
        except (httpx.HTTPError,ValueError):
            await asyncio.sleep(2)
    raise ValueError('后台节点仍在启动或网络不可用。请运行 status 检查；未执行云端部署。')


def stop_owned():
    info=record()
    if not is_owned_running(info):
        if info: RECORD.unlink(missing_ok=True)
        print('没有本命令管理的运行节点；未停止其他进程。')
        return
    os.kill(info['pid'],signal.SIGTERM)
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        if not is_owned_running(info):
            RECORD.unlink(missing_ok=True)
            print('后台节点已停止；下次重建临时通道时地址可能变化。')
            return
        time.sleep(.5)
    raise ValueError('节点仍在正常退出，未强制终止；请稍后 status。')


def main():
    parser=argparse.ArgumentParser(description='SAP 本机后台节点；部署不会重启此服务')
    parser.add_argument('action',choices=['start','status','stop'])
    parser.add_argument('--tse-email')
    parser.add_argument('--port',type=int,default=8011)
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('端口应为 1024–65535')
    if args.action=='stop':
        with control_lock(): stop_owned()
        return
    user=configured_user(args.tse_email)
    if args.action=='start':
        with control_lock(): asyncio.run(start(user,args.port))
    else:
        info=record();print('独立后台进程：'+('运行中' if is_owned_running(info) else '未由本命令管理'))
        result=asyncio.run(check(user))
        print('HTTPS 认证与绑定：正常；SAP 登录：'+('已登录' if result.get('logged_in') else '需要在专用浏览器登录'))


if __name__=='__main__':
    try: main()
    except (ValueError,httpx.HTTPError) as exc:
        print(str(exc) if isinstance(exc,ValueError) else 'HTTPS 检查失败；请查看节点日志、网络及当前地址。',file=sys.stderr)
        raise SystemExit(1)
