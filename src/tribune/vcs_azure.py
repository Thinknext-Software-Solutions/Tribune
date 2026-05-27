"""Azure DevOps Repos adapter.

v0.1.0a1 status: stubbed. The class exists so the multi-VCS API surface
is established, but operations raise NotImplementedError with a clear
message pointing at the planned milestone.

Implementation lands in v0.1.0a3. Azure Repos PR API:
https://learn.microsoft.com/en-us/rest/api/azure/devops/git/pull-requests
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from .exceptions import TribuneError
from .schemas import InlineFinding, PullRequest, Verdict
from .vcs import VCSClient


# https://dev.azure.com/<org>/<project>/_git/<repo>/pullrequest/<id>
# https://<org>.visualstudio.com/<project>/_git/<repo>/pullrequest/<id>
_AZ_DEV_URL = re.compile(
    r"^https?://(?P<host>dev\.azure\.com)/(?P<org>[^/]+)/(?P<project>[^/]+)/_git/(?P<repo>[^/]+)/pullrequest/(?P<id>\d+)/?",
    re.IGNORECASE,
)
_AZ_VS_URL = re.compile(
    r"^https?://(?P<org>[^./]+)\.visualstudio\.com/(?P<project>[^/]+)/_git/(?P<repo>[^/]+)/pullrequest/(?P<id>\d+)/?",
    re.IGNORECASE,
)


class AzureDevOpsClient(VCSClient):
    """Adapter for Azure DevOps Repos."""

    provider_name = "azure_devops"

    def __init__(self, token: str, base_url: Optional[str] = None, organization: Optional[str] = None):
        if not token:
            raise TribuneError("Azure DevOps PAT is required.")
        if not organization and not base_url:
            raise TribuneError(
                "Azure DevOps requires either organization name or explicit base_url.",
                hint="Pass organization='myorg' when constructing the client.",
            )
        self._token = token
        self._organization = organization
        self._base = (base_url or f"https://dev.azure.com/{organization}").rstrip("/")

    @classmethod
    def parse_pr_url(cls, url: str) -> Optional[dict]:
        match = _AZ_DEV_URL.match(url) or _AZ_VS_URL.match(url)
        if not match:
            return None
        host = match.groupdict().get("host") or f"{match.group('org')}.visualstudio.com"
        return {
            "project": f"{match.group('org')}/{match.group('project')}/{match.group('repo')}",
            "number": int(match.group("id")),
            "host": host,
        }

    def fetch_pr(self, project: str, number: int) -> PullRequest:
        raise TribuneError(
            "Azure DevOps support is stubbed in v0.1.0a1. Full implementation lands in v0.1.0a3.",
            hint="Use GitHub or GitLab in the meantime.",
        )

    def post_inline_comments(self, *, pr: PullRequest, findings: Sequence[InlineFinding]) -> list[str]:
        raise TribuneError("Azure DevOps support is stubbed in v0.1.0a1.")

    def post_review_summary(self, *, pr: PullRequest, verdict: Verdict, summary_body: str) -> str:
        raise TribuneError("Azure DevOps support is stubbed in v0.1.0a1.")
