"""当前登录账号的模型密钥管理接口。"""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from src.tidebound.runtime.model_channels import SILICONFLOW_BASE_URL, SILICONFLOW_MODEL
from src.tidebound.storage.model_credentials import ModelCredentialInput
from webapp.auth.dependencies import current_user

router = APIRouter()


class ModelCredentialView(BaseModel):
    provider: str = 'siliconflow'
    configured: bool
    model: str
    base_url: str


def credential_view(request: Request) -> ModelCredentialView:
    """返回当前账号可用状态，绝不序列化密钥。

    Args:
        request: 含已验证身份和聊天服务的请求。

    Returns:
        供应商、模型与当前账号是否已配置凭据。
    """
    user = current_user(request)
    chat = request.app.state.chat
    credential = chat.model_credentials.load(user.scope)
    return ModelCredentialView(configured=bool(credential and credential.get_secret_value()),
                               model=SILICONFLOW_MODEL, base_url=SILICONFLOW_BASE_URL)


@router.get('/api/model-credential', response_model=ModelCredentialView)
def get_model_credential(request: Request) -> ModelCredentialView:
    """读取当前登录账号的硅基流动配置状态。

    Args:
        request: 已鉴权的当前账号请求。

    Returns:
        不含密钥的配置状态。
    """
    return credential_view(request)


@router.put('/api/model-credential', response_model=ModelCredentialView)
def set_model_credential(credential: ModelCredentialInput, request: Request) -> ModelCredentialView:
    """保存当前账号自己的硅基流动密钥。

    Args:
        credential: 用户主动提交的密钥。
        request: 已鉴权的当前账号请求。

    Returns:
        不含密钥的保存后状态。
    """
    chat = request.app.state.chat
    chat.model_credentials.save(current_user(request).scope, credential)
    return credential_view(request)


@router.delete('/api/model-credential', response_model=ModelCredentialView)
def delete_model_credential(request: Request) -> ModelCredentialView:
    """删除当前账号已保存的密钥。

    Args:
        request: 已鉴权的当前账号请求。

    Returns:
        不含密钥的删除后状态。
    """
    chat = request.app.state.chat
    chat.model_credentials.delete(current_user(request).scope)
    return credential_view(request)
