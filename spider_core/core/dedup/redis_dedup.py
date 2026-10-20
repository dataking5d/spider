"""
Redis-backed two-layer deduplication pipeline.

Layer 1 — URL Bloom filter: exact URL dedup via Redis SETBIT/GETBIT.
Layer 2 — SimHash fuzzy dedup: content similarity via 4-block index,
          Hamming distance <= 3.

Graceful degradation: if Redis is unreachable, all content passes through
(logged as errors) rather than blocking the pipeline.

Usage:
    from core.dedup import RedisDedupPipeline

    pipeline = RedisDedupPipeline(redis_url="redis://localhost:6379/0")

    if pipeline.filter_and_save(url, html_content):
        # New unique content — proceed
        ...
    else:
        # Duplicate — skip
        ...
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

import redis

from core.structured_logger import SpiderLogger


class DedupPipelineError(Exception):
    """Raised when dedup is unavailable and fallback_permissive is False."""


class RedisDedupPipeline:
    """Two-layer deduplication pipeline backed by Redis.

    Layer 1: URL Bloom filter — catches exact URL duplicates.
    Layer 2: SimHash fuzzy dedup — catches near-identical content
             (Hamming distance <= 3 on 64-bit content fingerprints).

    Uses a 4-block index strategy: splitting each 64-bit simhash into
    four 16-bit blocks guarantees that hashes within Hamming distance 3
    share at least one identical block (pigeonhole principle).
    """

    # Bloom filter — ~119 MB bitmap
    BLOOM_M = 1_000_000_000
    BLOOM_K = 5

    # SimHash block index — 4 blocks of 16 bits each
    BLOCK_BITS = 16
    BLOCK_COUNT = 4
    BLOCK_MASK = 0xFFFF
    MIN_CONTENT_LENGTH = 50

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        key_prefix: str = "dedup",
        logger: Optional[SpiderLogger] = None,
        fallback_permissive: bool = True,
    ):
        """
        Args:
            redis_url: Redis connection URL.
            key_prefix: Namespace prefix for Redis keys (supports multi-domain).
            logger: SpiderLogger instance. Created automatically if not provided.
            fallback_permissive: If True, allow all content through when Redis
                                 is down. If False, raise DedupPipelineError.
        """
        self.redis_url = redis_url
        self.fallback_permissive = fallback_permissive
        self.log = logger or SpiderLogger(domain="dedup")

        # Redis key templates
        self._bloom_key = f"{key_prefix}:bloom:urls"
        self._simhash_block_prefix = f"{key_prefix}:simhash:b"
        self._simhash_all_key = f"{key_prefix}:simhash:all"

        self._redis: Optional[redis.Redis] = None
        self._connect()

    # ── Connection ──────────────────────────────────────

    def _connect(self) -> None:
        try:
            self._redis = redis.Redis.from_url(
                self.redis_url,
                socket_connect_timeout=3,
                socket_timeout=3,
                decode_responses=False,
            )
            self._redis.ping()
            self.log.info("redis_connected", url=self.redis_url)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            self._redis = None
            self.log.error("redis_unavailable", url=self.redis_url, error=str(e))

    @property
    def redis_available(self) -> bool:
        return self._redis is not None

    def _check_redis(self) -> bool:
        """Verify Redis is ready. Log and potentially raise if not."""
        if self.redis_available:
            return True
        if self.fallback_permissive:
            return False
        raise DedupPipelineError(f"Redis unavailable: {self.redis_url}")

    # ── Layer 1: URL Bloom Filter ───────────────────────

    def _bloom_offsets(self, url: str):
        """Generate k bit offsets via double hashing."""
        h1 = int(hashlib.md5(url.encode()).hexdigest(), 16)
        h2 = int(hashlib.sha1(url.encode()).hexdigest(), 16)
        for i in range(self.BLOOM_K):
            yield (h1 + i * h2) % self.BLOOM_M

    def _bloom_contains(self, url: str) -> bool:
        if not self._check_redis():
            return False
        try:
            pipe = self._redis.pipeline()
            for offset in self._bloom_offsets(url):
                pipe.getbit(self._bloom_key, offset)
            return all(pipe.execute())
        except (redis.ConnectionError, redis.TimeoutError) as e:
            self.log.error("bloom_check_failed", error=str(e))
            return False

    def _bloom_add(self, url: str) -> None:
        if not self.redis_available:
            return
        try:
            pipe = self._redis.pipeline()
            for offset in self._bloom_offsets(url):
                pipe.setbit(self._bloom_key, offset, 1)
            pipe.execute()
        except (redis.ConnectionError, redis.TimeoutError) as e:
            self.log.error("bloom_add_failed", error=str(e))

    # ── HTML text extraction ────────────────────────────

    @staticmethod
    def _extract_text(html: str) -> str:
        """Strip tags, scripts, styles; normalize whitespace."""
        text = re.sub(
            r"<script[^>]*>.*?</script>", " ", html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(
            r"<style[^>]*>.*?</style>", " ", text,
            flags=re.DOTALL | re.IGNORECASE,
        )
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-z]+;", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # ── Layer 2: SimHash Fuzzy Dedup ────────────────────

    @staticmethod
    def _compute_simhash(text: str) -> int:
        """Compute 64-bit SimHash fingerprint.

        ``simhash`` is imported lazily because it pulls in numpy, whose
        OpenBLAS backend can fail to allocate memory at import time. A
        module-level import meant that failure took down the whole fetch
        stage before a single feed was read (2026-09-21 incident).
        """
        from simhash import Simhash

        return Simhash(text).value

    def _block_keys(self, simhash: int):
        """Yield (block_index, block_value) for a 64-bit simhash."""
        for i in range(self.BLOCK_COUNT):
            shift = i * self.BLOCK_BITS
            yield i, (simhash >> shift) & self.BLOCK_MASK

    def _simhash_lookup(self, simhash: int) -> bool:
        """Check if any stored simhash is within Hamming distance 3."""
        if not self._check_redis():
            return False

        try:
            candidates: set[int] = set()
            for block_idx, block_val in self._block_keys(simhash):
                key = f"{self._simhash_block_prefix}:{block_idx}:{block_val}"
                members = self._redis.smembers(key)
                for m in members:
                    candidates.add(int(m))

            for candidate in candidates:
                if _hamming_distance(simhash, candidate) <= 3:
                    return True
            return False
        except (redis.ConnectionError, redis.TimeoutError) as e:
            self.log.error("simhash_lookup_failed", error=str(e))
            return False

    def _simhash_save(self, simhash: int) -> None:
        """Persist simhash to block index and global set."""
        if not self.redis_available:
            return

        try:
            simhash_str = str(simhash)
            pipe = self._redis.pipeline()
            for block_idx, block_val in self._block_keys(simhash):
                key = f"{self._simhash_block_prefix}:{block_idx}:{block_val}"
                pipe.sadd(key, simhash_str)
            # Also track in global set for exact-match fast path
            pipe.sadd(self._simhash_all_key, simhash_str)
            pipe.execute()
        except (redis.ConnectionError, redis.TimeoutError) as e:
            self.log.error("simhash_save_failed", error=str(e))

    # ── Public API ──────────────────────────────────────

    def filter_and_save(self, url: str, html_content: str) -> bool:
        """Run the two-layer dedup pipeline on raw HTML.

        Returns True if the content is new and unique, False if duplicate.
        When Redis is down and fallback_permissive=True, always returns True.
        """
        text = self._extract_text(html_content)
        return self.is_new(url, text)

    def is_new(self, url: str, content_text: str = "") -> bool:
        """Check url + text against both dedup layers. Marks as seen.

        This is the primary API for pipelines that already have cleaned text
        (e.g. from RSS feeds), avoiding redundant HTML parsing.

        Returns True if new/unique, False if duplicate.
        """
        # ── Layer 1: URL exact dedup ──
        if self._bloom_contains(url):
            self.log.debug("url_duplicate", url=url[:200])
            return False

        self._bloom_add(url)

        # Without Redis there is no cross-day store to compare against, so
        # every Layer-2 lookup is a no-op. Return before paying for the
        # simhash computation — same result, without importing numpy.
        if not self.redis_available:
            return True

        # ── Layer 2: Content fuzzy dedup ──
        if not content_text or len(content_text) < self.MIN_CONTENT_LENGTH:
            if not content_text:
                pass  # No content — skip simhash entirely
            else:
                self.log.debug("content_too_short_for_dedup", length=len(content_text))
            return True

        simhash = self._compute_simhash(content_text)

        # Fast path: exact simhash match (global set)
        if self.redis_available:
            try:
                if self._redis.sismember(self._simhash_all_key, str(simhash)):
                    self.log.debug("content_exact_duplicate", simhash=simhash)
                    return False
            except (redis.ConnectionError, redis.TimeoutError):
                pass

        # Slow path: Hamming-distance lookup
        if self._simhash_lookup(simhash):
            self.log.debug("content_similar", simhash=simhash, url=url[:200])
            return False

        self._simhash_save(simhash)
        return True

    def reset(self) -> dict:
        """Delete all dedup data for this key_prefix. Returns counts of keys removed.

        This provides the "deletable" guarantee — users can wipe dedup state
        without touching other Redis data.
        """
        if not self.redis_available:
            self.log.warning("reset_skipped", reason="redis_unavailable")
            return {"bloom_keys": 0, "simhash_block_keys": 0, "simhash_all_removed": 0}

        stats = {}
        try:
            # Delete bloom bitmap
            stats["bloom_keys"] = self._redis.delete(self._bloom_key)

            # Delete all simhash block sets
            pattern = f"{self._simhash_block_prefix}:*"
            cursor = 0
            block_keys_removed = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=pattern, count=1000)
                if keys:
                    block_keys_removed += self._redis.delete(*keys)
                if cursor == 0:
                    break
            stats["simhash_block_keys"] = block_keys_removed

            # Delete global simhash set
            stats["simhash_all_removed"] = self._redis.delete(self._simhash_all_key)

            self.log.info("dedup_reset", **stats)
        except (redis.ConnectionError, redis.TimeoutError) as e:
            self.log.error("reset_failed", error=str(e))
        return stats

    def stats(self) -> dict:
        """Return approximate counts for monitoring."""
        if not self.redis_available:
            return {"redis_available": False}

        try:
            bloom_bytes = self._redis.strlen(self._bloom_key) or 0
            simhash_count = self._redis.scard(self._simhash_all_key) or 0
            return {
                "redis_available": True,
                "bloom_bitmap_bytes": bloom_bytes,
                "simhash_total_fingerprints": simhash_count,
            }
        except (redis.ConnectionError, redis.TimeoutError) as e:
            self.log.error("stats_failed", error=str(e))
            return {"redis_available": False, "error": str(e)}

    def close(self) -> None:
        if self._redis:
            try:
                self._redis.close()
            except Exception:
                pass


def _hamming_distance(a: int, b: int) -> int:
    return (a ^ b).bit_count()


# ── Smoke tests ─────────────────────────────────────────

if __name__ == "__main__":
    import sys

    pipeline = RedisDedupPipeline()

    if not pipeline.redis_available:
        print("[SKIP] Redis not available — start Redis and re-run for full tests.")
        sys.exit(0)

    errors = []

    # ── Test 1: URL exact dedup ──
    r1 = pipeline.filter_and_save("http://example.com/dup-test", "<p>Hello World</p>")
    r2 = pipeline.filter_and_save("http://example.com/dup-test", "<p>Hello World</p>")
    if not (r1 is True and r2 is False):
        errors.append(f"Test 1 FAIL: URL dedup r1={r1} r2={r2}")
    else:
        print("PASS: Test 1 — URL exact dedup")

    # ── Test 2: Same content, different URLs → simhash catches it ──
    body = "人工智能正在改变世界 " * 80
    html_a = f"<html><body><article>{body}</article></body></html>"
    html_b = f"<div class='post'><p>{body}</p></div>"

    ra = pipeline.filter_and_save("http://a.example.com/article/1", html_a)
    rb = pipeline.filter_and_save("http://b.example.com/article/2", html_b)
    if not (ra is True and rb is False):
        errors.append(f"Test 2 FAIL: simhash dedup ra={ra} rb={rb}")
    else:
        print("PASS: Test 2 — SimHash fuzzy dedup (same body, different wrappers)")

    # ── Test 3: Different content → both pass ──
    html_c = "<p>" + "Python is a programming language. " * 50 + "</p>"
    html_d = "<p>" + "Redis is an in-memory data store. " * 50 + "</p>"

    rc = pipeline.filter_and_save("http://c.example.com/3", html_c)
    rd = pipeline.filter_and_save("http://d.example.com/4", html_d)
    if not (rc is True and rd is True):
        errors.append(f"Test 3 FAIL: different content should pass rc={rc} rd={rd}")
    else:
        print("PASS: Test 3 — Different content both pass")

    # ── Test 4: Near-duplicate with small edits → simhash catches it ──
    core = "Breaking news: major breakthrough in quantum computing achieved today. "
    html_e = f"<article>{core * 60}</article>"
    html_f = f"<article>{core * 58}Researchers announced the result at a press conference.</article>"

    re_ = pipeline.filter_and_save("http://e.example.com/5", html_e)
    rf = pipeline.filter_and_save("http://f.example.com/6", html_f)
    if not (re_ is True and rf is False):
        errors.append(f"Test 4 FAIL: near-duplicate should be caught re={re_} rf={rf}")
    else:
        print("PASS: Test 4 — Near-duplicate content caught by SimHash")

    pipeline.close()

    if errors:
        print(f"\n{len(errors)} test(s) FAILED:")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"\nAll 4 tests passed.")
