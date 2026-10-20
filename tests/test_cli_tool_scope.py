"""The child `claude` CLI must not be able to reach a shell.

Regression guard for a defect measured 2026-10-06 on CLI 2.1.291: both domains
spawned the CLI with `--permission-mode dontAsk --allowedTools "Write,Edit"` and
believed that confined it. It does not. `--allowedTools` only auto-approves; the
child still had PowerShell and executed a command successfully. `--tools` is the
flag that actually removes tools.

The prompts in both domains contain material the pipeline does not control —
20 external feeds for AI, fetched web pages for cognition. A shell in that
process turns a poisoned page into arbitrary command execution on an unattended
daily run, which is exactly what removing --dangerously-skip-permissions was
meant to prevent.

Two argv shapes exist. generate_report.py hands `subprocess.run` a literal list;
curator.py builds that list inside `call_claude()` and takes the tool set as a
`tools=` argument. Both are read here, so neither can drift unnoticed.
"""
import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL_TOOLS = {"Bash", "PowerShell", "BashOutput", "KillShell", "Shell"}

DOMAINS = {
    "ai": ROOT / "generate_report.py",
    "cognition": ROOT / "domains/cognition/curator.py",
}


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def print_argv_lists(path):
    """Every literal argv list in the module that launches `claude --print`."""
    found = []
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.List):
            continue
        values = [e.value for e in node.elts
                  if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        if "--print" in values:
            found.append(node)
    return found


def flag_operand(list_node, flag):
    """The AST expression that follows `flag` in a literal argv list."""
    for index, element in enumerate(list_node.elts):
        if isinstance(element, ast.Constant) and element.value == flag:
            return list_node.elts[index + 1] if index + 1 < len(list_node.elts) else None
    return None


def argv_strings(list_node):
    return [e.value for e in list_node.elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def constant_tool_sets(path):
    """Tool sets the child can be launched with, where they are literal strings.

    Covers both shapes: a literal `--tools "A,B"` in an argv list, and a
    `call_claude(..., tools="A,B")` argument.
    """
    sets = set()
    for node in print_argv_lists(path):
        operand = flag_operand(node, "--tools")
        if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
            sets.add(frozenset(t for t in operand.value.split(",") if t))
    for node in ast.walk(_tree(path)):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "call_claude"):
            continue
        for keyword in node.keywords:
            if keyword.arg == "tools" and isinstance(keyword.value, ast.Constant):
                sets.add(frozenset(t for t in keyword.value.value.split(",") if t))
    return sets


class CliToolScopeTests(unittest.TestCase):
    def test_every_domain_restricts_the_tool_set(self):
        """`--allowedTools` alone does not confine the child; `--tools` does."""
        for domain, path in DOMAINS.items():
            with self.subTest(domain=domain):
                launches = print_argv_lists(path)
                self.assertTrue(launches, f"{domain} has no `claude --print` invocation")
                for node in launches:
                    self.assertIn("--tools", argv_strings(node),
                                  f"{domain} spawns the CLI without --tools, so the "
                                  f"child keeps every default tool")
                self.assertTrue(constant_tool_sets(path),
                                f"{domain} names no tool set the test can read")

    def test_no_domain_grants_a_shell(self):
        for domain, path in DOMAINS.items():
            with self.subTest(domain=domain):
                for tools in constant_tool_sets(path):
                    self.assertFalse(tools & SHELL_TOOLS,
                                     f"{domain} grants a shell: {sorted(tools & SHELL_TOOLS)}")

    def test_no_permission_bypass_flag(self):
        for domain, path in DOMAINS.items():
            with self.subTest(domain=domain):
                for node in print_argv_lists(path):
                    values = argv_strings(node)
                    self.assertNotIn("--dangerously-skip-permissions", values)
                    self.assertNotIn("--allow-dangerously-skip-permissions", values)

    def test_mcp_is_not_loaded(self):
        """--tools does not govern MCP tools: they load from user config no
        matter what --tools names. Without this flag the child's tool set is
        whatever the machine happens to have configured, so the 'it can only
        write a draft' property would hold by luck rather than by construction."""
        for domain, path in DOMAINS.items():
            with self.subTest(domain=domain):
                for node in print_argv_lists(path):
                    self.assertIn("--strict-mcp-config", argv_strings(node))

    def test_autopapprove_list_does_not_exceed_the_tool_set(self):
        """The two lists drifting apart is how the shell stayed reachable: the
        restriction was narrower than what the child actually had.

        Compared as source expressions, not values, so curator.py's
        `--tools tools --allowedTools tools` (the same variable twice) counts as
        the guarantee it is.
        """
        for domain, path in DOMAINS.items():
            with self.subTest(domain=domain):
                for node in print_argv_lists(path):
                    tools = flag_operand(node, "--tools")
                    allowed = flag_operand(node, "--allowedTools")
                    self.assertIsNotNone(allowed, f"{domain} names no --allowedTools")
                    self.assertEqual(ast.dump(tools), ast.dump(allowed),
                                     f"{domain} auto-approves something --tools does "
                                     f"not grant")

    def test_cognition_keeps_search_so_links_can_be_real(self):
        """The template requires a clickable original link per item and forbids
        inventing one. Without search the model can only write from memory,
        which is how the audit found 28 link-free items.

        Search lives in the discovery stage only — the drafting stage runs with
        `--tools Write`, since by then Python has already fetched the sources.
        So this asks that search is granted somewhere, not everywhere.
        """
        self.assertTrue(any("WebSearch" in tools
                            for tools in constant_tool_sets(DOMAINS["cognition"])),
                        "no cognition stage can search, so every link would come "
                        "from memory")

    def test_cognition_does_not_rely_on_webfetch(self):
        """WebFetch is deliberately withdrawn from the cognition domain.

        Measured 2026-10-07: this machine runs the CLI against a non-Anthropic
        relay (`ANTHROPIC_BASE_URL=api.deepseek.com`), and WebFetch's per-domain
        safety check cannot pass there. Every source came back "Unable to verify
        if domain ... is safe to fetch", with and without a proxy, which is why
        the domain had been producing empty reports. Python fetches the sources
        instead (core.evidence); granting WebFetch again would restore a tool
        that only looks like it works.
        """
        for tools in constant_tool_sets(DOMAINS["cognition"]):
            self.assertNotIn("WebFetch", tools)


if __name__ == "__main__":
    unittest.main()
