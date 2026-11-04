"""前程无忧开放平台客户端（job51）。

端点形态按前程无忧开放平台惯例（token 经 GET /token 换取，业务码
``status`` 为 ``success`` 即成功）；真实连通回归依赖环境凭证（可延期测试）。
"""

from __future__ import annotations

from hr.integration.errors import IntegrationApiError
from hr.integration.http import ChannelHttpClient, HttpResponse, HttpTransport
from hr.integration.providers.base import (
    ChannelApplication,
    ChannelResume,
    RecruitingChannelClient,
)

BASE_URL = "https://open.51job.com"

# token 失效类业务码
TOKEN_INVALID_CODES = frozenset({"10001", "10002"})


class Job51ChannelClient(RecruitingChannelClient):
    """前程无忧：职位发布/下线/投递列表/简历详情。"""

    channel = "job51"

    def __init__(self, transport: HttpTransport | None = None) -> None:
        self._http = ChannelHttpClient(BASE_URL, transport=transport)

    # ---------------------------------------------------------------- token

    async def _request_token(self, credentials: dict) -> tuple[str, int | None]:
        resp = await self._http.request(
            "GET",
            "/token",
            params={
                "appKey": credentials.get("app_key", ""),
                "appSecret": credentials.get("app_secret", ""),
            },
        )
        self._raise_if_error(resp, "/token")
        data = resp.data or {}
        token = data.get("accessToken")
        if not token:
            raise IntegrationApiError(
                "前程无忧 token 响应缺少 accessToken",
                channel=self.channel,
                endpoint="/token",
            )
        return token, data.get("expiresIn")

    # ---------------------------------------------------------------- 能力

    async def publish_posting(
        self, tenant_id: str, credentials: dict, posting: dict, jd: str | None
    ) -> str:
        async def call(token: str):
            resp = await self._http.request(
                "POST",
                "/api/job/add",
                json_body={
                    "jobName": posting.get("title"),
                    "jobLevel": posting.get("job_level"),
                    "salaryFrom": posting.get("salary_min"),
                    "salaryTo": posting.get("salary_max"),
                    "workLocation": posting.get("org_name"),
                    "jobDesc": jd,
                },
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/job/add")
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
                "/api/apply/list",
                params={"jobId": external_post_id, "beginDate": since or "", "pageNo": page},
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/apply/list")
            data = resp.data or {}
            return [
                ChannelApplication(
                    external_application_id=str(item.get("applyNo", "")),
                    external_candidate_id=str(item.get("userId", "")),
                    name=item.get("userName"),
                    phone=item.get("phone"),
                    email=item.get("email"),
                    apply_time=item.get("applyTime"),
                    resume_url=item.get("resumePath"),
                    raw=item,
                )
                for item in data.get("records", [])
            ]

        return await self._authorized_call(tenant_id, credentials, call)

    async def fetch_resume(
        self, tenant_id: str, credentials: dict, external_candidate_id: str
    ) -> ChannelResume:
        async def call(token: str):
            resp = await self._http.request(
                "GET",
                "/api/resume/get",
                params={"userId": external_candidate_id},
                headers=self._auth_headers(token),
            )
            self._raise_if_error(resp, "/api/resume/get")
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
                f"前程无忧接口鉴权失败（HTTP 401）: {endpoint}",
                channel=self.channel,
                endpoint=endpoint,
                code=401,
                is_token_invalid=True,
            )
        if resp.status >= 400:
            raise IntegrationApiError(
                f"前程无忧接口请求失败（HTTP {resp.status}）: {endpoint}",
                channel=self.channel,
                endpoint=endpoint,
                code=resp.status,
            )
        data = resp.data or {}
        status = str(data.get("status", ""))
        if status and status != "success":
            code = data.get("statusCode", status)
            raise IntegrationApiError(
                f"前程无忧接口业务错误: {endpoint} status={status} {data.get('errorMsg', '')}",
                channel=self.channel,
                endpoint=endpoint,
                code=code,
                is_token_invalid=str(code) in TOKEN_INVALID_CODES,
            )
