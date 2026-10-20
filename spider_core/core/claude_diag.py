"""
Shared Claude CLI failure diagnosis (spider_core layer).

Why this exists
---------------
Claude Code prints FATAL errors on **stdout**, not stderr:

    $ claude --print ... ; echo $?
    API Error: 402 Insufficient Balance (request_id: ...)   <- stdout
    1                                                        <- exit code

while stderr carries only advisory warnings — e.g. the "model isn't described
by this version's model catalog" notice, which appears on successful runs too.

Domains that captured stderr only therefore logged `exit=1` with a misleading
warning and no cause. On 2026-09-29 the cognition domain was failing on an
exhausted API balance; it took three days, three unexplained failures and a
manual re-run to identify, because the one line that said so was on stdout and
was thrown away.

Rules of thumb encoded here:
  * Always capture AND persist both streams before deciding anything.
  * Classify the failure into something actionable — "充值" beats "exit=1".
  * Never let a failure path report success to the health scorer.
"""

from __future__ import annotations

from pathlib import Path

# (kind, needles, human hint) — matched case-insensitively against stdout+stderr.
CLAUDE_ERROR_RULES: list[tuple[str, tuple[str, ...], str]] = [
    ("api_balance",
     ("insufficient balance", "credit balance is too low", "insufficient_quota",
      "402", "余额不足", "out of credit"),
     "API 账户余额不足 — 需充值后重跑，代码层面无法绕过"),
    ("api_auth",
     ("401", "authentication_error", "invalid api key", "invalid x-api-key",
      "unauthorized", "permission denied"),
     "API 认证失败 — 检查 ANTHROPIC_API_KEY / provider 配置"),
    ("api_rate_limit",
     ("429", "rate limit", "rate_limit_error", "too many requests"),
     "API 限流 — 稍后重跑，或降低调用频率"),
    ("api_server",
     ("529", "overloaded_error", "overloaded", "internal server error",
      "500 ", "502 ", "503 ", "504 "),
     "API 服务端错误 — provider 侧问题，稍后重跑"),
    ("network",
     ("econnreset", "econnrefused", "connection aborted", "name or service not known",
      "timed out", "timeout", "temporary failure in name resolution"),
     "网络问题 — 检查网络后重跑"),
    ("cli_missing",
     ("not recognized as an internal or external command", "no such file or directory",
      "cannot find the file"),
     "Claude CLI 路径失效 — 检查 cliPathsByHost / 重新安装 CLI"),
]


def classify_claude_error(stdout: str, stderr: str) -> tuple[str, str]:
    """Return (kind, actionable_hint) for a failed CLI call."""
    blob = f"{stdout or ''}\n{stderr or ''}".lower()
    for kind, needles, hint in CLAUDE_ERROR_RULES:
        if any(needle in blob for needle in needles):
            return kind, hint
    return "unknown", "未知原因 — 见完整输出日志"


def dump_claude_io(logs_dir: Path, filename: str, stdout: str, stderr: str,
                   exit_code) -> str | None:
    """Persist the full CLI output for post-mortem.

    Exit code + a 3-line stderr tail cannot distinguish an API 402 from a
    network blip, so keep everything. Returns the path written, or None.
    """
    try:
        path = Path(logs_dir) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            f"exit_code: {exit_code}\n\n"
            f"--- STDOUT ---\n{stdout or '(empty)'}\n\n"
            f"--- STDERR ---\n{stderr or '(empty)'}\n",
            encoding="utf-8")
        return str(path)
    except Exception:
        return None


def tail(text: str, lines: int = 5, limit: int = 500) -> str:
    """Last `lines` lines of text, capped at `limit` chars — for log lines."""
    if not text:
        return ""
    return "\n".join(text.split("\n")[-lines:])[:limit]
