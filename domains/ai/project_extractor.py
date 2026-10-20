"""
Reproducible project extractor for AI Domain.
Scans scored items for GitHub repos, open-source tools, and demos
that the user can clone/try/reproduce.
"""

import re

GITHUB_REPO_PATTERN = re.compile(r"github\.com/([\w.-]+/[\w.-]+)")

PROJECT_SIGNALS = [
    "open source", "开源", "github", "repo",
    "tool", "framework", "library", "cli", "sdk",
    "plugin", "extension",
]

def _make_what_it_does(desc):
    """Extract a one-line description from the item description."""
    if not desc:
        return "未知"
    # Take first sentence or first 120 chars
    for sep in ["。", ". ", "\n"]:
        idx = desc.find(sep)
        if 20 < idx < 150:
            return desc[:idx].strip()
    return desc[:120].strip()


def extract_reproducible_projects(items):
    """Extract reproducible project cards from scored items.

    Returns list of project dicts (max 10).
    """
    candidates = []

    for it in items:
        title = it.get("title", "")
        desc = it.get("description") or ""
        link = it.get("link") or ""
        source = it.get("source_name", "")
        text = f"{title} {desc} {link}".lower()
        actionability = it.get("_actionability", "C")

        # Count project signals
        signal_count = sum(1 for s in PROJECT_SIGNALS if s in text)
        has_github = "github.com" in link
        is_github_trending = "github trending" in source.lower()

        # Must have at least 3 signals OR be from GitHub Trending
        if signal_count < 3 and not has_github and not is_github_trending:
            continue

        # Exclude pure news
        if actionability == "C" and not has_github:
            continue

        # Extract GitHub repo name
        repo = ""
        m = GITHUB_REPO_PATTERN.search(link)
        if m:
            repo = m.group(1)

        candidates.append({
            "title": title,
            "what_it_does": _make_what_it_does(desc),
            "why_worth_attention": (
                f"来自 {source}，"
                f"综合评分 {it.get('_total_score', 0):.0f}"
            ),
            # A public demo does not establish reproducibility or setup effort.
            "reproducible": "Unknown",
            "reproduction_cost": {"time": "Unknown", "difficulty": "Unknown"},
            "actionability": actionability,
            "availability_reason": it.get("_actionability_reason", "待核验"),
            "action_url": it.get("_action_url", ""),
            "link": link,
            "repo": repo,
            "source": source,
            "score": it.get("_total_score", 0),
        })

    candidates.sort(key=lambda x: -x["score"])

    return candidates[:10]
