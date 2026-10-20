"""
Campus AI opportunity detector for AI Domain.
Identifies items that suggest MVP opportunities for college students.
"""

CAMPUS_SIGNALS = [
    "student", "university", "college", "campus", "academic",
    "education", "learning", "teaching", "course", "homework",
    "study", "exam", "assignment", "tutoring",
    "校园", "学生", "大学", "教育", "学习", "课程", "考试",
    "上课", "作业", "笔记", "自习",
]

OPPORTUNITY_SIGNALS = [
    "free", "open source", "no cost", "免费", "开源",
    "mobile", "app", "browser", "web",
    "collaboration", "group", "share", "team", "social",
    "simple", "easy", "quick", "简单", "快速",
]

OPPORTUNITY_TYPE_KEYWORDS = {
    "student_tool": [
        "note", "study", "learn", "笔记", "学习", "复习",
        "flashcard", "quiz", "exam prep",
    ],
    "campus_workflow": [
        "schedule", "calendar", "task", "todo", "日程",
        "计划", "待办", "提醒", "organize",
    ],
    "study_ai": [
        "ai tutor", "ai teacher", "explain", "tutor",
        "家教", "辅导", "答疑", "问答",
    ],
    "campus_startup": [
        "marketplace", "二手", "delivery", "二手交易",
        "校园服务", "campus service",
    ],
}


def _text_contains(text, keywords):
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _detect_type(title, desc):
    """Detect the opportunity type from item text."""
    text = f"{title} {desc}".lower()
    scores = {}
    for otype, keywords in OPPORTUNITY_TYPE_KEYWORDS.items():
        scores[otype] = sum(1 for kw in keywords if kw in text)
    if not scores or max(scores.values()) == 0:
        return "student_tool"  # default
    return max(scores, key=scores.get)


def _make_mvp_scenario(title, desc, opp_type):
    """Generate a one-line MVP scenario for campus context."""
    desc_short = (desc or title)[:80]
    scenarios = {
        "student_tool": f"做一个面向大学生的{desc_short}工具，先在自己班级试用",
        "campus_workflow": f"把{desc_short}做成校园版的自动化流程",
        "study_ai": f"用这个思路做一个针对本校课程的学习助手",
        "campus_startup": f"把这个模式搬到本校，做一个校园版{desc_short}",
    }
    return scenarios.get(opp_type, f"探索{desc_short}在校园场景的应用")


def detect_campus_opportunities(items):
    """Detect campus-relevant AI opportunities from scored items.

    Returns list of opportunity dicts (max 5). Empty list if none found.
    """
    opportunities = []

    for it in items:
        title = it.get("title", "")
        desc = it.get("description", "")
        combined = f"{title} {desc}".lower()
        actionability = it.get("_actionability", "C")

        # Must have campus signal AND opportunity signal
        if not _text_contains(combined, CAMPUS_SIGNALS):
            continue
        if not _text_contains(combined, OPPORTUNITY_SIGNALS):
            continue
        if actionability == "C":
            continue

        opp_type = _detect_type(title, desc)
        mvp = _make_mvp_scenario(title, desc, opp_type)

        opportunities.append({
            "title": title,
            "opportunity_type": opp_type,
            "mvp_scenario": mvp,
            "link": it.get("link", ""),
            "source_item_score": it.get("_total_score", 0),
            "actionability": actionability,
        })

    opportunities.sort(key=lambda x: x["source_item_score"], reverse=True)
    return opportunities[:5]
