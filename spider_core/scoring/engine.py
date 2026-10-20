"""
Shared scoring engine — config-driven, multi-dimensional.
==========================================================
Used by all Spider domains. Domain-specific parameters live in
each domain's scoring_config.json.

Dimensions (all optional, controlled by config):
  source_weight   — static credibility score from tier config
  freshness       — exponential decay based on publish time
  community_heat  — log-scale score from votes/stars/points
  relevance       — keyword match against domain criteria
  long_term_value — topic-based lasting-value score (0-5)

Output per item:
  breakdown:    {dim_label: weighted_score, ...}     ← human-readable
  _total_score: weighted sum
  _reasons:     [human-readable reason strings]      ← for Claude prompt
  _matched_criteria: [rule_id, ...]
"""

import math
import re
from datetime import datetime, timezone


def _content_text(item):
    """Score article text, excluding RSS links and engagement boilerplate."""
    text = item.get("title", "") + " " + item.get("description", "")
    text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\[GitHub Stars:\s*[\d,]+\]|\[Upvotes:\s*\d+\]", " ", text,
                  flags=re.IGNORECASE)
    text = re.sub(r"(?:Article URL|Comments URL):|(?:Points|#\s*Comments):\s*\d+", " ",
                  text, flags=re.IGNORECASE)
    text = re.sub(r"submitted by\s+/u/\S+|\[(?:link|comments)\]", " ", text,
                  flags=re.IGNORECASE)
    return text.lower()


# Model names keep version digits (Qwen3.8 / GPT6) instead of a word boundary.
_MODEL_TERMS = ("gpt", "qwen", "llama", "gemini", "deepseek", "claude", "ling",
                "o1", "o3", "o4")

# Only real inflectional endings may follow a term: "skill" reaches "skills"
# and "fine-tun" reaches fine-tuning/fine-tuned, while "work" no longer hides
# inside "network"/"workflow" and "rag" no longer hides inside "coverage".
_INFLECTION = (r"e?s|es|ed|ing|er|ers|ion|ions|al|ally|ic|ics|ly|ive|able"
               r"|ment|ments")
# A single trailing letter is only credible for longer stems ("fine-tune");
# allowing it for short terms would make "ai" match "aid" and "cot" match "cote".
_SHORT_STEM_EXTRA = r"|[ed]"


def _term_body(term):
    """Escape a term, making spaces, hyphens, underscores and slashes equivalent."""
    parts = [re.escape(part) for part in re.split(r"[\s\-_/]+", term) if part]
    return r"[\s\-_/]+".join(parts) if parts else None


def _contains_term(text, term):
    """Match domain-context terms without finding 'ai' inside unrelated words.

    ASCII terms are matched on word boundaries with interchangeable separators
    ("open source" == "open-source") and normal inflections; CJK and other
    non-ASCII terms keep plain substring matching.
    """
    term = term.lower().strip()
    if not term:
        return False
    if not re.fullmatch(r"[a-z0-9][a-z0-9 .\-_/]*", term):
        return term in text
    body = _term_body(term)
    if body is None:
        return False
    prefix = r"(?<![a-z0-9])"
    if term in _MODEL_TERMS:
        return bool(re.search(prefix + body + r"(?![a-z])", text))
    extra = _SHORT_STEM_EXTRA if len(term) >= 5 else ""
    return bool(re.search(
        prefix + body + r"(?:" + _INFLECTION + extra + r")?(?![a-z0-9])", text))


def _source_evidence(item):
    return {key: item.get(key, "") for key in (
        "title", "link", "description", "source_name", "published", "observed_at")}


def score_items(items, config):
    """Score items across configured dimensions. Mutates items in-place.

    Adds to each item:
      breakdown:     {label: weighted_score, ...}
      _total_score:  float
      _reasons:      [str, ...]
      _matched_criteria: [str, ...]
      _scores:        {dim_name: raw_score, ...}  (internal, for debugging)

    Items with _total_score < min_total_score are dropped.
    Returns list sorted by _total_score descending.
    """
    dims = config.get("dimensions", {})
    min_score = config.get("min_total_score", 0)
    labels = config.get("dimension_labels", {})
    reasons_cfg = config.get("reasons", {})
    tier_map = config.get("tiers", {})

    for item in items:
        total = 0.0
        scores = {}
        breakdown = {}
        reasons = []
        content_text = _content_text(item)

        # ── Source weight ──────────────────────────────
        if "source_weight" in dims:
            sw = dims["source_weight"]
            # Auto-map tier if configured
            if tier_map and item.get("source_tier"):
                tier_weight = _tier_weight(item["source_tier"], tier_map)
            else:
                tier_weight = item.get("tier_weight", 0)
            raw = item.get("source_weight", 0) + tier_weight
            weighted = raw * sw.get("weight", 1.0)
            scores["source_weight"] = raw
            breakdown[labels.get("source_weight", "source_weight")] = round(weighted, 1)
            total += weighted

            # Reasons: high-tier source
            tier_name = item.get("source_tier", "")
            if tier_name and tier_map:
                tier_info = tier_map.get(tier_name, {})
                if tier_info.get("level", 99) <= 1:
                    reasons.append(reasons_cfg.get("high_tier_source",
                        f"顶级信源 ({tier_name})"))

        # ── Freshness ──────────────────────────────────
        if "freshness" in dims:
            fc = dims["freshness"]
            hours = _age_hours(item.get("published"))
            if hours is not None and hours >= 0:
                decay = 0.5 ** (hours / fc["half_life_hours"])
                raw = fc.get("base_score", 100) * decay
                weighted = raw * fc.get("weight", 1.0)
                scores["freshness"] = round(raw, 1)
                breakdown[labels.get("freshness", "freshness")] = round(weighted, 1)
                total += weighted

                # Reasons: very fresh
                if hours < fc.get("fresh_threshold_hours", 6):
                    reasons.append(reasons_cfg.get("very_fresh",
                        f"发布 {hours:.0f}h 内"))

        # ── Community heat ─────────────────────────────
        if "community_heat" in dims:
            cc = dims["community_heat"]
            pts = item.get(cc.get("field", "points"), 0) or 0
            raw = math.log10(pts + 1) * cc.get("scale", 10)
            weighted = raw * cc.get("weight", 1.0)
            scores["community_heat"] = round(raw, 1)
            breakdown[labels.get("community_heat", "community_heat")] = round(weighted, 1)
            total += weighted

            # Reasons: high community engagement
            hot_threshold = cc.get("hot_threshold", 100)
            if pts >= hot_threshold:
                reasons.append(reasons_cfg.get("community_hot",
                    f"社区热议 ({pts} votes)"))

        # ── Relevance (keyword match) ──────────────────
        if "relevance" in dims:
            rc = dims["relevance"]
            text = content_text
            context_terms = rc.get("context_terms", [])
            in_context = not context_terms or any(_contains_term(text, term)
                                                  for term in context_terms)
            rel_score = 0
            matched = []
            for rule_id, rule_cfg in rc.get("keywords", {}).items():
                for kw in rule_cfg.get("terms", []):
                    if in_context and _contains_term(text, kw):
                        rel_score += rule_cfg.get("score", 10)
                        matched.append(rule_id)
                        break
            weighted = rel_score * rc.get("weight", 1.0)
            scores["relevance"] = rel_score
            breakdown[labels.get("relevance", "relevance")] = round(weighted, 1)
            item["_matched_criteria"] = matched
            total += weighted

            # Reasons: from matched criteria labels
            criteria_labels = rc.get("criteria_labels", {})
            for rule_id in matched:
                label = criteria_labels.get(rule_id)
                if label:
                    reasons.append(label)

        # ── Long-term value ────────────────────────────
        if "long_term_value" in dims:
            ltv = dims["long_term_value"]
            text = content_text
            ltv_score = 0
            matched_topics = []
            for topic_cfg in ltv.get("topics", []):
                for kw in topic_cfg.get("terms", []):
                    if _contains_term(text, kw):
                        ltv_score += topic_cfg.get("score", 1)
                        matched_topics.append(topic_cfg.get("label", kw))
                        break
            ltv_score = min(ltv_score, ltv.get("max_score", 5))
            weighted = ltv_score * ltv.get("weight", 1.0)
            scores["long_term_value"] = ltv_score
            breakdown[labels.get("long_term_value", "long_term_value")] = round(weighted, 1)
            total += weighted

            # Reasons: long-term value topics
            for topic in matched_topics[:2]:
                reasons.append(reasons_cfg.get("long_term_topic",
                    f"长期价值: {topic}").replace("{topic}", topic))

        item["_scores"] = scores
        item["breakdown"] = breakdown
        item["_total_score"] = round(total, 1)
        item["_reasons"] = reasons

    # Filter & sort
    min_rel = config.get("min_relevance_score", 0)
    if min_rel > 0:
        items = [it for it in items if it.get("_scores", {}).get("relevance", 0) >= min_rel]
    items = [it for it in items if it.get("_total_score", 0) >= min_score]
    items.sort(key=lambda x: x.get("_total_score", 0), reverse=True)
    return items


def deduplicate(items):
    """Remove exact title duplicates. Track multi-source count."""
    seen = {}
    unique = []
    for item in items:
        key = re.sub(r"\W+", " ", item.get("title", "").lower()).strip()
        item.setdefault("_merged_evidence", [_source_evidence(item)])
        if key in seen:
            for record in item["_merged_evidence"]:
                if record not in seen[key]["_merged_evidence"]:
                    seen[key]["_merged_evidence"].append(record)
            # Record which sources reported this event
            src = item.get("source_name", "unknown")
            existing_srcs = seen[key].get("_related_sources", [])
            if src not in existing_srcs:
                existing_srcs.append(src)
                seen[key]["_related_sources"] = existing_srcs
            seen[key]["_multi_source_count"] = len(existing_srcs)
            continue
        seen[key] = item
        item["_multi_source_count"] = 1
        item["_related_sources"] = [item.get("source_name", "unknown")]
        unique.append(item)
    return unique


def apply_multi_source_boost(items, boost=10):
    """Boost _total_score for items found in multiple sources. Add reason."""
    for item in items:
        count = item.get("_multi_source_count", 1)
        if count >= 2:
            item["_total_score"] += boost
            reasons = item.get("_reasons", [])
            srcs = item.get("_related_sources", [])
            reasons.append(f"多源报道（不代表独立核实；{count} 个信源: {', '.join(srcs[:3])}）")
            item["_reasons"] = reasons
    items.sort(key=lambda x: x.get("_total_score", 0), reverse=True)
    return items


def filter_low_quality(items, patterns=None):
    """Pre-filter: mark low-quality community posts."""
    if patterns is None:
        patterns = [
            r"^(first|new)\s+(post|here).*",
            r"^(how|has anyone|does anyone|can someone|anyone else)\s",
            r"^(just|finally|grateful|excited|hello|hi|hey)\b",
            r"\b(rant|vent|frustrat|angry|pissed|terrible|awful|sucks?)\b",
            r"^\[meta\]",
        ]
    for item in items:
        src = item.get("source_tier", "")
        name = item.get("source_name", "").lower()
        if src == "community" or "reddit" in name:
            title = item.get("title", "")
            for pat in patterns:
                if re.search(pat, title, re.IGNORECASE):
                    item["_total_score"] = -999
                    item["_quality_flag"] = "low_quality"
                    break
    return items


# ── Internal helpers ────────────────────────────────────

def _tier_weight(source_tier, tier_map):
    """Look up tier weight from config's tier definitions."""
    tier_info = tier_map.get(source_tier, {})
    return tier_info.get("weight", 30)


def _age_hours(published_str):
    """Parse ISO/RFC date string and return age in hours. None on failure."""
    if not published_str:
        return None
    try:
        clean = published_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() / 3600
    except Exception:
        pass
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(published_str)
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() / 3600
    except Exception:
        return None
