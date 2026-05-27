"""Pydantic schemas shared across review engine + VCS adapters.

The review engine produces a `ReviewResult` containing inline
findings + an overall summary verdict. Each VCS adapter knows how
to render that into provider-specific API calls.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Pull request representation (VCS-agnostic)
# ---------------------------------------------------------------------------


class FilePatch(BaseModel):
    """One file's change in a PR. Patch is unified diff."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(..., description="File path relative to repo root")
    status: Literal["added", "modified", "removed", "renamed"] = "modified"
    patch: str = Field(default="", description="Unified diff body. Empty for binary / very large files.")
    additions: int = 0
    deletions: int = 0
    previous_path: Optional[str] = Field(default=None, description="Set when status is 'renamed'")


class PullRequest(BaseModel):
    """A normalized view of a pull request across VCS providers."""

    model_config = ConfigDict(extra="forbid")

    provider: Literal["github", "gitlab", "bitbucket", "azure_devops"]
    url: str
    project: str = Field(..., description="owner/repo or namespace/project depending on provider")
    number: int
    title: str
    body: str = ""
    author: str = ""
    base_branch: str
    head_branch: str
    head_sha: str
    files: list[FilePatch] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Review output
# ---------------------------------------------------------------------------


Severity = Literal["blocker", "warning", "nit"]
Category = Literal["bug", "security", "performance", "test", "style", "docs", "design"]
Verdict = Literal["approve", "request_changes", "comment"]


class InlineFinding(BaseModel):
    """One concern anchored to a specific line in a specific file."""

    model_config = ConfigDict(extra="forbid")

    file: str = Field(..., description="File path the finding refers to")
    line: int = Field(..., ge=1, description="1-based line number in the new (post-change) file")
    side: Literal["right", "left"] = Field(
        default="right",
        description="'right' = new file (the change), 'left' = old file (rare for review)",
    )
    severity: Severity
    category: Category
    title: str = Field(..., min_length=3, max_length=200, description="One-line summary of the concern")
    body: str = Field(..., min_length=10, max_length=4000, description="Explanation + suggested fix")
    suggestion: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Optional code suggestion to apply (raw code, no fences)",
    )


class ReviewResult(BaseModel):
    """The reviewer's full output for a single PR."""

    model_config = ConfigDict(extra="forbid")

    verdict: Verdict = Field(..., description="approve / request_changes / comment-only")
    summary: str = Field(
        ...,
        min_length=10,
        max_length=4000,
        description="Top-level review comment. Explains the verdict in 1-3 paragraphs.",
    )
    findings: list[InlineFinding] = Field(
        default_factory=list,
        description="Per-line concerns. May be empty if the PR is clean.",
    )

    def blockers(self) -> list[InlineFinding]:
        return [f for f in self.findings if f.severity == "blocker"]

    def warnings(self) -> list[InlineFinding]:
        return [f for f in self.findings if f.severity == "warning"]

    def nits(self) -> list[InlineFinding]:
        return [f for f in self.findings if f.severity == "nit"]
