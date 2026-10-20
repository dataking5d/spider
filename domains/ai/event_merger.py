"""
Event-level deduplication for AI Domain.
Groups items by _cluster_id, merges multi-source reports of the same event
into a single enriched item card.
"""

import re


def same_event(left, right):
    """Require matching article URLs or a complete matching informative title."""
    links = [(item.get("link") or "").split("#", 1)[0].rstrip("/")
             for item in (left, right)]
    if links[0] and links[0] == links[1]:
        return True
    titles = [re.sub(r"\W+", " ", item.get("title", "").casefold()).strip()
              for item in (left, right)]
    return len(titles[0]) >= 20 and titles[0] == titles[1]


def merge_events(items):
    """Merge items that share a _cluster_id from different sources.

    Only clusters with _cluster_id > 0 and >= 2 different sources are merged.
    Unclustered items (_cluster_id missing or <= 0) pass through unchanged.

    The `> 0` test is load-bearing and depends on an invariant held by the producer
    (fetch_ai_news.cluster_by_entities): real cluster ids start at 1. That producer
    used to start them at 0, which made this test drop one legitimate cluster per
    run — the cluster id 0 — while `_cluster_multi_source` (computed there without
    the same guard) still told the LLM to merge it. Keep the two in sync.

    Returns dict with enhanced_items and merge_stats.
    """
    clustered = {}
    unclustered = []

    for it in items:
        it["_reasons"] = [reason for reason in it.get("_reasons", [])
                          if not reason.startswith("多源验证")]
        cid = it.get("_cluster_id", 0)
        if cid and cid > 0:
            clustered.setdefault(cid, []).append(it)
        else:
            unclustered.append(it)

    # Saved data may still contain the old entity-only clusters. Recheck every
    # member; sharing a vendor and "agent" is not evidence of the same event.
    verified_groups = []
    for group in clustered.values():
        subgroups = []
        for item in group:
            for subgroup in subgroups:
                if all(same_event(item, other) for other in subgroup):
                    subgroup.append(item)
                    break
            else:
                subgroups.append([item])
        verified_groups.extend(subgroups)

    events_merged = 0
    duplicates_removed = 0
    merged_primaries = []

    for group in verified_groups:
        multiple_sources = len({item.get("source_name") for item in group}) >= 2
        for item in group:
            item["_cluster_multi_source"] = multiple_sources
            if not multiple_sources:
                item["_total_score"] = (item.get("_total_score", 0)
                                        - item.pop("_multi_source_boost", 0))
        if len(group) < 2 or not multiple_sources:
            merged_primaries.extend(group)
            continue

        # Sort by total_score desc — highest scored item is the primary
        group.sort(key=lambda x: x.get("_total_score", 0), reverse=True)
        primary = dict(group[0])  # shallow copy to avoid mutating original

        sources = []
        titles = []
        descriptions = []
        evidence = []
        all_criteria = set()

        for it in group:
            records = it.get("_merged_evidence") or [{key: it.get(key, "") for key in (
                "title", "link", "description", "source_name", "published", "observed_at")}]
            for record in records:
                if record not in evidence:
                    evidence.append(dict(record))
                src = record.get("source_name", "unknown")
                if src not in sources:
                    sources.append(src)
                title = record.get("title", "")
                if title and title not in titles:
                    titles.append(title)
                desc = record.get("description", "")
                if desc and len(desc) > 20 and desc not in descriptions:
                    descriptions.append(desc)
            for c in it.get("_matched_criteria", []):
                all_criteria.add(c)

        primary["_merged_sources"] = sources
        primary["_merged_titles"] = titles[:5]
        primary["_event_merge_count"] = len(group)
        primary["_merged_descriptions"] = descriptions[:3]
        primary["_merged_evidence"] = evidence
        primary["_matched_criteria"] = list(all_criteria)

        # Boost score for multi-source events: +5 per extra source, capped at +15
        boost = min(5 * (len(sources) - 1), 15)
        primary["_total_score"] = primary.get("_total_score", 0) + boost
        primary["_multi_source_boost"] = boost

        if "_reasons" not in primary:
            primary["_reasons"] = []
        primary["_reasons"] = list(primary["_reasons"])
        if len(sources) >= 2:
            primary["_reasons"].append("多源报道（不代表独立核实）")

        merged_primaries.append(primary)
        events_merged += 1
        duplicates_removed += len(group) - 1

    enhanced_items = merged_primaries + unclustered
    enhanced_items.sort(key=lambda x: x.get("_total_score", 0), reverse=True)

    return {
        "enhanced_items": enhanced_items,
        "merge_stats": {
            "items_before": len(items),
            "items_after": len(enhanced_items),
            "events_merged": events_merged,
            "duplicates_removed": duplicates_removed,
        },
    }
