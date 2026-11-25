"""The GitHub community files: issue forms, PR template, labels, the label-sync workflow, and the docs they link to.

No YAML library in the dev extras, so the forms are read with a few line rules (enough for GitHub's issue-form
layout we use: top-level keys, ``id:`` lines, ``options:`` lists, ``labels: [...]``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
FORM_NAMES = ("bug_report.yml", "crash_report.yml", "mod_request.yml", "feature_request.yml")
REQUIRED_LABELS = {"bug", "crash", "mod-request", "good first issue", "help wanted", "manifest", "gui", "docs"}


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def form_ids(text: str) -> list[str]:
    return re.findall(r"^\s+id:\s*(\S+)\s*$", text, re.M)


def form_options(text: str, field_id: str) -> list[str]:
    """The ``options:`` of the dropdown with this id."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if re.match(rf"\s+id:\s*{re.escape(field_id)}\s*$", ln))
    out: list[str] = []
    in_opts = False
    for ln in lines[start + 1:]:
        if re.match(r"\s+- type:", ln):
            break
        if ln.strip() == "options:":
            in_opts = True
            continue
        if in_opts:
            m = re.match(r"\s+- (.+)$", ln)
            if not m:
                break
            out.append(m.group(1).strip())
    return out


def labels_json() -> list[dict]:
    return json.loads(_text(ROOT / ".github" / "labels.json"))


@pytest.mark.parametrize("name", FORM_NAMES)
def test_issue_forms_are_well_formed(name):
    text = _text(FORMS / name)
    assert "\t" not in text
    for key in ("name", "description", "body"):
        assert re.search(rf"^{key}:", text, re.M), f"{name}: no top-level {key}"
    ids = form_ids(text)
    assert ids and len(ids) == len(set(ids)), f"{name}: duplicate field ids {ids}"
    assert all(re.fullmatch(r"[a-z][a-z0-9-]*", i) for i in ids), ids
    for ln in text.splitlines():  # two-space indentation throughout
        assert (len(ln) - len(ln.lstrip(" "))) % 2 == 0, f"{name}: odd indentation: {ln!r}"
    types = re.findall(r"^\s+- type:\s*(\S+)", text, re.M)
    assert types and set(types) <= {"markdown", "input", "textarea", "dropdown", "checkboxes"}
    labels = re.search(r"^labels:\s*\[(.*)\]\s*$", text, re.M)
    assert labels, f"{name}: no labels"
    used = {s.strip().strip('"') for s in labels.group(1).split(",")}
    assert used <= {lab["name"] for lab in labels_json()}, f"{name}: labels not in labels.json: {used}"


def test_bug_and_crash_forms_ask_for_the_report_zip_and_story_mode():
    for name in ("bug_report.yml", "crash_report.yml"):
        text = _text(FORMS / name)
        assert "leonida report" in text and "Leonida-report-" in text and "story mode" in text.lower()
        assert {"version", "edition", "build", "pack", "what-happened", "report"} <= set(form_ids(text))
        assert form_options(text, "edition")[:2] == ["GTA V Enhanced", "GTA V Legacy"]


def test_mod_request_form_keeps_the_rules():
    text = _text(FORMS / "mod_request.yml").lower()
    assert "author's own page" in text and "re-upload" in text and "paid" in text and "gta online" in text


def test_issue_chooser_config_links_discussions_and_docs():
    text = _text(FORMS / "config.yml")
    assert re.search(r"^blank_issues_enabled:\s*false", text, re.M)
    urls = re.findall(r"url:\s*(\S+)", text)
    assert "https://github.com/JacobJandon/leonida-v/discussions" in urls
    assert any(u.endswith("/docs/GUIDE.md") for u in urls)
    for u in urls:
        assert u.startswith("https://github.com/JacobJandon/leonida-v/")
        doc = re.search(r"/blob/main/(.+)$", u)
        if doc:
            assert (ROOT / doc.group(1)).is_file(), u


def test_pull_request_template_has_the_checklist():
    text = _text(ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md")
    for must in ("pytest", "ruff check", "Installer", "leonida/manifest/", "No mod files", "author's own",
                 "story mode"):
        assert must in text, must


def test_labels_json():
    labels = labels_json()
    names = [lab["name"] for lab in labels]
    assert len(names) == len(set(names)) and set(names) >= REQUIRED_LABELS
    for lab in labels:
        assert set(lab) <= {"name", "color", "description"}
        assert re.fullmatch(r"[0-9a-f]{6}", lab["color"]), lab
        assert len(lab.get("description", "")) <= 100  # GitHub's limit


def test_label_sync_workflow_uses_the_built_in_token_on_main_only():
    text = _text(ROOT / ".github" / "workflows" / "labels.yml")
    assert "pull_request" not in text and "${{ secrets." not in text
    assert re.search(r"push:\s*\n\s+branches:\s*\[main\]", text)
    assert re.search(r"^\s+issues:\s*write", text, re.M) and "github.token" in text
    assert ".github/labels.json" in text


def test_ci_runs_for_pull_requests_without_secrets():
    text = _text(ROOT / ".github" / "workflows" / "ci.yml")
    assert re.search(r"^\s+pull_request:", text, re.M)
    assert re.search(r"^permissions:\s*\n\s+contents:\s*read", text, re.M)  # read-only by default
    assert "${{ secrets." not in text


DOCS = ("README.md", "CONTRIBUTING.md", "SUPPORT.md", "SECURITY.md", "CODE_OF_CONDUCT.md", "docs/ADDING-MODS.md")


@pytest.mark.parametrize("doc", DOCS)
def test_community_docs_relative_links_resolve(doc):
    path = ROOT / doc
    text = re.sub(r"```.*?```", "", _text(path), flags=re.S)  # no links inside code blocks
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"(https?:|mailto:|#)", target):
            continue
        file = target.split("#", 1)[0]
        assert (path.parent / file).exists(), f"{doc}: broken link {target}"


def test_contributing_covers_setup_rules_and_layout():
    text = _text(ROOT / "CONTRIBUTING.md")
    for must in ("build\\dev_setup.ps1", "pip install -e \".[dev,gui]\"", "pytest -q", "ruff check .", "leonida-gui",
                 "docs/ADDING-MODS.md", "Never add or re-host mod files", "Story mode only", "Installer",
                 "good first issue", "build/README.md"):
        assert must in text, must
    assert (ROOT / "build" / "dev_setup.ps1").is_file()


def test_dev_setup_script_installs_dev_and_gui_and_runs_the_tests():
    text = _text(ROOT / "build" / "dev_setup.ps1")
    assert '-m pip install -e ".[dev,gui]"' in text and "-m pytest -q" in text and "-m ruff check ." in text
    assert "QT_QPA_PLATFORM" in text and "LEONIDA_NO_NET" in text
