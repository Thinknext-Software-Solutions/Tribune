"""Tests for VCS URL parsing + provider detection."""

from __future__ import annotations

import pytest

from tribune.vcs import detect_provider
from tribune.vcs_azure import AzureDevOpsClient
from tribune.vcs_bitbucket import BitbucketClient
from tribune.vcs_github import GitHubClient
from tribune.vcs_gitlab import GitLabClient


class TestDetectProvider:
    @pytest.mark.parametrize("url,expected", [
        ("https://github.com/foo/bar/pull/42", "github"),
        ("https://gitlab.com/foo/bar/-/merge_requests/7", "gitlab"),
        ("https://gitlab.internal.example.com/group/project/-/merge_requests/9", "gitlab"),
        ("https://bitbucket.org/team/repo/pull-requests/3", "bitbucket"),
        ("https://dev.azure.com/myorg/myproj/_git/myrepo/pullrequest/5", "azure_devops"),
        ("https://myorg.visualstudio.com/myproj/_git/myrepo/pullrequest/5", "azure_devops"),
    ])
    def test_detect(self, url, expected):
        assert detect_provider(url) == expected

    def test_unknown_returns_none(self):
        assert detect_provider("https://example.com/some/path") is None


class TestGitHubParseURL:
    def test_basic(self):
        out = GitHubClient.parse_pr_url("https://github.com/foo/bar/pull/42")
        assert out == {"project": "foo/bar", "number": 42, "host": "github.com"}

    def test_trailing_slash(self):
        out = GitHubClient.parse_pr_url("https://github.com/foo/bar/pull/42/")
        assert out["number"] == 42

    def test_enterprise_host(self):
        out = GitHubClient.parse_pr_url(
            "https://github.acme.corp/team/repo/pull/100"
        )
        assert out is not None
        assert out["project"] == "team/repo"
        assert out["number"] == 100

    def test_unknown_url(self):
        assert GitHubClient.parse_pr_url("https://gitlab.com/foo/bar/-/merge_requests/1") is None


class TestGitLabParseURL:
    def test_basic(self):
        out = GitLabClient.parse_pr_url("https://gitlab.com/group/project/-/merge_requests/9")
        assert out == {"project": "group/project", "number": 9, "host": "gitlab.com"}

    def test_subgroup(self):
        out = GitLabClient.parse_pr_url(
            "https://gitlab.com/a/b/c/d/-/merge_requests/100"
        )
        assert out["project"] == "a/b/c/d"
        assert out["number"] == 100

    def test_unknown_url(self):
        assert GitLabClient.parse_pr_url("https://github.com/foo/bar/pull/1") is None


class TestBitbucketParseURL:
    def test_basic(self):
        out = BitbucketClient.parse_pr_url(
            "https://bitbucket.org/team/repo/pull-requests/3"
        )
        assert out == {"project": "team/repo", "number": 3, "host": "bitbucket.org"}


class TestAzureParseURL:
    def test_dev_azure(self):
        out = AzureDevOpsClient.parse_pr_url(
            "https://dev.azure.com/myorg/myproj/_git/myrepo/pullrequest/5"
        )
        assert out["project"] == "myorg/myproj/myrepo"
        assert out["number"] == 5

    def test_visualstudio_legacy(self):
        out = AzureDevOpsClient.parse_pr_url(
            "https://myorg.visualstudio.com/myproj/_git/myrepo/pullrequest/12"
        )
        assert out["project"] == "myorg/myproj/myrepo"
        assert out["number"] == 12
