"""The path the CLI is told to write must be one the CLI can actually write.

Regression guard for a defect measured 2026-10-06. CLAUDE_CONFIG_DIR is
D:\\.claude and this project lives inside it, so the child `claude` CLI cannot
create a file anywhere under the project — a probe Write was denied under both
`dontAsk` and `acceptEdits`, and `--add-dir <project>` did not help, while the
same probe in %TEMP% succeeded. Both domains were nonetheless telling the model
to write to reports/<domain>/drafts/, so every run ended with

    Report draft rejected: Draft file not found

while the CLI itself exited 0 — a silent, unattended failure. Drafts are still
archived into the project by Python, which is an ordinary process and is not
restricted.
"""
import ast
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "spider_core"))
from core.output_utils import agent_draft_staging_dir, archive_agent_draft  # noqa: E402

DOMAINS = {
    "ai": ROOT / "generate_report.py",
    "cognition": ROOT / "domains/cognition/curator.py",
}


def module_source(path):
    return path.read_text(encoding="utf-8")


def produced_names(tree):
    """Names whose value traces back to agent_draft_staging_dir(...).

    Follows aliases to a fixed point, because the module may hold the staging
    directory in one variable and derive the file paths from it
    (`staging_draft = staging_dir / name`) — the derivation is exactly what a
    direct-call-only check would miss.
    """
    assignments = [node for node in ast.walk(tree)
                   if isinstance(node, ast.Assign)
                   and all(isinstance(t, ast.Name) for t in node.targets)]
    produced = set()
    for _ in range(len(assignments) + 1):
        added = set()
        for node in assignments:
            names = {t.id for t in node.targets}
            if names & produced:
                continue
            names_in_value = {s.id for s in ast.walk(node.value) if isinstance(s, ast.Name)}
            # The value may be a BinOp (`agent_draft_staging_dir(d) / name`), so
            # look for the call anywhere inside it, not just at its head.
            calls_staging = any(
                isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id == "agent_draft_staging_dir"
                for sub in ast.walk(node.value))
            if calls_staging or names_in_value & produced:
                added |= names
        if not added:
            break
        produced |= added
    return produced


def staging_variable(path):
    """Name of the variable both produced by agent_draft_staging_dir(...) and
    handed to the prompt, or None if the two are not wired to each other."""
    tree = ast.parse(module_source(path))
    produced = produced_names(tree)

    # generate_report.py interpolates the path into the prompt f-string;
    # curator.py passes it to build_prompt(). Either way the handler is the
    # module's own function, so scan every call/JoinedStr for those names.
    handed_over = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "build_prompt":
            handed_over.update(a.id for a in node.args if isinstance(a, ast.Name))
        if isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
                    handed_over.add(part.value.id)
    return next(iter(produced & handed_over), None)


class DraftStagingTests(unittest.TestCase):
    def test_staging_is_outside_the_project(self):
        """A path inside the project is one the child CLI cannot write."""
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                staging = agent_draft_staging_dir(domain)
                self.assertFalse(staging.is_relative_to(ROOT),
                                 f"{domain} stages drafts inside the project")

    def test_staging_is_outside_the_agent_config_dir(self):
        """The project sits under CLAUDE_CONFIG_DIR; anything under it is
        unwritable by the child no matter how the path is spelled."""
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        if not config_dir:
            self.skipTest("CLAUDE_CONFIG_DIR is not set in this environment")
        for domain in DOMAINS:
            with self.subTest(domain=domain):
                self.assertFalse(
                    agent_draft_staging_dir(domain).is_relative_to(Path(config_dir)),
                    f"{domain} stages drafts under CLAUDE_CONFIG_DIR")

    def test_each_domain_prompts_the_cli_with_the_staging_path(self):
        for domain, path in DOMAINS.items():
            with self.subTest(domain=domain):
                # The variable the prompt receives must be the one produced by
                # agent_draft_staging_dir(); handing it the in-project draft_file
                # is what made the CLI fail with "Draft file not found".
                self.assertIsNotNone(
                    staging_variable(path),
                    f"{domain} does not pass the staged path to the prompt — the "
                    f"CLI would be told to write an in-project draft it cannot create")

    def test_the_candidate_list_is_staged_too(self):
        """Stage 1's output goes through the child as well, so it needs the same
        treatment as the draft — a path inside the project is one the CLI cannot
        create, and the failure would again be silent."""
        tree = ast.parse(module_source(DOMAINS["cognition"]))
        produced = produced_names(tree)
        handed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "build_discovery_prompt":
                handed.update(a.id for a in node.args if isinstance(a, ast.Name))
        self.assertTrue(handed & produced,
                        "the candidate-list path given to the CLI is not staged")

    def test_archive_moves_the_staging_draft_into_the_project(self):
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "s" / "2026-10-06-000000000000.md"
            staging.parent.mkdir()
            staging.write_text("# draft", encoding="utf-8")
            destination = Path(directory) / "reports" / "ai" / "drafts" / staging.name
            self.assertTrue(archive_agent_draft(staging, destination))
            self.assertEqual(destination.read_text(encoding="utf-8"), "# draft")
            self.assertFalse(staging.exists(), "staging copy should not be left behind")

    def test_archive_reports_a_missing_draft_instead_of_crashing(self):
        """'The model returned without writing' must reach the validation gate
        as a readable failure, not an exception on an unattended run."""
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "nope.md"
            self.assertFalse(archive_agent_draft(
                missing, Path(directory) / "out" / missing.name))


if __name__ == "__main__":
    unittest.main()
