import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIRECTORY = REPOSITORY_ROOT / ".github" / "workflows"
EXTERNAL_ACTION_PATTERN = re.compile(
    r"^\s*uses:\s*(?!\./)(?P<action>[^\s@]+)@(?P<reference>[^\s#]+)",
    re.MULTILINE,
)
FULL_COMMIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
PRODUCTION_WORKFLOW_PATH = WORKFLOWS_DIRECTORY / "prod-docker-release.yml"


def test_external_github_actions_are_pinned_to_full_commit_shas() -> None:
    unpinned_actions: list[str] = []

    for workflow_path in sorted(WORKFLOWS_DIRECTORY.glob("*.yml")):
        workflow = workflow_path.read_text(encoding="utf-8")
        for match in EXTERNAL_ACTION_PATTERN.finditer(workflow):
            reference = match.group("reference")
            if FULL_COMMIT_SHA_PATTERN.fullmatch(reference) is None:
                unpinned_actions.append(
                    f"{workflow_path.name}: {match.group('action')}@{reference}"
                )

    assert unpinned_actions == [], (
        "External GitHub Actions must use immutable 40-character commit SHAs: "
        + ", ".join(unpinned_actions)
    )


def test_production_release_uses_one_exact_release_tag_source() -> None:
    workflow = PRODUCTION_WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "ref: main" not in workflow
    assert "github.ref_name" not in workflow
    assert "release_tag:" in workflow
    assert "required: true" in workflow
    assert (
        "RELEASE_TAG: ${{ github.event_name == 'release' "
        "&& github.event.release.tag_name || inputs.release_tag }}"
    ) in workflow
    assert "ref: ${{ env.RELEASE_TAG }}" in workflow
    assert "tag_name: ${{ env.RELEASE_TAG }}" in workflow
    assert "BUILD_BRANCH=${{ env.RELEASE_TAG }}" in workflow
    assert "BUILD_TAG=${{ env.RELEASE_TAG }}" in workflow
    assert "contents: write" in workflow
    assert "packages: write" in workflow
    assert "cancel-in-progress: false" in workflow
