"""Cloud Run IAM plus application authentication; never expose credentials to UI."""
import subprocess
import threading
import time

_cache = {}
_lock = threading.Lock()


def worker_headers(url, token, *, iam=False, allow_gcloud=False):
    headers = {'Authorization': 'Bearer ' + token}
    if not iam:
        return headers
    with _lock:
        cached = _cache.get((url, allow_gcloud))
        if cached and time.monotonic()-cached[0] < 2700:
            identity = cached[1]
        else:
            from google.auth.transport.requests import Request
            from google.oauth2.id_token import fetch_id_token
            try:
                identity = fetch_id_token(Request(), url)
            except Exception:
                if not allow_gcloud:
                    raise ValueError('Cloud Run caller identity unavailable') from None
                result = subprocess.run(['gcloud', 'auth', 'print-identity-token'],
                    capture_output=True, text=True, timeout=30, check=False)
                identity = result.stdout.strip()
                if result.returncode or not identity:
                    raise ValueError('Cloud Run deployment identity unavailable') from None
            _cache[(url, allow_gcloud)] = (time.monotonic(), identity)
    # Cloud Run verifies this header; the worker separately verifies Authorization.
    headers['X-Serverless-Authorization'] = 'Bearer ' + identity
    return headers
