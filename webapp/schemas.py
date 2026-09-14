"""已迁移的只读展示接口契约。"""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    service: Literal["tidebound-webapp"] = "tidebound-webapp"


class CapabilitiesResponse(BaseModel):
    mode: Literal["ui-preview"] = "ui-preview"
    chat_interface: Literal[True] = True
    settings: Literal[True] = True
    chat: Literal[False] = False
    authentication: Literal[False] = False
    history: Literal[False] = False
    live2d: Literal[True] = True


class LoginConfigResponse(BaseModel):
    loginPageTitle: str = "汐伴 · Tidebound"
    loginPageSubTitle: str = "GalGame Web Chat"


class ModelAsset(BaseModel):
    name: str
    path: str


class ModelListResponse(BaseModel):
    models: list[ModelAsset]
