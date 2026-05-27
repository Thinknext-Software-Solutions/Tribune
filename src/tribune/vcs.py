"""VCS provider abstraction.

Every supported VCS (GitHub, GitLab, Bitbucket, Azure DevOps) implements
this interface so the review engine can stay provider-agnostic. The
operations are deliberately narrow: fetch a PR, fetch its diff, post
inline comments, post the summary review.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Sequence

from .schemas import InlineFinding, PullRequest, Verdict


SUPPORTED_PROVIDERS: tuple[str, ...] = ("github", "gitlab", "bitbucket", "azure_devops")


class VCSClient(ABC):
    """Abstract base for VCS adapters.

    Each concrete subclass is constructed with provider-specific
    credentials and a base URL (for self-hosted variants).
    """

    provider_name: str = ""

    @classmethod
    @abstractmethod
    def parse_pr_url(cls, url: str) -> Optional[dict]:
        """Return {project, number} if the URL is for this provider; else None."""

    @abstractmethod
    def fetch_pr(self, project: str, number: int) -> PullRequest:
        """Fetch the PR's metadata + file list (with patches)."""

    @abstractmethod
    def post_inline_comments(
        self,
        *,
        pr: PullRequest,
        findings: Sequence[InlineFinding],
    ) -> list[str]:
        """Post one comment per finding, anchored to its file+line.

        Returns the URLs of the posted comments (best-effort; may be empty
        strings if the provider does not surface a comment URL).
        """

    @abstractmethod
    def post_review_summary(
        self,
        *,
        pr: PullRequest,
        verdict: Verdict,
        summary_body: str,
    ) -> str:
        """Post the top-level review (approve / request changes / comment).

        Returns the URL of the posted review or summary comment.
        """


def detect_provider(url: str) -> Optional[str]:
    """Sniff which provider a PR URL belongs to.

    Heuristic: hostname-based plus URL-shape hints.
    """
    lowered = url.lower()
    if "github.com" in lowered or "/pull/" in lowered:
        return "github"
    if "gitlab" in lowered or "/-/merge_requests/" in lowered or "/merge_requests/" in lowered:
        return "gitlab"
    if "bitbucket.org" in lowered or "/pull-requests/" in lowered:
        return "bitbucket"
    if "dev.azure.com" in lowered or "visualstudio.com" in lowered or "/pullrequest/" in lowered:
        return "azure_devops"
    return None
