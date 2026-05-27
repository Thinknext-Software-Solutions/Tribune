"""Bitbucket Cloud adapter.

v0.1.0a1 status: stubbed. The class exists so the multi-VCS API surface
is established, but operations raise NotImplementedError with a clear
message pointing at the planned milestone.

Implementation lands in v0.1.0a2. Bitbucket's PR review API is
documented at:
https://developer.atlassian.com/cloud/bitbucket/rest/api-group-pullrequests/
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from .exceptions import TribuneError
from .schemas import InlineFinding, PullRequest, Verdict
from .vcs import VCSClient


# https://bitbucket.org/<workspace>/<repo>/pull-requests/<id>
_BB_PR_URL = re.compile(
    r"^https?://(?P<host>bitbucket\.org)/(?P<workspace>[^/]+)/(?P<repo>[^/]+)/pull-requests/(?P<id>\d+)/?",
    re.IGNORECASE,
)


class BitbucketClient(VCSClient):
    """Adapter for Bitbucket Cloud."""

    provider_name = "bitbucket"

    def __init__(self, token: str, base_url: Optional[str] = None):
        if not token:
            raise TribuneError("Bitbucket app password is required.")
        self._token = token
        self._base = (base_url or "https://api.bitbucket.org").rstrip("/")

    @classmethod
    def parse_pr_url(cls, url: str) -> Optional[dict]:
        match = _BB_PR_URL.match(url)
        if not match:
            return None
        return {
            "project": f"{match.group('workspace')}/{match.group('repo')}",
            "number": int(match.group("id")),
            "host": match.group("host"),
        }

    def fetch_pr(self, project: str, number: int) -> PullRequest:
        raise TribuneError(
            "Bitbucket support is stubbed in v0.1.0a1. Full implementation lands in v0.1.0a2.",
            hint="Use GitHub or GitLab in the meantime, or file an issue to bump priority.",
        )

    def post_inline_comments(self, *, pr: PullRequest, findings: Sequence[InlineFinding]) -> list[str]:
        raise TribuneError("Bitbucket support is stubbed in v0.1.0a1.")

    def post_review_summary(self, *, pr: PullRequest, verdict: Verdict, summary_body: str) -> str:
        raise TribuneError("Bitbucket support is stubbed in v0.1.0a1.")
