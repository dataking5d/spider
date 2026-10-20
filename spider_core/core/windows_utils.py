"""
Windows-specific utilities for Spider projects.

Usage:
    from core.windows_utils import merge_user_path, read_claudian_config
    merge_user_path()
    claude_exe, _ = read_claudian_config(vault_path)
"""
import json
import os
import shutil
import winreg
from pathlib import Path


#: Model the pipeline is pinned to unless overridden. Chosen 2026-10-12 to stop
#: the daily run being billed against the pricier deepseek-v4-pro.
DEFAULT_MODEL = "deepseek-flash"


def merge_user_path():
    """Merge the user's PATH from HKCU registry into os.environ.
    Needed because Windows Task Scheduler uses system PATH only.
    Silently does nothing on failure.
    """
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        user_path, _ = winreg.QueryValueEx(key, "PATH")
        winreg.CloseKey(key)
        if user_path:
            os.environ["PATH"] = user_path + ";" + os.environ.get("PATH", "")
            print("[OK] User PATH merged")
    except Exception:
        pass


def _resolve_claude_exe(configured: str) -> str:
    """Return a usable claude executable path.

    The path Claudian records goes stale: WinGet deletes its Links/ shim on
    every auto-update, leaving cliPathsByHost pointing at a file that no
    longer exists. Validate it and fall back to a PATH lookup.
    """
    if configured and configured != "claude" and Path(configured).exists():
        return configured

    found = shutil.which("claude")
    if found:
        print(f"[WARN] Configured CLI path unusable ({configured}) → using {found}")
        return found

    print(f"[WARN] claude CLI not found on PATH → falling back to {configured!r}")
    return configured or "claude"


def read_claudian_config(vault_path: Path):
    """Read Claude CLI configuration from Obsidian vault's .claudian settings.

    Imports only provider credentials and endpoint; leaves model settings intact.
    Returns (claude_exe: str, provider_config: dict | None).
    Defaults claude_exe to "claude" if config is missing.
    """
    claudian_settings = vault_path / ".claudian" / "claudian-settings.json"
    if not claudian_settings.exists():
        print("[WARN] Claudian settings not found, using default 'claude'")
        return "claude", None

    cs = json.loads(claudian_settings.read_text(encoding="utf-8"))
    pc = cs.get("providerConfigs", {}).get("claude", {})

    if pc.get("environmentVariables"):
        for line in pc["environmentVariables"].split("\n"):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                if k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
                    os.environ[k] = v

    hostname = os.environ.get("COMPUTERNAME", "")
    claude_exe = _resolve_claude_exe(pc.get("cliPathsByHost", {}).get(hostname, "claude"))

    return claude_exe, pc


def resolve_model() -> str | None:
    """Return the model id this run should pin, or None to accept the CLI default.

    Call after ``read_claudian_config()``. Pass the result to the CLI as an
    explicit ``--model`` argument rather than letting the model be inferred
    from ambient environment variables.

    Why this exists: the vault's claudian settings and ``~/.claude/settings.json``
    both set ANTHROPIC_MODEL, so which one won was a precedence race. That race
    silently switched the daily pipeline from deepseek-v4-pro to deepseek-flash
    on 2026-09-11 — the same day the CLI path resolution changed — and the switch
    went unnoticed for 10 days. Pinning it here, and logging it, makes the model
    a single-sourced, observable fact again.

    Why the explicit default (2026-10-12): this returned ``None`` whenever the
    process environment carried no ``ANTHROPIC_MODEL`` — which is the normal
    case, since the WorkBuddy automation scheduler does not export one. ``None``
    means "emit no ``--model``", so the CLI fell back to its own default and the
    07:00 run was billed against deepseek-v4-pro (~26 requests / 526k tokens /
    CNY 1.89 per day) despite every settings file naming flash. Resolving to the
    intended model unconditionally makes the pin real instead of advisory.

    Precedence: ``SPIDER_MODEL`` (emergency override) → ``ANTHROPIC_MODEL``
    (operator intent) → :data:`DEFAULT_MODEL`.
    """
    for var in ("SPIDER_MODEL", "ANTHROPIC_MODEL"):
        value = os.environ.get(var)
        if value and value.strip():
            return value.strip()
    return DEFAULT_MODEL
