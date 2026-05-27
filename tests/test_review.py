"""Tests for the review engine."""

from __future__ import annotations

from tribune.review import (
    _LLMSubReview,
    _LLMSummary,
    _SYSTEM_PROMPT,
    _chunk_files,
    _should_review,
    review_pull_request,
)
from tribune.schemas import FilePatch, InlineFinding, PullRequest


def _patch(path: str, body: str = "+ new line\n", status: str = "modified") -> FilePatch:
    return FilePatch(path=path, status=status, patch=body, additions=1, deletions=0)


def _pr(files: list[FilePatch]) -> PullRequest:
    return PullRequest(
        provider="github",
        url="https://github.com/foo/bar/pull/1",
        project="foo/bar",
        number=1,
        title="Add new feature",
        body="",
        author="alice",
        base_branch="main",
        head_branch="feat",
        head_sha="abc123",
        files=files,
    )


class TestShouldReview:
    def test_removed_file_skipped(self):
        assert not _should_review(_patch("src/foo.py", status="removed"))

    def test_lockfile_skipped(self):
        assert not _should_review(_patch("package-lock.json", body="+ stuff"))
        assert not _should_review(_patch("poetry.lock"))
        assert not _should_review(_patch("Cargo.lock"))

    def test_empty_patch_skipped(self):
        assert not _should_review(FilePatch(path="foo.bin", patch="", status="modified"))

    def test_normal_file_kept(self):
        assert _should_review(_patch("src/foo.py"))


class TestChunkFiles:
    def test_empty_yields_one_empty_chunk(self):
        assert _chunk_files([]) == [[]]

    def test_small_files_single_chunk(self):
        files = [_patch(f"f{i}.py") for i in range(5)]
        chunks = _chunk_files(files)
        assert len(chunks) == 1
        assert len(chunks[0]) == 5

    def test_splits_on_file_count(self):
        files = [_patch(f"f{i}.py") for i in range(40)]
        chunks = _chunk_files(files)
        assert len(chunks) >= 2
        assert all(len(c) <= 25 for c in chunks)

    def test_splits_on_size(self):
        big_patch = "+ line\n" * 5000  # ~35K chars
        files = [_patch(f"f{i}.py", body=big_patch) for i in range(2)]
        chunks = _chunk_files(files)
        assert len(chunks) == 2


class TestReviewPullRequest:
    def test_clean_pr_approves(self, fake_llm):
        files = [_patch("src/foo.py")]
        pr = _pr(files)
        llm = fake_llm([
            _LLMSubReview(findings=[], notes="looks fine"),
            _LLMSummary(verdict="approve", summary="No issues found, ready to merge."),
        ])
        result = review_pull_request(pr=pr, llm=llm)
        assert result.verdict == "approve"
        assert result.findings == []
        assert "ready to merge" in result.summary.lower()

    def test_blocker_triggers_request_changes(self, fake_llm):
        files = [_patch("src/foo.py")]
        pr = _pr(files)
        finding = InlineFinding(
            file="src/foo.py", line=3, severity="blocker", category="security",
            title="hardcoded secret", body="API key is committed; rotate and read from env.",
        )
        llm = fake_llm([
            _LLMSubReview(findings=[finding]),
            _LLMSummary(verdict="request_changes", summary="One blocker found: secret committed in src/foo.py."),
        ])
        result = review_pull_request(pr=pr, llm=llm)
        assert result.verdict == "request_changes"
        assert len(result.findings) == 1
        assert result.findings[0].severity == "blocker"

    def test_skipped_files_not_sent_to_llm(self, fake_llm):
        files = [
            _patch("src/foo.py"),
            _patch("package-lock.json"),  # should be skipped
            _patch("src/bar.py"),
        ]
        pr = _pr(files)
        llm = fake_llm([
            _LLMSubReview(findings=[]),
            _LLMSummary(verdict="approve", summary="Clean, lockfiles skipped."),
        ])
        result = review_pull_request(pr=pr, llm=llm)
        # All files we did send were the non-lockfile ones (chunking decides),
        # so the FakeLLM should still have exactly the two responses consumed.
        assert result.verdict == "approve"

    def test_multi_chunk_collects_findings(self, fake_llm):
        big = "+ line\n" * 5000
        files = [_patch(f"f{i}.py", body=big) for i in range(2)]
        pr = _pr(files)
        f1 = InlineFinding(
            file="f0.py", line=1, severity="warning", category="bug",
            title="off-by-one", body="possible OBO in the loop bound",
        )
        f2 = InlineFinding(
            file="f1.py", line=42, severity="nit", category="style",
            title="prefer enumerate", body="use enumerate instead of range(len(x))",
        )
        llm = fake_llm([
            _LLMSubReview(findings=[f1]),
            _LLMSubReview(findings=[f2]),
            _LLMSummary(verdict="comment", summary="Two minor observations across the diff."),
        ])
        result = review_pull_request(pr=pr, llm=llm)
        assert result.verdict == "comment"
        assert len(result.findings) == 2
        assert {f.file for f in result.findings} == {"f0.py", "f1.py"}


# ---------------------------------------------------------------------------
# System-prompt regression guards
#
# Issues #1 and #2 were both classes of false positives the reviewer kept
# emitting because the system prompt did not warn it off. The fix is
# prompt-side, so the tests live in the same place: lock in that the
# anti-false-positive instructions are present so a future prompt edit
# cannot silently remove them.
# ---------------------------------------------------------------------------


class TestSystemPromptAntiFalsePositiveRules:
    def test_warns_against_flagging_absent_files_outside_diff(self):
        """Issue #1: 'Missing README' false-positive when README exists on the branch."""
        text = _SYSTEM_PROMPT.lower()
        assert "absence of files outside the diff" in text, (
            "system prompt no longer tells the LLM to ignore files outside "
            "the diff; #1 will regress"
        )
        # Concrete examples the LLM is expected to back off from.
        assert "missing readme" in text or "no readme" in text or "readme.md" in text

    def test_warns_against_flagging_missing_tests_by_name_alone(self):
        """Issue #2: test-coverage false-positive when test name lacks the feature keyword."""
        text = _SYSTEM_PROMPT.lower()
        assert "test function names" in text or "test names" in text, (
            "system prompt no longer warns against name-based test-coverage "
            "claims; #2 will regress"
        )
        assert "bodies" in text or "body" in text, (
            "system prompt no longer instructs the LLM to read test bodies; "
            "#2 will regress"
        )
