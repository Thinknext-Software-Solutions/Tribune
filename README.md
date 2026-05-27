# Tribune

> AI code/PR review agent. Fetches a pull request, asks an LLM to review it, posts inline comments + a verdict back to the VCS.

[![PyPI](https://img.shields.io/pypi/v/tribune-agent.svg?label=PyPI&color=22d3ee)](https://pypi.org/project/tribune-agent/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status](https://img.shields.io/badge/status-alpha-22d3ee.svg)](#)
[![Built by ThinkNext](https://img.shields.io/badge/built%20by-ThinkNext-22d3ee.svg)](https://thinknextsoftware.com)

> **Status**: alpha, live on PyPI as `tribune-agent==0.1.0a1`. Standalone: no inter-package runtime deps. GitHub + GitLab fully implemented in 0.1.0a1; Bitbucket lands in 0.1.0a2; Azure DevOps in 0.1.0a3.

## What it does

```bash
tribune review https://github.com/owner/repo/pull/42
```

Tribune fetches the PR, asks your LLM to review the diff, then posts:

- **Inline comments** anchored to specific file + line, tagged severity (blocker / warning / nit) and category (bug / security / performance / test / style / docs / design).
- **A top-level summary** with a verdict (approve / request_changes / comment-only).

You can also run `--no-post` to print the review to your terminal without touching the PR.

## Why this exists

ThinkNext ships an OSS agentic SDLC stack:

| Stage | Tool |
|---|---|
| Idea to code | [Cascade](https://github.com/Thinknext-Software-Solutions/Cascade) (human-gated) or [Relay](https://github.com/Thinknext-Software-Solutions/Relay) (autonomous) |
| **Code to review** | **Tribune** (this repo) |
| Code to tested running app | [Sentinel](https://github.com/Thinknext-Software-Solutions/Sentinel) |

Tribune is the only piece that touches every PR, regardless of who wrote it. Human, Cascade, Relay, Copilot, anything else.

## Install

```bash
pip install 'tribune-agent[anthropic]'        # or [openai], [google], [claude-code], [all]
```

## Configure

```bash
# LLM provider
tribune configure llm claude_code --set-default
# Or use a key-based provider:
tribune configure llm anthropic --key sk-ant-xxx --set-default

# VCS provider (token needs PR read + comment write scopes)
tribune configure vcs github --token ghp_xxx --set-default
```

Credentials live at `~/.config/tribune/config.yaml` (mode 0600).

## Run

```bash
# Print the review without posting (useful for dogfooding):
tribune review https://github.com/owner/repo/pull/42 --no-post

# Post the review back to the PR:
tribune review https://github.com/owner/repo/pull/42
```

## What ships in 0.1.0a1

| Capability | Status |
|---|---|
| GitHub PRs (read + inline comments + review) | Full |
| GitLab MRs (read + discussions + approve) | Full |
| Bitbucket PRs | Stub (lands in 0.1.0a2) |
| Azure DevOps Repos PRs | Stub (lands in 0.1.0a3) |
| Multi-LLM via vendored client (Anthropic / OpenAI / Google / Claude Code / Ollama) | Full |
| Diff chunking for large PRs | Full |
| Skip lockfiles, removed files, binaries | Full |
| Structured findings (severity + category + line anchor + optional suggestion) | Full |
| GitHub Actions / GitLab CI / Bitbucket Pipelines / Azure Pipelines wrappers | Planned 0.1.0a2 |
| Per-repo `tribune.yaml` (rules to apply, paths to skip, custom prompt) | Planned 0.1.0a2 |

## How it differs from existing tools

| | CodeRabbit / Greptile | GitHub Copilot review | Tribune |
|---|---|---|---|
| Multi-VCS (GitHub + GitLab + Bitbucket + Azure) | Limited | GitHub only | Yes |
| Self-hosted (your code stays on your network) | No | No | Yes |
| Bring your own LLM key | No | No | Yes |
| Free for individuals | Partial | Subscription | Yes |
| Open source | No | No | Yes |

## License

MIT. See [LICENSE](LICENSE).

## About

Built and maintained by [ThinkNext Software Solutions](https://thinknextsoftware.com), alongside [Cascade](https://github.com/Thinknext-Software-Solutions/Cascade), [Relay](https://github.com/Thinknext-Software-Solutions/Relay), and [Sentinel](https://github.com/Thinknext-Software-Solutions/Sentinel).
