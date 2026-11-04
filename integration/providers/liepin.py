"""猎聘开放平台客户端（liepin）。

端点形态按猎聘开放平台惯例（token 为 POST /api/oauth/token，业务码
``flag`` 为 1 即成功）；真实连通回归依赖环境凭证（可延期测试）。
"""

from __future__ import annotations

from hr.integration.errors import IntegrationApiError
from hr.integration.http import ChannelHttpClient, HttpResponse, HttpTransport
from hr.integration.providers.base import (
    ChannelApplication,
    ChannelResume,
    RecruitingChannelClient,
)

BASE_URL = "https://api.liepin.com"

# token 失效类业务码
TOKEN_INVALID_CODES = frozenset({"40101", "40102"})


class LiepinChannelClient(RecruitingChannelClient):
    """猎聘：职位发布/下线/投递列表/简历详情。"""

    channel = "liepin"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._http = ChannelHttpClient(BASE_URL, transport=transport)

    # ---------------------------------------------------------------- token

    async def _request_token(self, credentials: dict) -> tuple[str, int | None]:
        resp = await self._http.request(
            "POST",
            "/api/oauth/token",
            json_body={
                "grantType": "client_credentials",
                "appId": credentials.get("app_key", ""),
                "appSecret": credentials.get("app_secret", ""),
            },
        )
        self._raise_if_error(resp, "/api/oauth/token")
        data = resp.data or {}
        token = data.get("accessToken")
        if not token:
            raise IntegrationApiError(
                "猎聘 token 响应缺少 accessToken",
                channel=self.channel,
                endpoint="/api/oauth/token",
            )
        return token, data.get("expireIn")

    # ---------------------------------------------------------------- 能力

    async def publish_posting(
        self, tenant_id: str, credentials: dict, posting: dict, jd: str | None
    ) -> str:
        async def call(token: str):
            resp = await self._http.request(
                "POST",
                "/api/job/publish",
                json_body={
                    "jobTitle": posting.get("title"),
                    "jobLevel": posting.get("job_level"),
                    "salaryLower": posting.get("salary_min"),
                    "salaryUpper": posting.get("salary_max"),
                    "city": posting.get("org_name"),
                    "jobDescription": jd,
                },
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/job/publish")
            return str((resp.data or {}).get("jobId", ""))

        return await self._authorized_call(tenant_id, credentials, call)

    async def offline_posting(
        self, tenant_id: str, credentials: dict, external_post_id: str
    ) -> None:
        async def call(token: str):
            resp = await self._http.request(
                "POST",
                "/api/job/close",
                json_body={"jobId": external_post_id},
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/job/close")

        await self._authorized_call(tenant_id, credentials, call)

    async def fetch_applications(
        self,
        tenant_id: str,
        credentials: dict,
        external_post_id: str,
        since: str | None = None,
        page: int = 1,
    ) -> list[ChannelApplication]:
        async def call(token: str):
            resp = await self._http.request(
                "GET",
                "/api/candidate/list",
                params={"jobId": external_post_id, "startTime": since or "", "currentPage": page},
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/candidate/list")
            data = resp.data or {}
            return [
                ChannelApplication(
                    external_application_id=str(item.get("deliverId", "")),
                    external_candidate_id=str(item.get("candId", "")),
                    name=item.get("candName"),
                    phone=item.get("mobile"),
                    email=item.get("email"),
                    apply_time=item.get("deliverTime"),
                    resume_url=item.get("resumeUrl"),
                    raw=item,
                )
                for item in data.get("list", [])
            ]

        return await self._authorized_call(tenant_id, credentials, call)

    async def fetch_resume(
        self, tenant_id: str, credentials: dict, external_candidate_id: str
    ) -> ChannelResume:
        async def call(token: str):
            resp = await self._http.request(
                "GET",
                "/api/candidate/resume",
                params={"candId": external_candidate_id},
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/candidate/resume")
            data = resp.data or {}
            return ChannelResume(
                external_candidate_id=external_candidate_id,
                content=data.get("resumeContent") or "",
                content_type="html",
                raw=data,
            )

        return await self._authorized_call(tenant_id, credentials, call)

    # ---------------------------------------------------------------- 内部

    @staticmethod
    def _auth_headers(token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def _raise_if_error(self, resp: HttpResponse, endpoint: str) -> None:
        if resp.status == 401:
            raise IntegrationApiError(
                f"猎聘接口鉴权失败（HTTP 401）: {endpoint}",
                channel=self.channel,
                endpoint=endpoint,
                code=401,
                is_token_invalid=True,
            )
        if resp.status >= 400:
            raise IntegrationApiError(
                f"猎聘接口请求失败（HTTP {resp.status}）: {endpoint}",
                channel=self.channel,
                endpoint=endpoint,
                code=resp.status,
            )
        data = resp.data or {}
        flag = data.get("flag")
        if flag is not None and str(flag) != "1":
            code = data.get("errorCode", flag)
            raise IntegrationApiError(
                f"猎聘接口业务错误: {endpoint} code={code} {data.get('message', '')}",
                channel=self.channel,
                endpoint=endpoint,
                code=code,
                is_token_invalid=str(code) in TOKEN_INVALID_CODES,
            )
