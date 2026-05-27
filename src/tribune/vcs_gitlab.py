"""GitLab adapter (cloud + self-hosted).

Uses GitLab's REST API directly (no python-gitlab dependency to keep
the runtime footprint small). Only the four core operations are
implemented.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Sequence
from urllib.parse import quote, urlparse

from .exceptions import TribuneError
from .schemas import FilePatch, InlineFinding, PullRequest, Verdict
from .vcs import VCSClient


logger = logging.getLogger(__name__)


# Matches both gitlab.com and self-hosted GitLab MR URLs.
#   https://gitlab.com/group/subgroup/project/-/merge_requests/42
_GL_MR_URL = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<path>.+?)/-/merge_requests/(?P<iid>\d+)/?",
    re.IGNORECASE,
)


class GitLabClient(VCSClient):
    """Adapter for GitLab cloud and self-hosted."""

    provider_name = "gitlab"

    def __init__(self, token: str, base_url: Optional[str] = None):
        try:
            import httpx  # noqa: F401
        except ImportError as exc:
            raise TribuneError(
                "httpx is not installed.",
                hint="pip install tribune-agent",
            ) from exc

        if not token:
            raise TribuneError("GitLab token is required.")
        self._token = token
        self._base = (base_url or "https://gitlab.com").rstrip("/")

    @classmethod
    def parse_pr_url(cls, url: str) -> Optional[dict]:
        match = _GL_MR_URL.match(url)
        if not match:
            return None
        return {
            "project": match.group("path"),
            "number": int(match.group("iid")),
            "host": match.group("host"),
        }

    # GitLab calls the project ID "URL-encoded path" everywhere. Helper:
    @staticmethod
    def _proj(project: str) -> str:
        return quote(project, safe="")

    def _client(self):
        import httpx
        return httpx.Client(
            base_url=self._base,
            headers={"PRIVATE-TOKEN": self._token},
            timeout=30.0,
        )

    def fetch_pr(self, project: str, number: int) -> PullRequest:
        proj = self._proj(project)
        with self._client() as c:
            mr_res = c.get(f"/api/v4/projects/{proj}/merge_requests/{number}")
            if mr_res.status_code != 200:
                raise TribuneError(
                    f"Could not fetch MR {project}!{number}: HTTP {mr_res.status_code} {mr_res.text[:160]}"
                )
            mr = mr_res.json()

            diff_res = c.get(
                f"/api/v4/projects/{proj}/merge_requests/{number}/diffs",
                params={"per_page": 100},
            )
            diffs = diff_res.json() if diff_res.status_code == 200 else []

        files: list[FilePatch] = []
        for d in diffs:
            status: str = "modified"
            if d.get("new_file"):
                status = "added"
            elif d.get("deleted_file"):
                status = "removed"
            elif d.get("renamed_file"):
                status = "renamed"
            files.append(
                FilePatch(
                    path=d.get("new_path") or d.get("old_path") or "",
                    status=status,  # type: ignore[arg-type]
                    patch=(d.get("diff") or "")[:200_000],
                    additions=0,
                    deletions=0,
                    previous_path=d.get("old_path") if status == "renamed" else None,
                )
            )

        return PullRequest(
            provider="gitlab",
            url=mr.get("web_url", ""),
            project=project,
            number=number,
            title=mr.get("title", ""),
            body=mr.get("description", "") or "",
            author=(mr.get("author") or {}).get("username", ""),
            base_branch=mr.get("target_branch", ""),
            head_branch=mr.get("source_branch", ""),
            head_sha=mr.get("sha", ""),
            files=files,
        )

    def post_inline_comments(
        self,
        *,
        pr: PullRequest,
        findings: Sequence[InlineFinding],
    ) -> list[str]:
        if not findings:
            return []
        proj = self._proj(pr.project)
        posted: list[str] = []
        with self._client() as c:
            # Fetch the latest diff_refs from versions API; required for
            # position-based inline comments.
            versions_res = c.get(
                f"/api/v4/projects/{proj}/merge_requests/{pr.number}/versions"
            )
            diff_refs: dict = {}
            if versions_res.status_code == 200:
                versions = versions_res.json()
                if versions:
                    v0 = versions[0]
                    diff_refs = {
                        "base_sha": v0.get("base_commit_sha"),
                        "start_sha": v0.get("start_commit_sha"),
                        "head_sha": v0.get("head_commit_sha"),
                    }

            for finding in findings:
                body_md = _format_inline_body(finding)
                position = {
                    "position_type": "text",
                    "new_path": finding.file,
                    "old_path": finding.file,
                    "new_line": finding.line,
                    **diff_refs,
                }
                res = c.post(
                    f"/api/v4/projects/{proj}/merge_requests/{pr.number}/discussions",
                    json={"body": body_md, "position": position},
                )
                if res.status_code in (200, 201):
                    posted.append(pr.url)
                else:
                    logger.warning(
                        "tribune.vcs.gitlab.inline_comment_failed",
                        extra={"file": finding.file, "line": finding.line,
                               "status": res.status_code, "body": res.text[:200]},
                    )
                    posted.append("")
        return posted

    def post_review_summary(
        self,
        *,
        pr: PullRequest,
        verdict: Verdict,
        summary_body: str,
    ) -> str:
        proj = self._proj(pr.project)
        with self._client() as c:
            # GitLab does not have GitHub-style review events. We always
            # post a discussion (top-level comment) and additionally
            # approve / unapprove based on verdict.
            res = c.post(
                f"/api/v4/projects/{proj}/merge_requests/{pr.number}/notes",
                json={"body": _summary_with_verdict_prefix(verdict, summary_body)},
            )
            if res.status_code not in (200, 201):
                raise TribuneError(
                    f"Could not post MR comment: HTTP {res.status_code} {res.text[:160]}"
                )
            if verdict == "approve":
                c.post(f"/api/v4/projects/{proj}/merge_requests/{pr.number}/approve")
            elif verdict == "request_changes":
                # GitLab CE has no "request changes" primitive; the
                # comment + lack of approval is the signal.
                pass
            return pr.url


def _format_inline_body(finding: InlineFinding) -> str:
    badge = {"blocker": "**blocker**", "warning": "**warning**", "nit": "nit"}[finding.severity]
    parts = [f"{badge} · {finding.category} — {finding.title}", "", finding.body]
    if finding.suggestion:
        parts += ["", "```suggestion", finding.suggestion.rstrip(), "```"]
    return "\n".join(parts)


def _summary_with_verdict_prefix(verdict: Verdict, body: str) -> str:
    prefix = {
        "approve": "**Tribune verdict: approve**",
        "request_changes": "**Tribune verdict: request changes**",
        "comment": "**Tribune verdict: comment-only**",
    }[verdict]
    return f"{prefix}\n\n{body}"
