"""Evidence-based actionability hints. Pure rules; no model calls or network.

A = a documented public online entry; B = access/setup needs checking;
C = information only. A does not mean the product has been tested.
"""

import re

DEMO_PATTERN = re.compile(
    r"(?:online demo|public demo|live demo|demo|playground|try it|在线体验|在线演示|试玩)"
    r"\s*(?:at\s+)?[:：]?\s*(https?://[^\s<>\"\)]+)",
    re.IGNORECASE,
)
NO_ACCOUNT_PATTERN = re.compile(
    r"\b(?:no|without)\s+(?:an?\s+)?(?:sign[ -]?up|registration|account|log[ -]?in)\b"
    r"|无需注册|无需登录|免登录",
    re.IGNORECASE,
)
NO_REQUIREMENT_PATTERN = re.compile(
    r"\b(?:no|without)\s+(?:an?\s+)?"
    r"(?:sign[ -]?up|registration|account|log[ -]?in|installation|install|setup|waitlist|payment)"
    r"(?:\s+(?:is\s+)?(?:needed|required))?\b|无需(?:注册|登录|安装|配置|付费|排队)",
    re.IGNORECASE,
)

SETUP_SIGNALS = [
    "pip install", "npm install", "docker", "git clone", "self-host",
    "requires python", "prerequisites", "requires setup", "installation required",
    "requires gpu", "gpu cluster", "cuda", "本地部署", "需要安装", "需安装",
]
ACCOUNT_SIGNALS = [
    "sign up", "signup", "sign-up", "register", "registration", "create account",
    "requires account", "account required", "login required", "log in", "登录", "注册",
    "api key", "api-key",
]
PAYMENT_SIGNALS = [
    "paid", "subscription", "payment required", "credit card required", "付费", "收费", "订阅",
]
RESTRICTED_SIGNALS = [
    "private beta", "invite only", "invite-only", "invitation", "waitlist",
    "limited access", "contact sales", "coming soon", "developer preview",
    "early access", "内测", "申请", "灰度", "尚未开放",
]
COGNITIVE_SOURCES = {
    "Papers with Code", "MIT Technology Review", "TechCrunch AI", "The Verge AI",
    "VentureBeat AI", "Reddit r/MachineLearning", "Reddit r/artificial",
}


def _text_contains(text, keywords):
    return any(kw in text.lower() for kw in keywords)


def _documented_demo(item, summary, evidence):
    """Require the same explicit entry in the summary and fetched evidence.

    A generic demo navigation link in an article is not evidence for this item.
    """
    if item.get("_evidence_status") != "excerpt":
        return ""
    if not NO_ACCOUNT_PATTERN.search(evidence):
        return ""
    if not re.search(r"\bfree\b|免费", evidence, re.IGNORECASE):
        return ""
    for match in DEMO_PATTERN.finditer(summary):
        url = match.group(1).rstrip(".,;:!?，。；！")
        if url in evidence:
            return url
    return ""


def classify_actionability(items):
    """Mutate items with conservative availability hints; preserve A/B/C fields."""
    for it in items:
        link = it.get("link") or ""
        summary = f"{it.get('title') or ''} {it.get('description') or ''}"
        evidence = it.get("_evidence_text") or ""
        text = NO_REQUIREMENT_PATTERN.sub("", f"{summary} {evidence}").lower()
        has_url = link.startswith(("http://", "https://"))
        needs_setup = _text_contains(text, SETUP_SIGNALS)
        needs_account = _text_contains(text, ACCOUNT_SIGNALS)
        needs_payment = _text_contains(text, PAYMENT_SIGNALS)
        restricted = _text_contains(text, RESTRICTED_SIGNALS)

        it["_requires_setup"] = needs_setup
        it["_requires_account"] = needs_account
        it["_requires_payment"] = needs_payment
        it["_action_url"] = ""
        it["_has_public_url"] = False

        if restricted:
            level, reason = "B", "待核验：存在申请、限量或尚未开放的访问限制"
        elif needs_payment:
            level, reason = "B", "待核验：需要付费或订阅，先确认费用与权限"
        elif needs_account:
            level, reason = "B", "待核验：需要账号或密钥，先确认访问条件"
        elif needs_setup:
            level, reason = "B", "待核验：需要安装或配置，可借助 AI 工具核对环境要求"
        else:
            demo = _documented_demo(it, summary, evidence)
            if demo:
                level, reason = "A", "原文提供无需注册的免费在线体验入口（未实测）"
                it["_action_url"] = demo
                it["_has_public_url"] = True
            elif not has_url or it.get("source_name") in COGNITIVE_SOURCES:
                level, reason = "C", "认知信息，未确认可直接体验的入口"
            else:
                level, reason = "B", "待核验：有来源链接，但缺少直接可用的证据"
        it["_actionability"] = level
        it["_actionability_reason"] = reason

    return items
