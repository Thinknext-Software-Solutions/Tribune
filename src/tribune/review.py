"""LLM-driven review engine.

Takes a PullRequest and an LLMClient, returns a structured ReviewResult.
Handles diff chunking so large PRs don't blow the LLM context window.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .llm import LLMClient
from .schemas import (
    Category,
    FilePatch,
    InlineFinding,
    PullRequest,
    ReviewResult,
    Severity,
    Verdict,
)


logger = logging.getLogger(__name__)


# Soft cap on per-prompt diff size. Real models handle much larger
# contexts, but smaller prompts give sharper reviews.
_MAX_PATCH_CHARS_PER_CHUNK = 30_000
_MAX_FILES_PER_CHUNK = 25


# Files that almost always add noise to reviews. Skipped by default.
_SKIP_PATH_HINTS = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
)


class _LLMSubReview(BaseModel):
    """Structured LLM output for one chunk of files."""

    model_config = ConfigDict(extra="forbid")

    findings: list[InlineFinding] = Field(default_factory=list)
    notes: str = Field(
        default="",
        max_length=2000,
        description="Free-form observations the LLM wants to feed into the final summary.",
    )


class _LLMSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Verdict
    summary: str = Field(..., min_length=10, max_length=4000)


def review_pull_request(
    *,
    pr: PullRequest,
    llm: LLMClient,
    extra_context: Optional[str] = None,
    temperature: float = 0.1,
) -> ReviewResult:
    """Run the LLM review pipeline on a PR.

    Returns a ReviewResult with inline findings and an overall verdict
    + summary.
    """
    review_files = [f for f in pr.files if _should_review(f)]
    skipped = [f.path for f in pr.files if not _should_review(f)]
    if skipped:
        logger.info("tribune.review.skipped", extra={"count": len(skipped)})

    chunks = _chunk_files(review_files)
    logger.info(
        "tribune.review.chunked",
        extra={"file_count": len(review_files), "chunk_count": len(chunks)},
    )

    all_findings: list[InlineFinding] = []
    notes: list[str] = []
    for idx, chunk in enumerate(chunks):
        logger.info("tribune.review.chunk_start", extra={"chunk": idx + 1, "of": len(chunks)})
        sub = _review_chunk(
            pr=pr,
            chunk=chunk,
            llm=llm,
            extra_context=extra_context,
            chunk_index=idx,
            chunk_count=len(chunks),
            temperature=temperature,
        )
        all_findings.extend(sub.findings)
        if sub.notes:
            notes.append(sub.notes)

    summary = _summarize(
        pr=pr,
        findings=all_findings,
        notes="\n\n".join(notes),
        llm=llm,
        temperature=temperature,
    )

    return ReviewResult(
        verdict=summary.verdict,
        summary=summary.summary,
        findings=all_findings,
    )


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


def _should_review(f: FilePatch) -> bool:
    if f.status == "removed":
        return False
    if any(hint in f.path for hint in _SKIP_PATH_HINTS):
        return False
    if not f.patch:
        return False  # binary or oversized files have empty patch
    return True


def _chunk_files(files: list[FilePatch]) -> list[list[FilePatch]]:
    chunks: list[list[FilePatch]] = []
    current: list[FilePatch] = []
    current_size = 0
    for f in files:
        size = len(f.patch)
        if current and (
            current_size + size > _MAX_PATCH_CHARS_PER_CHUNK
            or len(current) >= _MAX_FILES_PER_CHUNK
        ):
            chunks.append(current)
            current = []
            current_size = 0
        current.append(f)
        current_size += size
    if current:
        chunks.append(current)
    if not chunks:
        chunks.append([])
    return chunks


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT = """You are Tribune, a careful and constructive code reviewer.

You are reviewing one chunk of a pull request. Output structured JSON
with inline findings only -- the summary verdict comes from a separate
synthesis step.

Hard rules for findings:
- Anchor every finding to a specific file and a 1-based line number in
  the post-change (right side) file. Read line numbers from the unified
  diff carefully: only lines starting with `+` or unchanged context lines
  count toward the right-side line number.
- severity is one of: blocker, warning, nit
  * blocker: ships a bug, security hole, or breaks an API contract
  * warning: real concern, should be addressed before merge
  * nit: cosmetic, optional, or a small suggestion
- category is one of: bug, security, performance, test, style, docs, design
- Keep the title to one line.
- The body explains the concern AND proposes a fix.
- If you can write the exact replacement code, put it in suggestion as
  raw code (no fences). Otherwise leave suggestion null.

Be concise. Prefer 3 sharp findings over 12 mediocre ones. If the chunk
is clean, return an empty findings list.

Do NOT flag:
- Style differences your linter would catch (assume CI runs linters).
- Personal preferences that are not in the repo's documented conventions.
- Cosmetic naming bikeshedding.
"""


def _review_chunk(
    *,
    pr: PullRequest,
    chunk: list[FilePatch],
    llm: LLMClient,
    extra_context: Optional[str],
    chunk_index: int,
    chunk_count: int,
    temperature: float,
) -> _LLMSubReview:
    if not chunk:
        return _LLMSubReview()

    parts: list[str] = []
    parts.append(f"PR title: {pr.title}")
    if pr.body:
        parts.append(f"PR description:\n{pr.body[:4000]}")
    parts.append(f"Base branch: {pr.base_branch}")
    parts.append(f"Head branch: {pr.head_branch}")
    parts.append(f"Author: {pr.author or '(unknown)'}")
    if extra_context:
        parts.append(f"Extra context:\n{extra_context}")
    parts.append(
        f"This is chunk {chunk_index + 1} of {chunk_count}. "
        f"{len(chunk)} file(s) follow."
    )

    for f in chunk:
        parts.append("")
        parts.append(f"=== FILE: {f.path} ({f.status}, +{f.additions}/-{f.deletions}) ===")
        if f.previous_path and f.previous_path != f.path:
            parts.append(f"(renamed from {f.previous_path})")
        parts.append(f.patch)

    prompt = "\n".join(parts)
    response = llm.structured_call(
        system=_SYSTEM_PROMPT,
        user=prompt,
        schema=_LLMSubReview,
        temperature=temperature,
    )
    return response.parsed


_SUMMARY_SYSTEM = """You are Tribune. You have already produced inline
findings for this pull request. Now write the top-level review summary
and pick the verdict.

verdict rules:
- approve: zero blockers, at most cosmetic warnings, the PR is mergeable as-is
- request_changes: one or more blockers, OR several substantive warnings
  that should be addressed before merge
- comment: ambiguous case, OR no actionable findings but you want to
  surface observations / questions

The summary is 1-3 short paragraphs. Lead with the verdict's headline
implication. Then call out the top 1-3 concerns or wins. Then optional
notes. Do NOT list every finding (they are already inline)."""


def _summarize(
    *,
    pr: PullRequest,
    findings: list[InlineFinding],
    notes: str,
    llm: LLMClient,
    temperature: float,
) -> _LLMSummary:
    n_blocker = sum(1 for f in findings if f.severity == "blocker")
    n_warning = sum(1 for f in findings if f.severity == "warning")
    n_nit = sum(1 for f in findings if f.severity == "nit")

    digest_lines = [
        f"PR: {pr.title}",
        f"Files changed: {len(pr.files)}",
        f"Findings: {n_blocker} blockers, {n_warning} warnings, {n_nit} nits.",
    ]
    if findings:
        digest_lines.append("Top findings:")
        for f in findings[:8]:
            digest_lines.append(f"  [{f.severity}] {f.file}:{f.line}: {f.title}")
    if notes:
        digest_lines.append(f"\nReviewer notes from per-chunk passes:\n{notes}")

    response = llm.structured_call(
        system=_SUMMARY_SYSTEM,
        user="\n".join(digest_lines),
        schema=_LLMSummary,
        temperature=temperature,
    )
    return response.parsed
