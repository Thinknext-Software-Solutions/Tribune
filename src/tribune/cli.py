"""tribune command-line interface."""

from __future__ import annotations

import logging
import sys
from typing import Optional

import click

from . import __version__
from .error_format import echo_error
from .exceptions import TribuneError
from .llm import SUPPORTED_PROVIDERS as SUPPORTED_LLM_PROVIDERS, build_client_from_credentials
from .review import review_pull_request
from .user_config import (
    LLMProviderConfig,
    VCSProviderConfig,
    config_path,
    load_user_config,
    mask_secret,
    resolve_llm_credentials,
    resolve_vcs_credentials,
    save_user_config,
)
from .vcs import VCSClient, detect_provider
from .vcs_azure import AzureDevOpsClient
from .vcs_bitbucket import BitbucketClient
from .vcs_github import GitHubClient
from .vcs_gitlab import GitLabClient


_VCS_REGISTRY: dict[str, type[VCSClient]] = {
    "github": GitHubClient,
    "gitlab": GitLabClient,
    "bitbucket": BitbucketClient,
    "azure_devops": AzureDevOpsClient,
}


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
        stream=sys.stderr,
    )


@click.group()
@click.version_option(__version__, prog_name="tribune")
@click.option("-v", "--verbose", is_flag=True, help="Enable debug-level logs.")
def cli(verbose: bool) -> None:
    """Tribune: AI code/PR review agent."""
    _setup_logging(verbose)


# ---------------------------------------------------------------------------
# tribune review
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("pr_url")
@click.option(
    "--provider",
    type=click.Choice(["github", "gitlab", "bitbucket", "azure_devops"]),
    default=None,
    help="Override VCS provider. Auto-detected from the URL by default.",
)
@click.option(
    "--no-post",
    is_flag=True,
    help="Compute the review but don't post it back to the PR. Prints to stdout instead.",
)
@click.option(
    "--llm-provider",
    default=None,
    help="LLM provider override. Defaults to your user config's default.",
)
@click.option(
    "--llm-model",
    default=None,
    help="LLM model override.",
)
def review(
    pr_url: str,
    provider: Optional[str],
    no_post: bool,
    llm_provider: Optional[str],
    llm_model: Optional[str],
) -> None:
    """Review a pull request URL: fetch diff, ask LLM, post results back."""
    try:
        # 1. Pick VCS provider.
        provider_name = provider or detect_provider(pr_url)
        if provider_name is None:
            raise TribuneError(
                f"Could not detect VCS provider from URL: {pr_url}",
                hint="Pass --provider github|gitlab|bitbucket|azure_devops explicitly.",
            )

        # 2. Load credentials.
        user_cfg = load_user_config()
        llm_creds = resolve_llm_credentials(
            user_config=user_cfg,
            provider=llm_provider,
            model_override=llm_model,
        )
        vcs_creds = resolve_vcs_credentials(user_config=user_cfg, provider=provider_name)

        # 3. Build clients.
        llm = build_client_from_credentials(llm_creds)
        vcs_kwargs: dict = {"token": vcs_creds.token}
        if vcs_creds.base_url:
            vcs_kwargs["base_url"] = vcs_creds.base_url
        if provider_name == "azure_devops" and vcs_creds.organization:
            vcs_kwargs["organization"] = vcs_creds.organization
        vcs: VCSClient = _VCS_REGISTRY[provider_name](**vcs_kwargs)

        # 4. Parse URL into project + number.
        parsed = vcs.parse_pr_url(pr_url)
        if parsed is None:
            raise TribuneError(
                f"URL does not look like a {provider_name} PR URL: {pr_url}",
            )

        # 5. Fetch PR.
        click.echo()
        click.echo(f"==> Tribune review: {pr_url}")
        click.echo(f"    VCS:        {provider_name}")
        click.echo(f"    LLM:        {llm.provider_name} / {llm.model}")
        click.echo()

        pr = vcs.fetch_pr(parsed["project"], parsed["number"])
        click.echo(f"  {pr.title}")
        click.echo(f"    {len(pr.files)} file(s) changed, base={pr.base_branch}, head={pr.head_branch}")
        click.echo()

        # 6. Run review.
        result = review_pull_request(pr=pr, llm=llm)

        # 7. Display.
        _print_result(result)

        # 8. Post back (unless --no-post).
        if no_post:
            click.echo()
            click.echo(click.style("  (--no-post: results not sent to PR)", fg="yellow"))
            return

        click.echo()
        click.echo("  posting findings...")
        urls = vcs.post_inline_comments(pr=pr, findings=result.findings)
        click.echo(f"    {sum(1 for u in urls if u)} inline comment(s) posted")
        summary_url = vcs.post_review_summary(
            pr=pr,
            verdict=result.verdict,
            summary_body=result.summary,
        )
        click.echo(f"    summary: {summary_url}")

    except TribuneError as exc:
        echo_error(exc)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        click.echo(click.style(f"  FAILED: {type(exc).__name__}: {exc}", fg="red"), err=True)
        sys.exit(1)


def _print_result(result) -> None:
    verdict_color = {
        "approve": "green",
        "request_changes": "red",
        "comment": "yellow",
    }[result.verdict]
    icon = {"approve": "✓", "request_changes": "✗", "comment": "·"}[result.verdict]
    click.echo(
        click.style(f"  {icon}  verdict: {result.verdict}", fg=verdict_color, bold=True)
    )
    click.echo()
    click.echo(f"  {result.summary}")
    click.echo()
    n = {"blocker": 0, "warning": 0, "nit": 0}
    for f in result.findings:
        n[f.severity] += 1
    click.echo(
        f"  findings: {n['blocker']} blocker(s), {n['warning']} warning(s), {n['nit']} nit(s)"
    )
    for f in result.findings:
        sev_color = {"blocker": "red", "warning": "yellow", "nit": "white"}[f.severity]
        click.echo(
            click.style(f"    [{f.severity}] ", fg=sev_color)
            + f"{f.file}:{f.line}  ({f.category})  {f.title}"
        )


# ---------------------------------------------------------------------------
# tribune configure
# ---------------------------------------------------------------------------


@cli.group()
def configure() -> None:
    """Set up credentials at ~/.config/tribune/config.yaml."""


@configure.command("show")
def configure_show() -> None:
    """Show effective user config (with secrets masked)."""
    cfg = load_user_config()
    click.echo(f"Config file: {config_path()}")
    click.echo("Defaults:")
    click.echo(f"  llm_provider:  {cfg.defaults.llm_provider}")
    click.echo(f"  vcs_provider:  {cfg.defaults.vcs_provider}")
    click.echo()
    if cfg.llm_providers:
        click.echo("LLM providers:")
        for name, p in cfg.llm_providers.items():
            click.echo(
                f"  {name}: key={mask_secret(p.api_key)} "
                f"model={p.default_model or '(default)'} "
                f"base_url={p.base_url or '(default)'}"
            )
        click.echo()
    if cfg.vcs_providers:
        click.echo("VCS providers:")
        for name, p in cfg.vcs_providers.items():
            click.echo(
                f"  {name}: token={mask_secret(p.token)} "
                f"base_url={p.base_url or '(default)'} "
                f"org={p.organization or '(n/a)'}"
            )


@configure.command("llm")
@click.argument(
    "provider",
    type=click.Choice(list(SUPPORTED_LLM_PROVIDERS), case_sensitive=False),
)
@click.option("--key", default=None, help="API key for this provider.")
@click.option("--model", default=None, help="Default model identifier.")
@click.option("--base-url", default=None, help="Override the API base URL.")
@click.option("--set-default", is_flag=True, help="Make this the default LLM provider.")
def configure_llm(
    provider: str,
    key: Optional[str],
    model: Optional[str],
    base_url: Optional[str],
    set_default: bool,
) -> None:
    """Configure an LLM provider."""
    cfg = load_user_config()
    existing = cfg.llm_providers.get(provider.lower(), LLMProviderConfig())
    updated = LLMProviderConfig(
        api_key=key if key is not None else existing.api_key,
        default_model=model if model is not None else existing.default_model,
        base_url=base_url if base_url is not None else existing.base_url,
    )
    new_providers = dict(cfg.llm_providers)
    new_providers[provider.lower()] = updated
    new_defaults = cfg.defaults.model_copy(
        update={"llm_provider": provider.lower()} if set_default else {}
    )
    new_cfg = cfg.model_copy(update={"llm_providers": new_providers, "defaults": new_defaults})
    save_user_config(new_cfg)
    click.echo(f"Updated LLM provider '{provider}'.")
    if set_default:
        click.echo(f"Set '{provider}' as the default LLM provider.")


@configure.command("vcs")
@click.argument(
    "provider",
    type=click.Choice(["github", "gitlab", "bitbucket", "azure_devops"], case_sensitive=False),
)
@click.option("--token", default=None, help="Access token / PAT / app password.")
@click.option("--base-url", default=None, help="Override the API base URL (for self-hosted).")
@click.option("--organization", default=None, help="Organization name (Azure DevOps).")
@click.option("--set-default", is_flag=True, help="Make this the default VCS provider.")
def configure_vcs(
    provider: str,
    token: Optional[str],
    base_url: Optional[str],
    organization: Optional[str],
    set_default: bool,
) -> None:
    """Configure a VCS provider."""
    cfg = load_user_config()
    existing = cfg.vcs_providers.get(provider.lower(), VCSProviderConfig())
    updated = VCSProviderConfig(
        token=token if token is not None else existing.token,
        base_url=base_url if base_url is not None else existing.base_url,
        organization=organization if organization is not None else existing.organization,
    )
    new_providers = dict(cfg.vcs_providers)
    new_providers[provider.lower()] = updated
    new_defaults = cfg.defaults.model_copy(
        update={"vcs_provider": provider.lower()} if set_default else {}
    )
    new_cfg = cfg.model_copy(update={"vcs_providers": new_providers, "defaults": new_defaults})
    save_user_config(new_cfg)
    click.echo(f"Updated VCS provider '{provider}'.")
    if set_default:
        click.echo(f"Set '{provider}' as the default VCS provider.")


@cli.command()
def version() -> None:
    """Print the Tribune version."""
    click.echo(f"tribune-agent {__version__}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
