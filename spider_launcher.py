"""
Spider Task Launcher — parallel morning pipeline runner.

Invoked by the WorkBuddy hosted automation. Reads task_registry.json and
spawns all enabled tasks as parallel pythonw.exe subprocesses.

The job used to be triggered by the Windows Task Scheduler task `Spider晨跑`
(daily 07:30); that task was disabled on 2026-09-29 when scheduling moved to
WorkBuddy. Its registration is kept for rollback — see README「调度」.

Each task writes to pipeline_status.json independently (atomic writes
with retry already built into domain_status.py). The persistent
dashboard polls the file and shows live progress.

Usage:
    pythonw.exe spider_launcher.py          # hosted automation (silent)
    python spider_launcher.py --verbose     # Manual run with console output
    python spider_launcher.py --help        # 用法说明（不会启动管道）

Unknown arguments are rejected by argparse rather than ignored — see _parse_args.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = BASE_DIR / "task_registry.json"

sys.path.insert(0, str(BASE_DIR / "spider_core"))
from core.output_utils import validate_system_clock


# Independent probes — any one answering means the network is usable.
#
# This used to be baidu.com alone, which made one host a single point of failure for
# the whole pipeline: on 2026-09-23 the launcher aborted after 300s while all 20 news
# sources were reachable, because baidu alone was returning EOF through the local
# proxy. The question here is "is the network usable", not "is baidu up".
NETWORK_PROBES = (
    "https://www.baidu.com",
    "https://www.google.com/generate_204",
    "https://api.github.com",
)


def wait_for_network(timeout=120, interval=5, heartbeat=300):
    """Block until the network is usable, however long this machine takes.

    The task fires right after the machine resumes from sleep — usually before
    Wi-Fi has re-associated — so a short budget silently costs the whole day's
    report (2026-09-05, 09-07, 09-18 and 09-23 all produced no report this way).
    Rather than giving up, keep waiting and record why, so the run happens whenever
    connectivity actually arrives. That is the point: the machine decides when.

    Returns True as soon as any probe answers, False once `timeout` is spent.

    The budget is measured with time.monotonic(), not time.time(): on Windows that is
    GetTickCount64, which does not advance while the machine sleeps or hibernates. So
    "4 hours" means four hours of *awake* waiting — hibernating mid-wait does not burn
    the budget, and the run still happens on the next wake.
    """
    started = time.monotonic()
    deadline = started + timeout
    next_beat = started + heartbeat
    attempts = 0
    last_err = "no attempt completed"

    while time.monotonic() < deadline:
        attempts += 1
        for url in NETWORK_PROBES:
            try:
                urllib.request.urlopen(url, timeout=5)
                waited = int(time.monotonic() - started)
                print(f"  Network OK ({url}; waited {waited}s, {attempts} attempt(s))")
                return True
            except Exception as e:
                last_err = f"{url} -> {type(e).__name__}: {e}"

        now = time.monotonic()
        if now >= next_beat:
            print(f"  ... waiting for network ({int(now - started)}s) — last: {last_err}")
            next_beat = now + heartbeat

        time.sleep(interval)

    print(f"  [FAIL] No network after {timeout}s ({attempts} attempts) — last: {last_err}")
    return False


def _parse_args(argv):
    """Parse the launcher's (deliberately tiny) CLI.

    The hosted automation runs this with no arguments at all, so that path must not change.
    What must change is `--help`: the previous form — `verbose = "--verbose" in
    sys.argv` — ignored every other argument, so *any* flag ran the whole pipeline.
    That is not hypothetical: CC Server health-checks a registered CLI project by
    running `{runtime} {entry_point} --help` (routes/control.py), and
    project_registry.json names this file as that entry point. So a health check
    would silently kick off a real fetch-and-report run, and the checker's 10s
    timeout would then kill it mid-pipeline. argparse handles --help itself
    (printing usage, exiting 0, running nothing) and rejects unknown flags loudly
    instead of ignoring them.
    """
    parser = argparse.ArgumentParser(
        prog="spider_launcher.py",
        description="Spider 晨跑启动器：读 task_registry.json，并行拉起各 domain 管道。",
        epilog="无参数 = 静默写 logs/launcher/（托管调用用法）；--verbose = 输出到控制台。",
    )
    parser.add_argument("--verbose", action="store_true",
                        help="输出到控制台而非 logs/launcher/（人工运行时用）")
    return parser.parse_args(argv)


def main():
    args = _parse_args(sys.argv[1:])
    verbose = args.verbose
    ts = datetime.now().strftime("%H:%M:%S")

    if not verbose:
        log_dir = BASE_DIR / "logs" / "launcher"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"launcher_{datetime.now().strftime('%Y-%m-%d')}.log"
        # Line-buffered: the network wait can now run for hours, and a buffered log
        # would lose every heartbeat if the process is killed (caller stop,
        # power loss, another hibernate) — which is exactly when the log matters.
        sys.stdout = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stderr = sys.stdout

    print(f"[{ts}] Spider Launcher starting...")

    # Load registry
    if not REGISTRY_PATH.exists():
        print(f"  [FAIL] Task registry not found: {REGISTRY_PATH}")
        sys.exit(1)

    with open(REGISTRY_PATH, encoding="utf-8") as f:
        registry = json.load(f)

    settings = registry.get("settings", {})
    tasks = [t for t in registry.get("tasks", []) if t.get("enabled", True)]

    if not tasks:
        print(f"  [SKIP] No enabled tasks in registry")
        return

    print(f"  Registry: {len(tasks)} task(s)")

    # ── System clock validation ─────────────────────────
    cognition_config_path = BASE_DIR / "domains" / "cognition" / "config.json"
    if cognition_config_path.exists():
        with open(cognition_config_path, encoding="utf-8") as f:
            cog_cfg = json.load(f)
        vault_path = Path(cog_cfg["obsidian"]["vault_path"])
        output_dir = vault_path / cog_cfg["obsidian"]["output_dir"]
        clock_ok, clock_msg = validate_system_clock(output_dir)
        if not clock_ok:
            print(f"  [FATAL] {clock_msg}")
            sys.exit(1)

    # Network check
    if settings.get("network_check", True):
        timeout = settings.get("network_timeout_seconds", 3600)
        print(f"  Waiting for network (up to {timeout}s)...")
        if not wait_for_network(timeout):
            print(f"  [FAIL] No network after {timeout}s — aborting")
            sys.exit(1)

    # Resolve pythonw.exe path (same directory as current python)
    python_dir = Path(sys.executable).parent
    pythonw = python_dir / "pythonw.exe"
    if not pythonw.exists():
        # Fallback: search in same directory with pythonw.exe name
        fallback = python_dir / "pythonw.exe"
        if not pythonw.exists():
            print(f"  [WARN] pythonw.exe not found at {pythonw}, trying python.exe")
            pythonw = python_dir / "python.exe"

    # Launch all tasks in parallel
    processes = []
    failed = []
    for task in tasks:
        script = BASE_DIR / task["script"]
        if not script.exists():
            print(f"  [FAIL] Script not found: {script} ({task['label']})")
            failed.append(f"{task['label']} (script missing)")
            continue

        print(f"  Launching: {task['label']} → {task['script']}")
        try:
            p = subprocess.Popen(
                [str(pythonw), str(script)],
                cwd=str(BASE_DIR),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            processes.append((task, p))
        except Exception as e:
            print(f"  [FAIL] Cannot launch {task['label']}: {e}")

    print(f"  Launched {len(processes)}/{len(tasks)} tasks in parallel")

    # Wait for all to complete
    timeout = settings.get("timeout_seconds", 900)
    deadline = time.time() + timeout
    remaining = list(processes)

    while remaining and time.time() < deadline:
        still_running = []
        for task, p in remaining:
            ret = p.poll()
            if ret is not None:
                status = "OK" if ret == 0 else f"exit={ret}"
                if ret != 0:
                    failed.append(f"{task['label']} ({status})")
                print(f"  [{status}] {task['label']} finished")
            else:
                still_running.append((task, p))
        remaining = still_running
        if remaining:
            time.sleep(3)

    for task, p in remaining:
        print(f"  [TIMEOUT] {task['label']} — still running after {timeout}s")
        failed.append(f"{task['label']} (timeout)")
        try:
            p.terminate()
        except Exception:
            pass

    elapsed = int(time.time() - (deadline - timeout))
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Launcher done ({elapsed}s)")

    # Propagate failure so the caller sees a non-zero exit code. Without this the
    # launcher always exited 0, so the scheduler reported a fully successful run
    # even on days a domain produced no report at all — e.g. 2026-09-21, when the
    # AI domain exited 1 and the task's LastResult was still 0.
    if failed:
        print(f"  [FAILED] {len(failed)}/{len(tasks)} task(s): {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
