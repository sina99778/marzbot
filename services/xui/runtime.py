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

    If server.sub_domain is set, use it instead of extracting from base_url.
    Result: http://<host>:<port>/sub/<sub_id>
    """
    if server.sub_domain:
        host = server.sub_domain
    else:
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
    Build a VLESS/VMess URI by reading actual stream settings from inbound metadata.
    Supports: tcp, ws, grpc, http, kcp networks and none/tls/reality security.
    """
    # Use config_domain if set, otherwise extract from base_url
    if server.config_domain:
        host = server.config_domain
    else:
        host = _extract_host(server.base_url)

    port = inbound.port or 443
    protocol = (inbound.protocol or "vless").lower()

    # Read stream settings from inbound metadata
    meta = inbound.metadata_ or {}
    stream = meta.get("stream_settings", {})
    from schemas.internal.xui_stream import StreamSettings

    try:
        if isinstance(stream, str):
            import json
            stream = json.loads(stream)
        stream_model = StreamSettings.model_validate(stream)
    except Exception:
        # Fallback to an empty model if parsing completely fails
        stream_model = StreamSettings()

    network = stream_model.network
    security = stream_model.security

    # Build query parameters
    params: dict[str, str] = {
        "type": network,
        "security": security,
    }

    # --- Network-specific settings ---
    if network == "ws" and stream_model.wsSettings:
        params["path"] = stream_model.wsSettings.path
        ws_host = stream_model.wsSettings.get_host()
        if ws_host:
            params["host"] = ws_host
            
    elif network == "grpc" and stream_model.grpcSettings:
        if stream_model.grpcSettings.serviceName:
            params["serviceName"] = stream_model.grpcSettings.serviceName
            
    elif network == "tcp" and stream_model.tcpSettings:
        if stream_model.tcpSettings.header.type != "none":
            params["headerType"] = stream_model.tcpSettings.header.type
            
    elif network == "kcp" and stream_model.kcpSettings:
        if stream_model.kcpSettings.header.type != "none":
            params["headerType"] = stream_model.kcpSettings.header.type
        if stream_model.kcpSettings.seed:
            params["seed"] = stream_model.kcpSettings.seed
            
    elif network in ("http", "h2") and stream_model.httpSettings:
        params["path"] = stream_model.httpSettings.path
        h_host = stream_model.httpSettings.get_first_host()
        if h_host:
            params["host"] = h_host

    # --- Security-specific settings ---
    if security == "tls" and stream_model.tlsSettings:
        if stream_model.tlsSettings.serverName:
            params["sni"] = stream_model.tlsSettings.serverName
        if stream_model.tlsSettings.fingerprint:
            params["fp"] = stream_model.tlsSettings.fingerprint
        if stream_model.tlsSettings.alpn:
            params["alpn"] = ",".join(stream_model.tlsSettings.alpn)
            
    elif security == "reality" and stream_model.realitySettings:
        r = stream_model.realitySettings
        if r.publicKey: params["pbk"] = r.publicKey
        if r.shortId: params["sid"] = r.shortId
        if r.serverName: params["sni"] = r.serverName
        if r.fingerprint: params["fp"] = r.fingerprint
        if r.spiderX: params["spx"] = r.spiderX

    # --- External proxy / SNI override ---
    if stream_model.externalProxy:
        first_proxy = stream_model.externalProxy[0]
        if first_proxy.dest:
            host = first_proxy.dest.split(":")[0] if ":" in first_proxy.dest else first_proxy.dest
        if first_proxy.port:
            port = first_proxy.port

        if "host" not in params and network == "ws":
            original_host = server.config_domain or _extract_host(server.base_url)
            if original_host:
                params["host"] = original_host

        if "sni" not in params:
            params["sni"] = host

    # Build URI
    from urllib.parse import urlencode, quote
    query = urlencode(params, safe="/:@,")

    if protocol == "vless":
        return f"vless://{client_uuid}@{host}:{port}?{query}#{quote(remark)}"
    elif protocol == "vmess":
        import base64, json as json_mod
        payload = {
            "v": "2",
            "ps": remark,
            "add": host,
            "port": str(port),
            "id": client_uuid,
            "aid": "0",
            "net": network,
            "type": params.get("headerType", "none"),
            "host": params.get("host", params.get("sni", "")),
            "path": params.get("path", ""),
            "tls": security if security != "none" else "",
            "sni": params.get("sni", ""),
            "fp": params.get("fp", ""),
            "alpn": params.get("alpn", ""),
        }
        encoded = base64.b64encode(json_mod.dumps(payload, separators=(",", ":")).encode()).decode()
        return f"vmess://{encoded}"
    else:
        return f"vless://{client_uuid}@{host}:{port}?{query}#{quote(remark)}"


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
