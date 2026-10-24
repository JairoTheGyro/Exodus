"""Repository asset ownership guards for issues #1335 and #6175.

Public Markdown and landing-page media belong in website/, while shared
optional README/packaging imagery belongs in assets/branding/. Retained images
in either managed root must be referenced by tracked text, and every retained
website video must be referenced by the site's entry point. Publication can
operate with no imagery or videos. Explicitly maintained operator guides may
live in docs/ without becoming part of the public Pages site.
"""
import re
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import pytest

REPO = Path(__file__).resolve().parent.parent
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
VIDEO_EXTS = {".webm", ".mp4", ".mov", ".m4v"}
PUBLIC_GUIDES = {
    "agent-migration.md",
    "attachments.md",
    "backup-restore.md",
    "configuration-reference.md",
    "email-outlook.md",
    "pr-blocker-audit.md",
    "security-ci.md",
    "setup.md",
}
# Local deployment/development instructions are maintained with the source,
# not published as Pages guides. Keep exceptions exact: other Markdown and
# all landing-page videos must still live in website/.
OPERATIONAL_GUIDES = {
    "APP_RECREATION.md",
    "CLOUD_DEVELOPMENT.md",
    "EMAIL_SECURITY.md",
    "EXODUS_ROADMAP.md",
    "GO_PUBLIC_AUDIT.md",
    "TRANSLATIONS.md",
    "LOCAL_BACKUPS.md",
    "PHONE_ALERTS.md",
    "PRACTICE_TESTS.md",
    "SERVICES_MANAGER.md",
    "SHARED_SPACES.md",
    "TEAM_ACCOUNTS.md",
    "VAULTWARDEN.md",
}
# Upstream Odysseus engineering records under docs/ (as of the 2026-10-24 sync).
UPSTREAM_DOCS_FALLBACK = {
    "AGENT_TURN_CONTRACT.md",
    "BACKGROUND_TOOL_JOBS.md",
    "CODE_REVIEW_2026-09-16.md",
    "HISTORICAL_ODYSSEUS_QA_QUEUE.md",
    "ODYSSEUS_FIX_WORKSTREAMS.md",
    "ODYSSEUS_SFT_ALEX_CORPUS.md",
    "ODYSSEUS_TOOL_INSTRUCTIONS_EXAMPLE.md",
    "REVIEW_FIX_PROGRESS.md",
    "TYPO_ROUTING_AUDIT_20260909.md",
    "chromadb-volume-migration.md",
    "frontend-architecture/ADR-001-source-and-deployment.md",
    "frontend-architecture/assessment.md",
    "frontend-architecture/handbook.md",
    "frontend-architecture/notes-case-study.md",
    "frontend-architecture/notes-changed-files.md",
    "frontend-architecture/notes-module-inventory.md",
    "frontend-architecture/notes-roadmap.md",
    "frontend-architecture/notes-validation.md",
    "frontend-architecture/validation.md",
    "maintainers/README.md",
    "maintainers/changes-and-review.md",
    "maintainers/documentation.md",
    "maintainers/product-and-features.md",
    "maintainers/review-playbook.md",
    "maintainers/roles-and-access.md",
    "maintainers/testing-and-releases.md",
    "maintainers/triage.md",
    "ref-parity-audit.md",
    "runtime-decomposition/COMPARISON_PROTOCOL.md",
    "runtime-decomposition/WAVE_1_1_RECONCILIATION.md",
    "runtime-decomposition/validation/wave-3-corrective-pass.md",
    "runtime-decomposition/wave-2-request-authority.md",
    "runtime-decomposition/wave-2-validation-full.md",
    "runtime-decomposition/wave-3-browser-authority.md",
    "runtime-decomposition/wave-3-checkpoint-a.md",
    "runtime-decomposition/wave-3-independent-adapters.md",
    "runtime-decomposition/wave-3-resource-identity.md",
    "runtime-decomposition/wave-3-s-delivery-2026-10-01.md",
    "runtime-decomposition/wave-4-effects-provenance-integration.md",
    "runtime-decomposition/wave-5a-browser-lifecycle.md",
    "search-quality-audit-20260917.md",
    "searxng-trust-image.md",
    "skills-audit-architecture.md",
    "skills-audit-second-review.md",
    "skills-lifecycle.md",
    "tls-trust.md",
}
# Files a referenced image name could legitimately appear in.
TEXT_EXTS = {".md", ".html", ".htm", ".js", ".ts", ".css", ".py", ".sh",
             ".json", ".yml", ".yaml", ".txt"}


def _tracked(*paths_under):
    """Git-tracked files under paths, or None if git isn't available."""
    try:
        out = subprocess.run(
            ["git", "ls-files", "--", *paths_under],
            cwd=REPO, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [REPO / line for line in out.stdout.splitlines()
            if line.strip() and (REPO / line).is_file()]


def test_no_orphan_documentation_or_branding_images():
    managed_files = _tracked("website", "assets/branding")
    if managed_files is None:
        pytest.skip("not a git checkout")
    managed_images = [p for p in managed_files if p.suffix.lower() in IMAGE_EXTS]

    # All tracked text we might reference an image from.
    all_tracked = _tracked(".") or []
    haystack = []
    for p in all_tracked:
        if p.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            haystack.append(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    blob = "\n".join(haystack)

    orphans = [
        str(img.relative_to(REPO))
        for img in managed_images
        if img.name not in blob
    ]
    assert not orphans, (
        "unreferenced image(s) committed under website/ or assets/branding/ "
        f"(see #1335 and #6175): {orphans}"
    )


def _upstream_docs():
    """Markdown under docs/ that exists on the upstream Odysseus remote, if known."""
    try:
        out = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "upstream/dev", "--", "docs"],
            cwd=REPO, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        out = ""
    names = {line for line in out.splitlines() if line.endswith(".md")}
    # Without an upstream remote (e.g. CI), fall back to the docs that are not
    # Exodus's own: anything outside the explicit Exodus allowlist that is
    # tracked must then be reviewed by hand.
    return names or {f"docs/{n}" for n in UPSTREAM_DOCS_FALLBACK}


def test_pages_site_owns_its_entrypoint_and_media():
    docs_files = _tracked("docs")
    website_files = _tracked("website")
    if docs_files is None or website_files is None:
        pytest.skip("not a git checkout")

    assert REPO / "website/index.html" in website_files
    assert REPO / "docs/index.html" not in docs_files
    # Upstream keeps its own engineering records in docs/; Exodus's allowlist
    # only governs Markdown that Exodus adds on top of upstream's tree.
    upstream_docs = _upstream_docs()
    unexpected_docs_assets = [
        p for p in docs_files
        if p.suffix.lower() in VIDEO_EXTS
        or (p.suffix.lower() == ".md"
            and p.relative_to(REPO / "docs").as_posix() not in OPERATIONAL_GUIDES
            and p.relative_to(REPO).as_posix() not in upstream_docs)
    ]
    assert not unexpected_docs_assets, unexpected_docs_assets
    for guide in OPERATIONAL_GUIDES:
        assert (REPO / "docs" / guide).is_file(), guide
    assert not [p for p in docs_files if p.name in PUBLIC_GUIDES]

    website_paths = {p.relative_to(REPO / "website").as_posix() for p in website_files}
    assert PUBLIC_GUIDES <= website_paths
    for guide in PUBLIC_GUIDES:
        text = (REPO / "website" / guide).read_text(encoding="utf-8")
        assert text.startswith("---\nlayout: default\n---\n"), guide

    website_videos = [p for p in website_files if p.suffix.lower() in VIDEO_EXTS]

    entrypoint = (REPO / "website/index.html").read_text(encoding="utf-8")
    unreferenced = [
        str(video.relative_to(REPO))
        for video in website_videos
        if video.name not in entrypoint
    ]
    assert not unreferenced, f"unreferenced website video(s): {unreferenced}"

    workflow = (REPO / ".github/workflows/deploy-pages.yml").read_text(encoding="utf-8")
    assert "actions/jekyll-build-pages@" in workflow
    assert "source: website" in workflow
    assert "destination: _site" in workflow
    assert "path: _site" in workflow
    assert "cancel-in-progress: false" in workflow


def test_pages_guides_keep_relative_links_inside_site():
    site_root = (REPO / "website").resolve()

    for guide in sorted(PUBLIC_GUIDES):
        guide_path = REPO / "website" / guide
        text = guide_path.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", text):
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue

            resolved = (guide_path.parent / parsed.path).resolve()
            assert resolved.is_relative_to(site_root), (
                f"{guide} links outside the Pages source: {target}"
            )
            assert resolved.exists(), f"{guide} has a missing local link: {target}"


def test_setup_preserves_docker_go_template_literal():
    setup = (REPO / "website/setup.md").read_text(encoding="utf-8")
    guarded_command = """<!-- {% raw %} -->
```bash
docker info --format '{{.DockerRootDir}}'
```
<!-- {% endraw %} -->"""

    assert guarded_command in setup


def test_preview_encoder_targets_pages_source():
    encoder = (REPO / "scripts/encode_previews.sh").read_text(encoding="utf-8")

    assert "landing page: website/<name>.webm" in encoder
    assert 'OUT_DIR="$(cd "$(dirname "$0")/../website" && pwd)"' in encoder


def test_ci_runs_asset_ownership_guards_for_managed_roots():
    workflow = (REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    match = re.search(r"grep -Ev '([^']+)'", workflow)
    assert match, "expected the docs-only path classifier in CI"
    docs_only = re.compile(match.group(1))

    assert docs_only.match("README.md")
    assert docs_only.match("docs/example.md")
    assert not docs_only.match("website/setup.md")
    assert not docs_only.match("website/new-preview.webm")
    assert not docs_only.match("assets/branding/new-logo.png")


@pytest.mark.parametrize(
    "path",
    [
        "website/favicon.png",
        "website/media/social-card.jpg",
        "website/guides/reference.pdf",
        "assets/branding/new-logo.gif",
        "assets/branding/print/logo.tiff",
    ],
)
def test_managed_site_media_is_not_ignored(path):
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", path],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode == 128:
        pytest.skip("not a git checkout")
    assert result.returncode == 1, f"{path} is unexpectedly ignored"
