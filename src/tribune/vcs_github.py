"""GitHub adapter using PyGithub.

Implements the four core operations defined in tribune.vcs.VCSClient:
parse_pr_url, fetch_pr, post_inline_comments, post_review_summary.
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Sequence
from urllib.parse import urlparse

from .exceptions import TribuneError
from .schemas import FilePatch, InlineFinding, PullRequest, Verdict
from .vcs import VCSClient


logger = logging.getLogger(__name__)


_GH_PR_URL = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)/?"
)


class GitHubClient(VCSClient):
    """Adapter for github.com and GitHub Enterprise Server."""

    provider_name = "github"

    def __init__(self, token: str, base_url: Optional[str] = None):
        try:
            from github import Auth, Github  # type: ignore
        except ImportError as exc:
            raise TribuneError(
                "PyGithub is not installed.",
                hint="pip install tribune-agent (PyGithub is a runtime dependency).",
            ) from exc

        if not token:
            raise TribuneError("GitHub token is required.")

        kwargs = {"auth": Auth.Token(token)}
        if base_url:
            kwargs["base_url"] = base_url.rstrip("/")
        self._gh = Github(**kwargs)

    @classmethod
    def parse_pr_url(cls, url: str) -> Optional[dict]:
        match = _GH_PR_URL.match(url)
        if not match:
            return None
        host = match.group("host").lower()
        if host not in ("github.com", "www.github.com") and "github" not in host:
            # Probably GitHub Enterprise; accept conservatively.
            pass
        return {
            "project": f"{match.group('owner')}/{match.group('repo')}",
            "number": int(match.group("number")),
            "host": host,
        }

    def fetch_pr(self, project: str, number: int) -> PullRequest:
        try:
            repo = self._gh.get_repo(project)
            pr = repo.get_pull(number)
        except Exception as exc:
            raise TribuneError(
                f"Could not fetch {project}#{number} from GitHub: {exc}",
                hint="Check that the token has 'repo' scope and the PR exists.",
            ) from exc

        files: list[FilePatch] = []
        try:
            for f in pr.get_files():
                status_raw = (f.status or "modified").lower()
                if status_raw == "removed":
                    status: str = "removed"
                elif status_raw == "added":
                    status = "added"
                elif status_raw == "renamed":
                    status = "renamed"
                else:
                    status = "modified"
                files.append(
                    FilePatch(
                        path=f.filename,
                        status=status,  # type: ignore[arg-type]
                        patch=(f.patch or "")[:200_000],
                        additions=int(f.additions or 0),
                        deletions=int(f.deletions or 0),
                        previous_path=getattr(f, "previous_filename", None),
                    )
                )
        except Exception as exc:
            logger.warning("tribune.vcs.github.files_fetch_partial", extra={"err": str(exc)})

        return PullRequest(
            provider="github",
            url=pr.html_url,
            project=project,
            number=number,
            title=pr.title or "",
            body=pr.body or "",
            author=(pr.user.login if pr.user else ""),
            base_branch=pr.base.ref,
            head_branch=pr.head.ref,
            head_sha=pr.head.sha,
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
        try:
            repo = self._gh.get_repo(pr.project)
            gh_pr = repo.get_pull(pr.number)
        except Exception as exc:
            raise TribuneError(f"Could not load PR for inline comments: {exc}") from exc

        commit = repo.get_commit(pr.head_sha)
        posted: list[str] = []
        for finding in findings:
            body = _format_inline_body(finding)
            try:
                comment = gh_pr.create_review_comment(
                    body=body,
                    commit=commit,
                    path=finding.file,
                    line=finding.line,
                    side="RIGHT" if finding.side == "right" else "LEFT",
                )
                posted.append(getattr(comment, "html_url", ""))
            except Exception as exc:
                logger.warning(
                    "tribune.vcs.github.inline_comment_failed",
                    extra={"file": finding.file, "line": finding.line, "err": str(exc)[:160]},
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
        try:
            repo = self._gh.get_repo(pr.project)
            gh_pr = repo.get_pull(pr.number)
            event = _verdict_to_event(verdict)
            review = gh_pr.create_review(body=summary_body, event=event)
            return getattr(review, "html_url", pr.url)
        except Exception as exc:
            # Fall back to a plain comment if review submission fails (e.g.
            # the token can't approve the user's own PR).
            try:
                comment = gh_pr.create_issue_comment(
                    body=f"_(Tribune review fallback comment)_\n\n{summary_body}"
                )
                return getattr(comment, "html_url", pr.url)
            except Exception as exc2:
                raise TribuneError(
                    f"Could not post review summary: {exc}; fallback also failed: {exc2}"
                ) from exc


def _verdict_to_event(verdict: Verdict) -> str:
    return {
        "approve": "APPROVE",
        "request_changes": "REQUEST_CHANGES",
        "comment": "COMMENT",
    }[verdict]


def _format_inline_body(finding: InlineFinding) -> str:
    """Markdown body for an inline review comment."""
    badge = {
        "blocker": "🚫 blocker",
        "warning": "⚠ warning",
        "nit": "· nit",
    }[finding.severity]
    parts = [f"**{badge} · {finding.category}** — {finding.title}", "", finding.body]
    if finding.suggestion:
        parts += ["", "```suggestion", finding.suggestion.rstrip(), "```"]
    return "\n".join(parts)
