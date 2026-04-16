from __future__ import annotations
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class HeaderSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = "none"


class TcpSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    header: HeaderSettings = Field(default_factory=HeaderSettings)


class KcpSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    header: HeaderSettings = Field(default_factory=HeaderSettings)
    seed: str = ""


class WsSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str = "/"
    host: str = ""
    headers: dict[str, str] = Field(default_factory=dict)

    def get_host(self) -> str:
        return self.headers.get("Host") or self.headers.get("host") or self.host


class HttpSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    path: str = "/"
    host: list[str] = Field(default_factory=list)

    def get_first_host(self) -> str:
        return self.host[0] if self.host else ""


class GrpcSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    serviceName: str = ""


class TlsSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    serverName: str = ""
    fingerprint: str = ""
    alpn: list[str] = Field(default_factory=list)


class RealitySettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    serverName: str = ""
    fingerprint: str = ""
    publicKey: str = ""
    shortId: str = ""
    spiderX: str = ""


class ExternalProxy(BaseModel):
    model_config = ConfigDict(extra="ignore")
    dest: str = ""
    port: int | None = None


class StreamSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")
    network: str = "tcp"
    security: str = "none"
    tcpSettings: TcpSettings | None = None
    kcpSettings: KcpSettings | None = None
    wsSettings: WsSettings | None = None
    httpSettings: HttpSettings | None = None
    grpcSettings: GrpcSettings | None = None
    tlsSettings: TlsSettings | None = None
    realitySettings: RealitySettings | None = None
    externalProxy: list[ExternalProxy] = Field(default_factory=list)
