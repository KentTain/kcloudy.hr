"""智联招聘开放平台客户端（zhilian）。

端点形态按智联招聘开放平台惯例（token 为 OAuth client_credentials，
业务码 ``code`` 非成功值即失败）；真实连通回归依赖环境凭证（可延期测试）。
"""

from __future__ import annotations

from hr.integration.errors import IntegrationApiError
from hr.integration.http import ChannelHttpClient, HttpResponse, HttpTransport
from hr.integration.providers.base import (
    ChannelApplication,
    ChannelResume,
    RecruitingChannelClient,
)

BASE_URL = "https://openapi.zhaopin.com"

# token 失效类业务码（access_token 过期/非法）
TOKEN_INVALID_CODES = frozenset({"2602102", "2602103"})


class ZhilianChannelClient(RecruitingChannelClient):
    """智联招聘：职位发布/下线/投递列表/简历详情。"""

    channel = "zhilian"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._http = ChannelHttpClient(BASE_URL, transport=transport)

    # ---------------------------------------------------------------- token

    async def _request_token(self, credentials: dict) -> tuple[str, int | None]:
        resp = await self._http.request(
            "POST",
            "/oauth/token",
            json_body={
                "grant_type": "client_credentials",
                "client_id": credentials.get("app_key", ""),
                "client_secret": credentials.get("app_secret", ""),
            },
        )
        self._raise_if_error(resp, "/oauth/token")
        data = resp.data or {}
        token = data.get("access_token")
        if not token:
            raise IntegrationApiError(
                "智联 token 响应缺少 access_token",
                channel=self.channel,
                endpoint="/oauth/token",
            )
        return token, data.get("expires_in")

    # ---------------------------------------------------------------- 能力

    async def publish_posting(
        self, tenant_id: str, credentials: dict, posting: dict, jd: str | None
    ) -> str:
        async def call(token: str):
            resp = await self._http.request(
                "POST",
                "/api/hr/job/publish",
                json_body={
                    "title": posting.get("title"),
                    "jobLevel": posting.get("job_level"),
                    "salaryLower": posting.get("salary_min"),
                    "salaryUpper": posting.get("salary_max"),
                    "workCity": posting.get("org_name"),
                    "description": jd,
                },
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/hr/job/publish")
            return str((resp.data or {}).get("jobId", ""))

        return await self._authorized_call(tenant_id, credentials, call)

    async def offline_posting(
        self, tenant_id: str, credentials: dict, external_post_id: str
    ) -> None:
        async def call(token: str):
            resp = await self._http.request(
                "POST",
                "/api/hr/job/offline",
                json_body={"jobId": external_post_id},
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/hr/job/offline")

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
                "/api/resume/list",
                params={"jobId": external_post_id, "startDate": since or "", "page": page},
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/resume/list")
            data = resp.data or {}
            return [
                ChannelApplication(
                    external_application_id=str(item.get("applyId", "")),
                    external_candidate_id=str(item.get("candidateId", "")),
                    name=item.get("name"),
                    phone=item.get("mobile"),
                    email=item.get("email"),
                    apply_time=item.get("applyDate"),
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
                "/api/resume/detail",
                params={"candidateId": external_candidate_id},
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/resume/detail")
            data = resp.data or {}
            return ChannelResume(
                external_candidate_id=external_candidate_id,
                content=data.get("resumeHtml") or data.get("resumeText") or "",
                content_type="html" if data.get("resumeHtml") else "text",
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
                f"智联接口鉴权失败（HTTP 401）: {endpoint}",
                channel=self.channel,
                endpoint=endpoint,
                code=401,
                is_token_invalid=True,
            )
        if resp.status >= 400:
            raise IntegrationApiError(
                f"智联接口请求失败（HTTP {resp.status}）: {endpoint}",
                channel=self.channel,
                endpoint=endpoint,
                code=resp.status,
            )
        data = resp.data or {}
        code = str(data.get("code", ""))
        if code and code not in ("200", "0"):
            raise IntegrationApiError(
                f"智联接口业务错误: {endpoint} code={code} {data.get('message', '')}",
                channel=self.channel,
                endpoint=endpoint,
                code=code,
                is_token_invalid=code in TOKEN_INVALID_CODES,
            )
