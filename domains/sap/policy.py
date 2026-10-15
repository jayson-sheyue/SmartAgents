"""Deterministic read-only boundary; never execute SAP business APIs directly."""
from email import policy
from email.parser import BytesParser
import re
from urllib.parse import urlsplit


def validate_order(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{10}", value):
        raise ValueError("采购订单号必须是 10 位数字")
    return value


def tenant_url(value: str) -> str:
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname
            or not url.hostname.endswith(".s4hana.cloud.sap")
            or url.username or url.password or url.port not in (None, 443)):
        raise ValueError("SAP_BROWSER_URL 必须是 https://<租户>.s4hana.cloud.sap/... 地址")
    return value


def read_only_batch(content_type: str, body: bytes) -> bool:
    """SAP UI5 batches reads using POST. Reject changesets and all non-GET parts."""
    if len(body) > 2_000_000 or "\r" in content_type or "\n" in content_type:
        return False
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode("ascii", errors="replace")
        + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
    )
    if not message.is_multipart() or message.defects:
        return False
    parts = list(message.iter_parts())
    if not parts:
        return False
    for part in parts:
        if part.is_multipart() or part.defects or part.get_content_type() != "application/http":
            return False
        payload = part.get_payload(decode=True)
        if not payload:
            return False
        lines = payload.lstrip(b"\r\n").splitlines()
        if not re.fullmatch(rb"GET [^\s]+ HTTP/1\.[01]", lines[0]):
            return False
        # No second HTTP message, smuggled mutation, or GET request body.
        split = re.split(rb"\r?\n\r?\n", payload.lstrip(b"\r\n"), maxsplit=1)
        if len(split) > 1 and split[1].strip():
            return False
    return True


def allow_request(url: str, method: str, content_type: str, body: bytes,
                  origin: str, resource_type: str = "") -> bool:
    parsed = urlsplit(url)
    # SAP UI5 loads icons, fonts and application code from SAP's official CDN.
    # UI5 also fetches JS/XML/properties assets through XHR under /resources/.
    # Never allow off-origin document navigation or arbitrary XHR.
    if (parsed.scheme == "https" and parsed.hostname in {"ui5.sap.com", "sapui5.hana.ondemand.com"}
            and method == "GET" and (resource_type in {"script", "stylesheet", "font", "image"}
                or (resource_type in {"xhr", "fetch"} and "/resources/" in parsed.path))):
        return True
    if parsed.scheme != "https" or parsed.netloc != urlsplit(origin).netloc:
        return False
    if method in {"GET", "HEAD", "OPTIONS"}:
        return True
    return (method == "POST" and parsed.path.rstrip("/").endswith("/$batch")
            and read_only_batch(content_type, body))
