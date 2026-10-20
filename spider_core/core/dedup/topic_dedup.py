"""
Cross-day topic-level deduplication via bigram Jaccard similarity.

Detects items covering the same topic as content from the past 7 days.
Complements Redis URL-exact dedup and same-day title dedup.

Usage:
    from core.dedup.topic_dedup import TopicDedup

    td = TopicDedup("ai", base_dir=memory_dir)
    td.load_recent(days=7)

    for item in items:
        if td.is_duplicate(item["title"], item.get("description", "")):
            item["_topic_duplicate"] = True
            item["_total_score"] *= 0.5

    td.save(items, today)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def _bigrams(text: str) -> set[str]:
    """Extract character bigrams from normalized text.

    Works for both Chinese (meaningful character pairs) and English
    (character pairs within words). Simple, fast, language-agnostic.
    """
    # Normalize: lowercase, collapse whitespace, strip most punctuation
    text = text.lower().strip()
    text = re.sub(r'[^\w\s一-鿿]', '', text)
    text = re.sub(r'\s+', ' ', text)

    if len(text) < 2:
        return {text} if text else set()

    return {text[i:i + 2] for i in range(len(text) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity: |intersection| / |union|."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union > 0 else 0.0


class TopicDedup:
    """Cross-day topic deduplication using bigram overlap.

    Stores bigram sets from report items. On subsequent days,
    checks new items for significant overlap with past items.
    """

    def __init__(self, domain: str, base_dir: Path | None = None) -> None:
        self.domain = domain
        self._base = base_dir or Path.cwd()
        self._mem_dir = self._base / domain
        self._mem_dir.mkdir(parents=True, exist_ok=True)
        self._fp_path = self._mem_dir / "topic_fingerprints.json"
        self._past_items: list[dict[str, Any]] = []

    def load_recent(self, days: int = 7) -> int:
        """Load fingerprint records from past N days. Returns count."""
        if not self._fp_path.exists():
            return 0

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        try:
            data = json.loads(self._fp_path.read_text(encoding="utf-8"))
        except Exception:
            return 0

        self._past_items = [fp for fp in data if fp.get("date", "") >= cutoff]
        # Pre-compute bigram sets for fast comparison
        for item in self._past_items:
            if "bigrams" not in item:
                item["_bg_set"] = _bigrams(
                    item.get("title", "") + " " + item.get("desc", "")
                )
            else:
                item["_bg_set"] = set(item["bigrams"])
        return len(self._past_items)

    def is_duplicate(self, title: str, description: str = "",
                     min_shared: int = 12) -> bool:
        """Check if content shares enough bigrams with any past item.

        Uses character-bigram overlap as the primary signal.
        min_shared=12 means 12+ shared 2-char sequences trigger dedup.
        This catches same-topic content even when wording differs
        (e.g., 'Claude 4.7 发布' vs 'Anthropic 推出 Claude Opus 4.7').
        """
        if not self._past_items or not title:
            return False

        bg = _bigrams(title + " " + (description or ""))

        for past in self._past_items:
            past_bg = past.get("_bg_set", set())
            if not past_bg:
                continue
            if len(bg & past_bg) >= min_shared:
                return True
        return False

    def save(self, items: list[dict], date_str: str) -> int:
        """Save bigram fingerprints for today's items.

        Appends to existing file, prunes entries older than 14 days.
        Returns number of new items saved.
        """
        existing = []
        if self._fp_path.exists():
            try:
                existing = json.loads(self._fp_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        # Remove existing entries for today (re-running)
        existing = [fp for fp in existing if fp.get("date") != date_str]

        new_items = []
        for item in items:
            title = item.get("title", "")
            desc = item.get("description", "")
            if len(title) < 10:
                continue
            bg = _bigrams(title + " " + desc)
            new_items.append({
                "date": date_str,
                "title": title[:80],
                "desc": desc[:120] if desc else "",
                "bigrams": sorted(bg)[:200],  # store as sorted list for JSON
            })

        existing.extend(new_items)

        # Prune: keep last 14 days
        cutoff = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
        existing = [fp for fp in existing if fp.get("date", "") >= cutoff]

        tmp = self._fp_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._fp_path)

        return len(new_items)

    def fingerprint_items(self, items: list[dict]) -> tuple[list[dict], int]:
        """Check and mark topic duplicates. Mutates items in-place.

        Sets _topic_duplicate=True and reduces _total_score by 50%
        for items that overlap significantly with past content.

        Returns (items, duplicate_count).
        """
        dup_count = 0
        for item in items:
            if self.is_duplicate(
                item.get("title", ""),
                item.get("description", ""),
            ):
                item["_topic_duplicate"] = True
                old_score = item.get("_total_score", 0)
                item["_total_score"] = old_score * 0.5
                dup_count += 1
        return items, dup_count
