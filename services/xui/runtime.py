from __future__ import annotations

import re
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from pydantic import SecretStr

from core.security import decrypt_secret
from models.xui import XUIInboundRecord, XUIServerRecord
from services.xui.client import SanaeiXUIClient, XUIClientConfig


def build_sub_link(server: XUIServerRecord, sub_id: str) -> str:
    """
    Build the X-UI subscription URL.

    X-UI admin panel and subscription service run on DIFFERENT ports.
    base_url is the admin panel URL (e.g. http://1.2.3.4:54321/path).
    Subscription service uses server.subscription_port (default 2096).

    Result: http://1.2.3.4:2096/sub/<sub_id>
    """
    host = _extract_host(server.base_url)
    sub_port = server.subscription_port
    return f"http://{host}:{sub_port}/sub/{sub_id}"


def build_vless_uri(
    *,
    client_uuid: str,
    server: XUIServerRecord,
    inbound: XUIInboundRecord,
    sub_id: str,
    remark: str = "VPN",
) -> str:
    """
    Build a VLESS URI for direct import to clients like v2rayNG/Hiddify.
    Format: vless://<uuid>@<host>:<port>?type=tcp&security=none#<remark>
    """
    host = _extract_host(server.base_url)
    port = inbound.port or 443
    protocol = (inbound.protocol or "vless").lower()

    if protocol == "vless":
        return (
            f"vless://{client_uuid}@{host}:{port}"
            f"?type=tcp&security=none&pbk=&fp=&sid=&spx=#{remark}"
        )
    elif protocol == "vmess":
        import base64, json
        payload = {
            "v": "2",
            "ps": remark,
            "add": host,
            "port": str(port),
            "id": client_uuid,
            "aid": "0",
            "net": "tcp",
            "type": "none",
            "tls": "",
        }
        encoded = base64.b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode()
        return f"vmess://{encoded}"
    else:
        # Generic fallback: encode as vless-style
        return (
            f"vless://{client_uuid}@{host}:{port}"
            f"?type=tcp&security=none#{remark}"
        )


def _extract_host(base_url: str) -> str:
    """
    Extract bare host (no port, no path, no scheme) from a URL.
    http://1.2.3.4:54321/xui  →  1.2.3.4
    http://example.com:8080   →  example.com
    """
    # Strip scheme
    url = re.sub(r"^https?://", "", base_url.strip())
    # Take only the host:port part (before first /)
    host_port = url.split("/")[0]
    # Strip port
    host = host_port.split(":")[0]
    return host


def build_xui_client_config(server: XUIServerRecord) -> XUIClientConfig:
    if server.credentials is None:
        raise ValueError("X-UI server credentials are missing.")

    return XUIClientConfig(
        base_url=server.base_url,
        username=server.credentials.username,
        password=SecretStr(decrypt_secret(server.credentials.password_encrypted)),
    )


@asynccontextmanager
async def create_xui_client_for_server(server: XUIServerRecord) -> AsyncIterator[SanaeiXUIClient]:
    async with SanaeiXUIClient(build_xui_client_config(server)) as client:
        yield client


def ensure_inbound_server_loaded(inbound: XUIInboundRecord) -> XUIServerRecord:
    server = inbound.server
    if server is None:
        raise ValueError("Inbound server relation is missing.")
    if server.credentials is None:
        raise ValueError("Inbound server credentials relation is missing.")
    return server
