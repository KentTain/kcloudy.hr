"""招聘渠道适配层异常体系（智联/前程无忧/猎聘共用）。

错误归一约定（对齐 iam 统一集成层）：
- 配置域（块缺失/未启用/解密失败）→ IntegrationConfigError 族；
- token 获取失败 → IntegrationAuthError；
- 渠道业务错误码 → IntegrationApiError（携带 channel/endpoint/code）；
- 网络层失败 → IntegrationNetworkError。
"""

from __future__ import annotations


class IntegrationError(Exception):
    """渠道适配层基础异常。"""


class IntegrationConfigError(IntegrationError):
    """渠道凭证配置缺失或损坏（配置块不存在 / 敏感属性解密失败）。"""


class IntegrationDisabledError(IntegrationConfigError):
    """渠道未启用（hr_channel_{code}.enabled != true）。"""


class IntegrationAuthError(IntegrationError):
    """渠道 access_token 获取失败。"""


class IntegrationApiError(IntegrationError):
    """渠道接口返回错误码（携带 channel/endpoint/code 便于定位）。

    ``is_token_invalid`` 标记 token 失效类错误，供客户端失效缓存后
    强取重试一次。
    """

    def __init__(
        self,
        message: str,
        *,
        channel: str = "",
        endpoint: str = "",
        code: object = None,
        is_token_invalid: bool = False,
    ) -> None:
        super().__init__(message)
        self.channel = channel
        self.endpoint = endpoint
        self.code = code
        self.is_token_invalid = is_token_invalid


class IntegrationNetworkError(IntegrationError):
    """渠道接口网络层请求失败（连接/超时/DNS 等）。"""
