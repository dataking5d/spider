"""
AI Intelligence Officer — News Fetcher v2
==========================================
Four-tier data source architecture.
Fetches AI news, scores by relevance, filters by real-world impact criteria.
Outputs structured JSON for Claude analysis.
"""

import json
import os
import re
import sys
import time
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin, quote

if sys.platform == "win32" and sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
import warnings
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# ── Paths ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR / "spider_core"))
from core.logger import log_event
from core.structured_logger import SpiderLogger
from scoring.engine import score_items, deduplicate, apply_multi_source_boost, filter_low_quality
from core.dedup import RedisDedupPipeline
from core.dashboard import start_http_server
from domains.ai.event_merger import same_event

def log(msg):
    log_event("ai", msg, base_dir=BASE_DIR / "logs")

slog = SpiderLogger("ai", base_dir=BASE_DIR / "logs")
CONFIG_PATH = BASE_DIR / "config.json"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

with open(CONFIG_PATH, encoding="utf-8") as f:
    CFG = json.load(f)

SCORING_CONFIG_PATH = BASE_DIR / "domains" / "ai" / "scoring_config.json"
with open(SCORING_CONFIG_PATH, encoding="utf-8") as f:
    SCORING_CFG = json.load(f)

# Generic words such as "free", "replace" or "自动化" require an AI context.
# Keep this domain rule out of the shared engine's defaults.
AI_CONTEXT_TERMS = [
    "ai", "artificial intelligence", "llm", "gpt", "chatgpt", "openai",
    "anthropic", "claude", "codex", "agent", "agentic", "mcp", "rag",
    "deepmind", "gemini", "llama", "qwen", "deepseek", "manus", "astra", "ling",
    "machine learning", "deep learning", "generative", "diffusion",
    "genai", "language model", "local model", "foundation model", "vllm", "lora",
    "人工智能", "大模型", "智能体", "机器学习", "深度学习", "生成式",
]
SCORING_CFG["dimensions"]["relevance"]["context_terms"] = AI_CONTEXT_TERMS

# config.json owns the 9 criteria and their weights; scoring_config.json owns the
# engine parameters. Both declared a minimum relevance gate and they disagreed
# (15 vs 10) — only the engine's was ever read, so config.json's
# `minimum_criteria_score` was dead config and the effective gate was 10, which
# is exactly the weight of the weakest rule, community_growth. One
# `trending` / `增长` substring was therefore enough to qualify an item alone:
# the 2026-09-21 run admitted two 淘宝双11 shopping promos into the AI report on
# that single criterion. Honor the threshold the domain actually declares.
_criteria_min = CFG.get("filtering_criteria", {}).get("minimum_criteria_score")
if _criteria_min:
    SCORING_CFG["min_relevance_score"] = _criteria_min

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
}

# For blog scrapers that need browser-like headers (no Sec-Fetch)
BLOG_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

TIMEOUT = CFG["token_budget"]["fetch_timeout_seconds"]
MAX_CHARS = CFG["token_budget"]["raw_json_max_chars_per_item"]


from core.domain_status import write_domain_status

STATUS_PATH = BASE_DIR / "pipeline_status.json"


def _clean(text, max_len=MAX_CHARS):
    if not text:
        return ""
    try:
        soup = BeautifulSoup(str(text), "html.parser")
        clean = soup.get_text(separator=" ", strip=True)
    except Exception:
        clean = str(text)
    return clean[:max_len].strip()


def _parse_points(text):
    """Extract numeric points from strings like '36 points'."""
    if isinstance(text, (int, float)):
        return int(text)
    m = re.search(r'(\d+)', str(text))
    return int(m.group(1)) if m else 0


# ── RSS Fetcher ────────────────────────────────────────
def fetch_rss(feed_cfg, tier_weight):
    """Fetch and parse a standard RSS feed."""
    items = []
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    w = feed_cfg.get("weight", 50)

    # Fetch through the retrying session rather than letting feedparser issue its
    # own request. feedparser sends a default User-Agent that a number of feeds
    # reject outright and retries nothing, so one transient failure — or a UA-based
    # block — silently yielded 0 items for the entire day, with no error recorded
    # and the source still reported as OK. Several feeds were written off as dead
    # on that basis. Fall back to feedparser's own fetch if this fails, so the
    # path is never worse than it was.
    #
    # The fallback must not launder a real failure into a silent empty, though:
    # a 429 (Reddit's anonymous .rss quota is ~2 requests per window) and a
    # genuinely quiet feed both arrived at the caller as status="ok", items=0,
    # which makes a rate-limited source indistinguishable from an idle one in
    # health.log. HTTP 200 with no entries is a real empty and still returns [];
    # anything else is raised so the caller records FAILED.
    try:
        resp = _requests_retry_session().get(
            url, timeout=CFG["token_budget"].get("fetch_timeout_seconds", 20))
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as primary_err:
        feed = feedparser.parse(url)
        http_status = getattr(feed, "status", None)
        if not feed.entries and http_status != 200:
            raise RuntimeError(
                f"{name}: session fetch failed ({type(primary_err).__name__}: "
                f"{str(primary_err)[:80]}); fallback HTTP status={http_status}"
            ) from primary_err
    if feed.bozo and not feed.entries:
        return items

    max_n = CFG["token_budget"].get("max_items_per_feed", 10)
    for entry in feed.entries[:max_n]:
        try:
            item = {
                "id": hashlib.md5(
                    (entry.get("link", entry.get("title", ""))).encode()
                ).hexdigest()[:12],
                "title": _clean(entry.get("title", ""), 200),
                "link": entry.get("link", "").strip(),
                "description": _clean(
                    entry.get("description", entry.get("summary", ""))
                ),
                "published": entry.get("published", entry.get("updated", "")),
                "source_name": name,
                "source_tier": feed_cfg.get("category", "unknown"),
                "source_weight": w,
                "tier_weight": tier_weight,
                "points": 0,
                "comments_count": 0,
            }
            items.append(item)
        except Exception:
            continue  # Skip malformed entry, keep the rest

    return items


# ── GitHub Trending Fetcher ────────────────────────────
def fetch_github_trending(feed_cfg, tier_weight):
    """Scrape GitHub trending page for AI-related repos."""
    items = []
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    w = feed_cfg.get("weight", 50)

    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    repos = soup.select("article.Box-row")[:15]
    for repo in repos:
        try:
            h2 = repo.select_one("h2 a")
            if not h2:
                continue
            href = h2.get("href", "").strip()

            desc_el = repo.select_one("p.col-9")
            desc = desc_el.text.strip() if desc_el else ""

            lang_el = repo.select_one('[itemprop="programmingLanguage"]')
            lang = lang_el.text.strip() if lang_el else ""

            stars_el = repo.select_one(".Link--muted.d-inline-block")
            stars_text = stars_el.text.strip() if stars_el else "0"
            stars = _parse_points(stars_text.replace(",", ""))

            title = href.strip("/")
            full_link = urljoin("https://github.com", href)

            # Only AI-related repos
            ai_terms = [
                "ai", "llm", "gpt", "agent", "ml", "deep-learning",
                "transformer", "diffusion", "chatgpt", "rag",
                "langchain", "llama", "whisper", "stable-diffusion",
                "nlp", "computer-vision", "tts", "embedding",
                "vector", "fine-tun", "prompt", "mcp", "tool-call"
            ]
            combined = (title + " " + desc + " " + lang).lower()
            if not any(t in combined for t in ai_terms):
                continue

            item = {
                "id": hashlib.md5(full_link.encode()).hexdigest()[:12],
                "title": title,
                "link": full_link,
                "description": f"[GitHub Stars: {stars}] {desc}",
                "published": "",
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "source_name": name,
                "source_tier": feed_cfg.get("category", "unknown"),
                "source_weight": w,
                "tier_weight": tier_weight,
                "points": stars,
                "comments_count": 0,
            }
            items.append(item)
        except Exception:
            continue  # Skip malformed repo, keep the rest

    return items


# ── Anthropic Blog Scraper ─────────────────────────────
def _parse_text_date(raw_text):
    """Extract ISO date from text like 'Apr 16, 2026' or 'April 8, 2026'."""
    months = {"jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,
              "apr":4,"april":4,"may":5,"jun":6,"june":6,
              "jul":7,"july":7,"aug":8,"august":8,"sep":9,"september":9,
              "oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12}
    m = re.search(
        r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|'
        r'jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|'
        r'nov(?:ember)?|dec(?:ember)?)\s*(\d{1,2}),?\s*(\d{4})',
        raw_text, re.IGNORECASE
    )
    if m:
        mon = months.get(m.group(1).lower())
        day = int(m.group(2))
        year = int(m.group(3))
        if mon and 1 <= day <= 31:
            return f"{year}-{mon:02d}-{day:02d}T00:00:00+00:00"
    return None


def _clean_anthropic_title(raw_text):
    """Strip date prefix and category labels from Anthropic blog card text."""
    # Remove date: "Apr 16, 2026", "May 19, 2026"
    text = re.sub(
        r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*\d{1,2},?\s*\d{4}',
        '', raw_text, flags=re.IGNORECASE
    )
    # Remove category labels
    text = re.sub(
        r'\b(Product|Announcements?|Research|Engineering|Company|Perspectives|Events)\b',
        '', text
    )
    # Split camelCase concatenations: "Opus 4.7Product" → "Opus 4.7 Product"
    text = re.sub(r'([a-z])([A-Z])', r'\1 \2', text)
    text = re.sub(r'(\d)([A-Z])', r'\1 \2', text)
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:200] if text else ""


def fetch_anthropic_blog(feed_cfg, tier_weight):
    """Scrape anthropic.com/news for latest posts (no RSS available)."""
    items = []
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    w = feed_cfg.get("weight", 50)

    r = requests.get(url, headers=BLOG_HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = soup.select('a[href*="/news/"]')
    seen = set()
    for a in links[:15]:
        try:
            href = a.get("href", "").strip()
            raw_text = a.get_text(strip=True)
            if not href or not raw_text:
                continue

            # Extract real publish date from card text
            pub_date = _parse_text_date(raw_text)
            # If we can't find a date, assume 7 days old (conservative default)
            if pub_date is None:
                pub_date = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

            # Clean title
            title = _clean_anthropic_title(raw_text)
            if len(title) < 15:
                continue

            full_url = urljoin("https://www.anthropic.com", href)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Extract description: text after title in the raw content
            desc = ""
            title_pos = raw_text.lower().find(title.lower()[:30])
            if title_pos >= 0:
                remaining = raw_text[title_pos + len(title):].strip()
                # Remove leftover date/category fragments from description
                remaining = re.sub(
                    r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s*\d{1,2},?\s*\d{4}',
                    '', remaining, flags=re.IGNORECASE
                )
                remaining = re.sub(
                    r'\b(Product|Announcements?|Research|Engineering|Company|Perspectives|Events)\b',
                    '', remaining
                )
                remaining = re.sub(r'([a-z])([A-Z])', r'\1 \2', remaining)
                remaining = re.sub(r'\s+', ' ', remaining).strip()
                if len(remaining) > 20:
                    desc = remaining

            item = {
                "id": hashlib.md5(full_url.encode()).hexdigest()[:12],
                "title": title,
                "link": full_url,
                "description": _clean(desc),
                "published": pub_date,
                "source_name": name,
                "source_tier": feed_cfg.get("category", "unknown"),
                "source_weight": w,
                "tier_weight": tier_weight,
                "points": 0,
                "comments_count": 0,
            }
            items.append(item)
        except Exception:
            continue

    return items


# ── Meta AI Blog Scraper ────────────────────────────────
def fetch_meta_blog(feed_cfg, tier_weight):
    """Scrape ai.meta.com/blog for latest posts (no RSS available)."""
    items = []
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    w = feed_cfg.get("weight", 50)

    session = requests.Session()
    meta_ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    meta_timeout = (5, TIMEOUT)  # short connect, normal read
    # First get cookies from homepage
    session.get("https://ai.meta.com/", headers=meta_ua, timeout=meta_timeout)
    # Then fetch blog page (Meta only accepts minimal headers)
    r = session.get(url, headers=meta_ua, timeout=meta_timeout)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    links = soup.select('a[href*="/blog/"]')
    seen = set()
    skip_words = {"featured", "read more", "learn more", "subscribe", "menu"}
    for a in links[:20]:
        try:
            href = a.get("href", "").strip()
            text = a.get_text(strip=True)
            if not href or not text or len(text) < 15 or text.lower() in skip_words:
                continue
            full_url = urljoin("https://ai.meta.com", href)
            if full_url in seen:
                continue
            seen.add(full_url)

            # Try to find description in parent element
            parent = a.find_parent("div") or a.find_parent("li")
            desc = ""
            if parent:
                p_tag = parent.select_one("p")
                if p_tag:
                    desc = p_tag.get_text(strip=True)

            # Extract date from parent/grandparent text
            grandparent = parent.find_parent("div") if parent else None
            date_text = (parent.get_text() if parent else "") + " " + (grandparent.get_text() if grandparent else "")
            pub_date = _parse_text_date(date_text)
            if not pub_date:
                pub_date = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

            item = {
                "id": hashlib.md5(full_url.encode()).hexdigest()[:12],
                "title": text[:200],
                "link": full_url,
                "description": _clean(desc),
                "published": pub_date,
                "source_name": name,
                "source_tier": feed_cfg.get("category", "unknown"),
                "source_weight": w,
                "tier_weight": tier_weight,
                "points": 0,
                "comments_count": 0,
            }
            items.append(item)
        except Exception:
            continue

    return items


# ── Papers with Code Scraper ────────────────────────────
def _requests_retry_session(retries=2, backoff_factor=1.0):
    """Session with retry on transient network errors (ConnectionError, ConnectTimeout, etc.)."""
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(HEADERS)
    return session


def fetch_paperswithcode(feed_cfg, tier_weight):
    """Fetch trending papers from HuggingFace daily papers API.

    paperswithcode.com now redirects to huggingface.co/papers/trending.
    Using the JSON API is faster and more reliable than HTML scraping.
    """
    items = []
    name = feed_cfg["name"]
    url = feed_cfg["url"]
    w = feed_cfg.get("weight", 50)
    max_n = CFG["token_budget"].get("max_items_per_feed", 10)

    session = _requests_retry_session()
    r = session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    papers = r.json()

    for paper in papers[:max_n]:
        try:
            p = paper.get("paper", {})
            if not p:
                continue
            title = p.get("title", "")
            arxiv_id = p.get("id", "")
            summary = p.get("summary", "")
            pub_date = p.get("publishedAt") or p.get("submittedOnDailyAt", "")
            upvotes = paper.get("upvotes", 0)
            link = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""

            if not title or not link:
                continue

            # Build description from summary + authors
            authors = [a.get("name", "") for a in p.get("authors", [])[:3]]
            author_str = ", ".join(authors) if authors else ""
            desc_parts = [summary[:500]] if summary else []
            if author_str:
                desc_parts.append(f"[Authors: {author_str}]")
            desc_parts.append(f"[Upvotes: {upvotes}]")
            description = " ".join(desc_parts)

            item = {
                "id": hashlib.md5(link.encode()).hexdigest()[:12],
                "title": title[:200],
                "link": link,
                "description": _clean(description),
                "published": pub_date,
                "source_name": name,
                "source_tier": feed_cfg.get("category", "unknown"),
                "source_weight": w,
                "tier_weight": tier_weight,
                "points": upvotes,
                "comments_count": 0,
            }
            items.append(item)
        except Exception:
            continue

    return items


# ── Unified fetcher dispatch ───────────────────────────
FETCHERS = {
    "rss": fetch_rss,
    "github_trending": fetch_github_trending,
    "anthropic_blog": fetch_anthropic_blog,
    "meta_blog": fetch_meta_blog,
    "paperswithcode": fetch_paperswithcode,
}


def fetch_one(feed_cfg, tier_weight):
    """Fetch one source with full error isolation.

    Returns (items, health) where health is {name, status, items, error}.
    The caller can continue safely regardless of the outcome.
    """
    name = feed_cfg["name"]
    ftype = feed_cfg.get("type", "rss")
    fetcher = FETCHERS.get(ftype, fetch_rss)

    try:
        items = fetcher(feed_cfg, tier_weight)
        n = len(items)
        log(f"  {name} fetched: {n} items")
        slog.info("source_fetched", stage="fetch", source=name, items=n, status="ok")
        return items, {"name": name, "status": "OK", "items": n, "error": None}
    except Exception as e:
        err_msg = str(e)[:120]
        log(f"  {name} FAILED: {err_msg}")
        print(f"    [FAIL] {name}: {err_msg}")
        slog.error("source_failed", stage="fetch", source=name, status="failed", error=err_msg)
        return [], {"name": name, "status": "FAILED", "items": 0, "error": err_msg}


# ── Entity clustering ──────────────────────────────────
def _extract_entities(title, entity_config):
    """Extract matching entities from a title. Returns set of (category, entity) tuples."""
    found = set()
    lower = title.lower()
    for category in ("companies", "products", "technologies"):
        for entity in entity_config.get(category, []):
            if entity in lower:
                found.add((category, entity))
    return found


def cluster_by_entities(items, entity_config):
    """Group matching article URLs/titles; entities are topic hints only.

    Assigns _cluster_id to each item. Two items are unioned only when they share
    a matching URL or complete title and come from different sources.
    Real cluster ids start at 1, so `_cluster_id > 0` means "clustered" and 0 never
    appears. When no entity config is supplied, every item gets a unique negative id
    — i.e. no clustering at all.
    """
    if not entity_config:
        for i, it in enumerate(items):
            it["_cluster_id"] = -(i + 1)
        return items

    # Extract entities per item
    item_entities = []
    for it in items:
        entities = _extract_entities(it.get("title", ""), entity_config)
        item_entities.append(entities)

    # Union-find on clear article identity, never on shared vendor/topic alone.
    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            # Don't cluster same-source items — that's NOT cross-source dedup
            if items[i].get("source_name") == items[j].get("source_name"):
                continue
            if same_event(items[i], items[j]):
                union(i, j)

    # Assign cluster IDs, starting at 1 so 0 is never a real cluster. Callers read
    # `_cluster_id > 0` as "clustered" (event_merger does exactly that), so when 0
    # was a legitimate id, one cluster per run was silently never merged while
    # `_cluster_multi_source` still flagged it — Python told the LLM to merge a
    # group Python had itself refused to merge.
    cluster_roots = {}
    next_cluster = 1
    for i in range(len(items)):
        root = find(i)
        if root not in cluster_roots:
            # Only create a real cluster if it has at least 2 members
            # (otherwise it's a singleton — no clustering needed)
            cluster_roots[root] = next_cluster
            next_cluster += 1
        items[i]["_cluster_id"] = cluster_roots[root]
        items[i]["_cluster_entities"] = sorted(item_entities[i])

    # Tag clusters with ≥2 members from different sources
    cluster_sources = {}
    for it in items:
        cid = it["_cluster_id"]
        if cid not in cluster_sources:
            cluster_sources[cid] = set()
        cluster_sources[cid].add(it.get("source_name"))

    multi_source_clusters = {cid for cid, srcs in cluster_sources.items() if len(srcs) >= 2}

    for it in items:
        it["_cluster_multi_source"] = it["_cluster_id"] in multi_source_clusters

    return items


# ── Scoring pipeline ──────────────────────────────────
def _fuzzy_description_dedup(items, threshold=0.75):
    """Catch near-duplicate descriptions missed by exact-title dedup.

    Compares first 200 chars of description. Items with >threshold similarity
    AND from different sources are merged (keep the higher-scored one).
    Returns (items, removed_count).
    """
    import difflib

    kept = []
    for item in items:
        desc = item.get("description", "")[:200]
        if len(desc) < 60:
            kept.append(item)
            continue

        is_dup = False
        for existing in kept:
            existing_desc = existing.get("description", "")[:200]
            if len(existing_desc) < 60:
                continue
            # Only cross-source (same-source dupes already handled by title dedup)
            if item.get("source_name") == existing.get("source_name"):
                continue
            if not same_event(item, existing):
                continue
            ratio = difflib.SequenceMatcher(None, desc, existing_desc).ratio()
            if ratio >= threshold:
                evidence = existing.get("_merged_evidence", []) + item.get("_merged_evidence", [])
                # Keep higher-scored one, carry over multi-source info
                if item.get("_total_score", 0) > existing.get("_total_score", 0):
                    item["_multi_source_count"] = existing.get("_multi_source_count", 1) + 1
                    srcs = existing.get("_related_sources", [])
                    srcs.append(item.get("source_name", "unknown"))
                    item["_related_sources"] = srcs
                    kept[kept.index(existing)] = item
                    item["_merged_evidence"] = evidence
                else:
                    existing["_multi_source_count"] = existing.get("_multi_source_count", 1) + 1
                    src = item.get("source_name", "unknown")
                    if src not in existing.get("_related_sources", []):
                        existing["_related_sources"].append(src)
                    existing["_merged_evidence"] = evidence
                is_dup = True
                break

        if not is_dup:
            kept.append(item)

    return kept, len(items) - len(kept)


def run_scoring_pipeline(items):
    """Apply shared scoring engine with AI domain config.
    Returns (items, stats_dict).
    """
    before = len(items)
    items = filter_low_quality(items)
    quality_filtered = before - len(items)
    items = [it for it in items if it.get("_quality_flag") != "low_quality"]
    quality_filtered += before - len(items) - quality_filtered  # items removed by flag check
    actually_quality_filtered = before - len(items)

    items = score_items(items, SCORING_CFG)
    before_dedup = len(items)
    items = deduplicate(items)
    title_dedup_removed = before_dedup - len(items)

    # Fuzzy description dedup (cross-source, as safety net)
    items, fuzzy_dedup_removed = _fuzzy_description_dedup(items)

    items = apply_multi_source_boost(items)

    # Shared English character pairs do not prove a repeated topic. The previous
    # 12-bigram rule halved 105/112 selected items, including unrelated events.
    # Successful publication + unchanged source text is now the cross-day gate.
    for item in items:
        item.pop("_topic_duplicate", None)
    log("  Topic overlap discount disabled; using successful-publication history")

    # Entity-based cross-source clustering (last step — after all scoring)
    entity_cfg = SCORING_CFG.get("entity_clusters")
    items = cluster_by_entities(items, entity_cfg)

    stats = {
        "pipeline_input": before,
        "quality_filtered": actually_quality_filtered,
        "title_dedup_removed": title_dedup_removed,
        "fuzzy_description_dedup_removed": fuzzy_dedup_removed,
        "topic_dedup_downgraded": 0,
        "total_removed": before - len(items),
        "output": len(items),
    }
    return items, stats


def select_diverse(items, limit, max_per_source):
    """Take the top `limit` items by score, but at most `max_per_source` per source.

    Why this exists: `_total_score` is dominated by `source_weight`, which is a
    constant per source (60-200) and larger than freshness + community_heat +
    long_term_value combined. Ranking by raw score therefore let one feed take
    most of the report — on 2026-09-20 GitHub Trending Python took 12 of 16 slots
    while 12 other live sources contributed nothing. The cut, not the scoring, is
    what decides the report's composition, so the constraint belongs here.

    Surplus slots are backfilled by score, so a pool smaller than `limit *
    max_per_source` still fills the prompt. Pass max_per_source <= 0 to restore
    the plain top-N cut.

    Returns (selected_items, per_source_counts).
    """
    if not max_per_source or max_per_source <= 0:
        picked = items[:limit]
        counts = {}
        for it in picked:
            s = it.get("source_name", "?")
            counts[s] = counts.get(s, 0) + 1
        return picked, counts

    picked, overflow, counts = [], [], {}
    for it in items:
        if len(picked) >= limit:
            break
        src = it.get("source_name", "?")
        if counts.get(src, 0) < max_per_source:
            picked.append(it)
            counts[src] = counts.get(src, 0) + 1
        else:
            overflow.append(it)
    for it in overflow[:limit - len(picked)]:
        picked.append(it)
        src = it.get("source_name", "?")
        counts[src] = counts.get(src, 0) + 1
    return picked, counts


def _published_content(item):
    """Ignore counters and feed boilerplate, but keep substantive text/links."""
    text = (item.get("title") or "") + " " + (item.get("description") or "")
    text = re.sub(r"\[GitHub Stars:\s*[\d,]+\]|\[Upvotes:\s*\d+\]", " ", text,
                  flags=re.IGNORECASE)
    text = re.sub(r"(?:Points|#\s*Comments):\s*\d+", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"submitted by\s+/u/\S+\s*\[link\]\s*\[comments\]", " ", text,
                  flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip().casefold()


def filter_published_items(items, history_path, today=None):
    """Skip unchanged URLs actually published in the previous seven days.

    The report writer alone maintains this ledger after successful publication.
    Unselected fetch results and changed content remain eligible.
    """
    history_path = Path(history_path)
    if not history_path.exists():
        return items, 0
    history = json.loads(history_path.read_text(encoding="utf-8"))
    if not isinstance(history, list) or any(not isinstance(row, dict) for row in history):
        raise ValueError("published_sources.json must contain a list of source records")
    today = today or datetime.now().strftime("%Y-%m-%d")
    cutoff = (datetime.fromisoformat(today) - timedelta(days=7)).strftime("%Y-%m-%d")
    published = {(row.get("link"), _published_content(row)) for row in history
                 if row.get("link") and cutoff <= row.get("published_on", "") <= today}
    kept = [item for item in items
            if (item.get("link"), _published_content(item)) not in published]
    return kept, len(items) - len(kept)


# ── Main ───────────────────────────────────────────────
def main():
    t0 = time.time()
    today = datetime.now().strftime("%Y-%m-%d")
    total_feeds = 0
    total_items = 0

    log("Stage 1: Fetch started")
    slog.info("pipeline_start", stage="init", max_items=CFG["filtering_criteria"]["max_items_for_report"])
    print(f"\n{'=' * 60}")
    print(f"  AI Intelligence Officer — News Fetcher v2")
    print(f"  Date: {today}  |  Max items for report: {CFG['filtering_criteria']['max_items_for_report']}")
    print(f"{'=' * 60}")

    # ── Dashboard HTTP server (no-op if daemon already running) ──
    httpd = start_http_server(BASE_DIR)

    all_items = []
    source_health = []
    redis_seen_count = 0

    # Capture Redis dedup initial state for health reporting
    redis_dedup_stats_before = {}
    redis_dedup_stats_after = {}

    # ── Redis cross-day dedup ──
    dedup_cfg = CFG.get("redis_dedup", {})
    redis_dedup = None
    if dedup_cfg.get("enabled"):
        redis_dedup = RedisDedupPipeline(
            redis_url=dedup_cfg.get("redis_url", "redis://localhost:6379/0"),
            key_prefix=dedup_cfg.get("key_prefix", "dedup:ai"),
            logger=slog,
            fallback_permissive=True,
        )
        if redis_dedup.redis_available:
            ds = redis_dedup.stats()
            redis_dedup_stats_before = ds
            print(f"\n  [Redis Dedup ENABLED] {ds['simhash_total_fingerprints']} fingerprints stored")
        else:
            redis_dedup_stats_before = {"redis_available": False}
            print(f"\n  [Redis Dedup DEGRADED] Redis unavailable — all content passes through")
    else:
        redis_dedup_stats_before = {"enabled": False}
    tiers = [
        ("tier_1_official",   "TIER 1: Official AI Sources"),
        ("tier_2_tech_trends", "TIER 2: Tech Trends & Open Source"),
        ("tier_3_community",   "TIER 3: Community & Real Usage"),
        ("tier_4_products",    "TIER 4: AI Products & Commercialization"),
        ("chinese_sources",    "CHINESE: Supplementary"),
        ("media_sources",      "MEDIA: Adjusted Weight"),
    ]
    total_feed_count = sum(
        len(CFG["sources"][tk].get("feeds", []))
        for tk, _ in tiers
        if CFG["sources"].get(tk)
    )
    write_domain_status("ai", STATUS_PATH, phase="starting",
                        label="AI 前沿情报",
                        progress={"done": 0, "total": total_feed_count})

    for tier_key, tier_label in tiers:
        tier = CFG["sources"].get(tier_key)
        if not tier:
            continue
        tier_weight = tier.get("weight", 30)
        print(f"\n  [{tier_label}] (tier weight: {tier_weight})")

        for feed_cfg in tier.get("feeds", []):
            total_feeds += 1
            name = feed_cfg["name"]
            print(f"    Fetching {name} ...", end=" ")

            try:
                new_items, health = fetch_one(feed_cfg, tier_weight)

                # Redis records acquisition, not publication. A seen URL may
                # never have reached the report, or may now contain an update.
                # Only the successful-publication ledger below can suppress it.
                redis_seen = 0
                if redis_dedup:
                    for it in new_items:
                        content_text = it.get("title", "") + " " + it.get("description", "")
                        if not redis_dedup.is_new(it["link"], content_text):
                            redis_seen += 1

                label = f"{len(new_items)} items"
                if redis_seen:
                    label += f" ({redis_seen} previously fetched)"
                    redis_seen_count += redis_seen
                print(label)
                source_health.append(health)
                all_items.extend(new_items)
                total_items += len(new_items)
            except Exception as e:
                print(f"CRASH: {e}")
                log(f"  {name} CRASHED: {e}")
                slog.error("source_crashed", stage="fetch", source=name,
                           error=str(e)[:200], status="failed")
                source_health.append({
                    "name": name, "status": "FAILED",
                    "items": 0, "error": str(e)[:200]
                })

            failed_count = sum(1 for h in source_health if h["status"] == "FAILED")
            src_list = [{"name": h["name"],
                         "status": h["status"].lower() if h["status"] == "OK" else "failed",
                         "items": h.get("items", 0),
                         "error": h.get("error", "")} for h in source_health]
            write_domain_status("ai", STATUS_PATH, phase="fetching",
                                progress={"done": len(source_health), "total": total_feed_count},
                                sources=src_list, total_items=total_items,
                                failed_count=failed_count)
            time.sleep(0.3)

    total_fetched = len(all_items)
    published_skipped = 0
    try:
        all_items, published_skipped = filter_published_items(
            all_items, BASE_DIR / "memory" / "ai" / "published_sources.json", today)
        if published_skipped:
            log(f"  Published-source dedup: {published_skipped} unchanged published items skipped")
    except (OSError, ValueError, TypeError) as error:
        log(f"  Published-source history unavailable; keeping candidates: {error}")

    # Scoring pipeline: quality filter → score → dedup → multi-source boost
    all_items, pipeline_stats = run_scoring_pipeline(all_items)
    slog.info("scoring_complete", stage="scoring", **pipeline_stats)
    failed_count = sum(1 for h in source_health if h["status"] == "FAILED")
    src_list = [{"name": h["name"],
                 "status": h["status"].lower() if h["status"] == "OK" else "failed",
                 "items": h.get("items", 0),
                 "error": h.get("error", "")} for h in source_health]
    write_domain_status("ai", STATUS_PATH, phase="scoring",
                        progress={"done": len(source_health), "total": total_feed_count},
                        sources=src_list, total_items=len(all_items),
                        failed_count=failed_count,
                        extra={"scoring": pipeline_stats})

    # Cap to max report items (plus buffer for Claude filtering). A plain score
    # cut is decided by source_weight alone, so apply a per-source ceiling —
    # see select_diverse() for why.
    fc = CFG["filtering_criteria"]
    max_out = fc["max_items_for_report"] * 2
    max_per_src = fc.get("report_max_per_source", 0)
    before_cap = len(all_items)
    all_items, src_counts = select_diverse(all_items, max_out, max_per_src)
    if before_cap > len(all_items):
        trimmed = before_cap - len(all_items)
        print(f"  Scoring → {before_cap}, capped to {len(all_items)} (max {max_out} for prompt)")
        slog.info("scoring_truncated", stage="scoring", before=before_cap, after=len(all_items), trimmed=trimmed, max_for_prompt=max_out)
    if max_per_src:
        comp = ", ".join(f"{s}×{c}" for s, c in
                         sorted(src_counts.items(), key=lambda kv: -kv[1]))
        print(f"  Composition (≤{max_per_src}/源, {len(src_counts)} 个源): {comp}")
        slog.info("report_composition", stage="output", sources=len(src_counts),
                  max_per_source=max_per_src, composition=src_counts)

    # Source health summary
    ok_count = sum(1 for h in source_health if h["status"] == "OK")
    fail_count = sum(1 for h in source_health if h["status"] == "FAILED")
    # A source that answers HTTP but yields nothing is still recorded as OK, so
    # the OK count alone cannot reveal a dead feed. Nine sources returned 0 items
    # every day for weeks while all 109 health reports read "23/23 OK, 0 FAILED".
    empty_count = sum(1 for h in source_health
                      if h["status"] == "OK" and h.get("items", 0) == 0)

    print(f"\n{'─' * 60}")
    print(f"  Feeds checked: {total_feeds}  |  OK: {ok_count}  |  FAILED: {fail_count}"
          f"  |  EMPTY (0 items): {empty_count}")
    print(f"  Fetched: {total_fetched} items")
    if published_skipped:
        print(f"  Published-source dedup: -{published_skipped} unchanged items")
    ps = pipeline_stats
    print(f"  Pipeline: {ps['pipeline_input']} → quality -{ps['quality_filtered']} → title dedup -{ps['title_dedup_removed']} → fuzzy dedup -{ps['fuzzy_description_dedup_removed']} → {ps['output']} items")
    print(f"  (Will be further curated by Claude to ~{CFG['filtering_criteria']['max_items_for_report']})")
    print(f"{'─' * 60}")

    # Print health status
    if fail_count > 0:
        print(f"\n  [SOURCE HEALTH]")
        for h in source_health:
            status_icon = "[OK]" if h["status"] == "OK" else "[FAIL]"
            detail = f" — {h['error']}" if h["error"] else f" — {h['items']} items"
            print(f"    {status_icon} {h['name']}{detail}")

    # Save
    # Capture after-run Redis stats for health JSON
    if redis_dedup and redis_dedup.redis_available:
        redis_dedup_stats_after = redis_dedup.stats()

    dedup_info = {
        "redis_enabled": dedup_cfg.get("enabled", False),
        "redis_available": redis_dedup_stats_before.get("redis_available", False),
        "redis_items_filtered": 0,
        "redis_items_previously_seen": redis_seen_count,
        "published_items_filtered": published_skipped,
        "redis_fingerprints_before": redis_dedup_stats_before.get("simhash_total_fingerprints", 0),
        "redis_fingerprints_after": redis_dedup_stats_after.get("simhash_total_fingerprints", 0),
        "pipeline_input": pipeline_stats["pipeline_input"],
        "quality_filtered": pipeline_stats["quality_filtered"],
        "title_dedup_removed": pipeline_stats["title_dedup_removed"],
        "fuzzy_description_dedup_removed": pipeline_stats["fuzzy_description_dedup_removed"],
    }

    output = {
        "fetch_date": today,
        "fetch_time_utc": datetime.now(timezone.utc).isoformat(),
        "total_feeds_checked": total_feeds,
        "total_items_fetched": total_fetched,
        "total_items_after_filter": len(all_items),
        "source_health": source_health,
        "dedup": dedup_info,
        "items": all_items,
        "runtime_s": round(time.time() - t0),
    }

    data_file = DATA_DIR / f"ai_news_raw_{today}.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    # Save topic fingerprints for cross-day dedup (top-scored items)
    try:
        from core.dedup.topic_dedup import TopicDedup as _TD
        _td_save = _TD("ai", base_dir=BASE_DIR / "memory")
        top_items = sorted(all_items, key=lambda x: x.get("_total_score", 0), reverse=True)[:30]
        _td_save.save(top_items, today)
    except Exception:
        pass

    log(f"  Data saved: {total_feeds} feeds, {ok_count} OK / {fail_count} FAILED"
        f", {empty_count} empty → {len(all_items)} items"
        f" (scored, then hard-capped — not a filtering result)")
    slog.info("data_saved", stage="output", feeds=total_feeds, ok_sources=ok_count,
              failed_sources=fail_count, empty_sources=empty_count,
              items=len(all_items), hard_cap=max_out)
    src_list = [{"name": h["name"],
                 "status": h["status"].lower() if h["status"] == "OK" else "failed",
                 "items": h.get("items", 0),
                 "error": h.get("error", "")} for h in source_health]
    write_domain_status("ai", STATUS_PATH, phase="fetch_done",
                        progress={"done": len(source_health), "total": total_feed_count},
                        sources=src_list, total_items=len(all_items),
                        failed_count=fail_count,
                        extra={"scoring": pipeline_stats})
    print(f"\n  [OK] Saved: {data_file}  ({ok_count}/{total_feeds} sources OK,"
          f" {empty_count} returned 0 items)")

    # Quick preview with breakdown + reasons
    print(f"\n{'=' * 60}")
    print(f"  PREVIEW (top by score)")
    print(f"{'=' * 60}")
    for i, item in enumerate(all_items[:15]):
        s = item.get("_total_score", 0)
        tier = item.get("source_tier", "?")
        pts = f" [{item.get('points', 0)}pts]" if item.get("points") else ""
        bd = item.get("breakdown", {})
        dims = "  ".join(f"{k}={v:.0f}" for k, v in bd.items())
        reasons = item.get("_reasons", [])
        reason_str = " | ".join(reasons[:3]) if reasons else ""
        print(f"  {i+1:2d}. [{s:6.1f}] {item['title'][:80]}")
        if dims:
            print(f"      {dims}")
        if reason_str:
            print(f"      → {reason_str}")

    print()
    if redis_dedup:
        redis_dedup.close()
    return str(data_file)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"  FATAL ERROR in Stage 1: {e}")
        sys.exit(1)
