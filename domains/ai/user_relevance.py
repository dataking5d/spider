"""
User relevance computation for AI Domain.
Reads memory/founder_profile.md and boosts items matching the founder's profile:
first-year science undergrad, AI product explorer, Agent practitioner, OSS enthusiast.
"""

from pathlib import Path

BOOST_RULES = [
    # (label, boost, keywords to match in item text)
    ("Agent/MCP 工具链", 10, [
        "agent", "mcp", "tool calling", "computer use",
        "智能体", "mcp server", "agent framework",
        "agent protocol", "agent orchestration", "tool use",
        "function call", "coding agent", "browser agent",
        "multi-agent", "agent swarm",
    ]),
    ("GitHub 开源工具", 8, []),  # special: checked via link domain
    ("低门槛可复现", 7, [
        "no-code", "零代码", "low-code", "低代码",
        "no coding", "democratize", "人人可用",
        "for everyone",
    ]),
    ("校园/学生相关", 5, [
        "student", "university", "campus", "college",
        "education", "学生", "大学", "校园",
        "学习", "教育",
    ]),
    ("AI 创业/变现", 5, [
        "startup", "monetize", "marketplace", "创业",
        "变现", "副业", "side hustle", "freelance",
        "赚钱", "income",
    ]),
    ("工作流/效率提升", 4, [
        "workflow", "productivity", "efficiency",
        "工作流", "效率", "自动化", "automation",
        "省时", "save time",
    ]),
]

PENALTY_RULES = [
    ("纯学术论文", -2, [
        "arxiv", "paper", "benchmark", "sota",
        "论文", "算法",
    ]),
    ("企业级专用", -5, [
        "enterprise", "organization", "企业版",
        "requires team", "contact sales", "pricing",
    ]),
]


def _parse_profile(profile_path):
    """Read founder_profile.md and extract basic signals."""
    try:
        text = Path(profile_path).read_text(encoding="utf-8")
    except Exception:
        return {"available": False, "is_student": True}

    signals = {
        "available": True,
        "is_student": "大一" in text or "学生" in text,
        "interests": [],
    }
    for kw in ["agent", "mvp", "创业", "校园", "开源", "自动化"]:
        if kw in text:
            signals["interests"].append(kw)
    return signals


def _text_contains(text, keywords):
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def compute_user_relevance(items, profile_path=None):
    """Compute per-item user relevance boost based on founder profile.

    Adds to each item:
      _user_relevance_boost: float (0-25)
      _user_relevance_reasons: list[str]

    Returns items list for chaining.
    """
    if profile_path is None:
        profile_path = str(
            Path(__file__).resolve().parent.parent.parent
            / "memory" / "founder_profile.md"
        )

    profile = _parse_profile(profile_path)

    for it in items:
        title = (it.get("title") or "").lower()
        desc = (it.get("description") or "").lower()
        link = (it.get("link") or "").lower()
        source = (it.get("source_name") or "").lower()
        combined = f"{title} {desc}"
        boost = 0.0
        reasons = []

        # GitHub link boost (separate from keyword rules)
        if "github.com" in link or "github trending" in source:
            boost += 8
            reasons.append("GitHub 开源工具")

        # Keyword-based boost rules
        for label, points, keywords in BOOST_RULES:
            if points == 8 and "github" in label.lower():
                continue  # already handled above
            if _text_contains(combined, keywords):
                if label not in reasons:
                    boost += points
                    reasons.append(label)

        # Penalty rules
        for label, points, keywords in PENALTY_RULES:
            if _text_contains(combined, keywords):
                boost += points
                reasons.append(label)

        # Campus boost amplification for students
        if profile.get("is_student") and "校园/学生相关" in reasons:
            boost += 3  # extra +3 for confirmed student

        # Cap at 25, floor at -5
        boost = max(-5.0, min(25.0, boost))

        it["_user_relevance_boost"] = round(boost, 1)
        it["_user_relevance_reasons"] = reasons

    return items
