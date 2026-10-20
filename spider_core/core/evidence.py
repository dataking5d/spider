"""Fetch source pages into bounded, auditable evidence records.

**Why Python fetches and the model does not.** The child `claude` CLI's WebFetch
tool runs a domain safety check before every non-preapproved domain. Measured
2026-10-07 on CLI 2.1.291 against this machine's API relay
(`ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic`): only the CLI's
built-in preapproved domains (`example.com`, `httpbin.org`, `en.wikipedia.org`)
came back; `pubmed.ncbi.nlm.nih.gov`, `www.nature.com` and
`www.semanticscholar.org` all returned "Unable to verify if domain ... is safe
to fetch", with and without an HTTP proxy. The CLI binary carries the matching
`DomainCheckFailedError`. Python is an ordinary process with no such gate and
reached every one of those domains directly (HTTP 200).

Semantics deliberately mirror `generate_report.enrich_priority_evidence`:
bounded page size, HTML only, bot-check detection, and an honest status when the
page cannot be read. Keeping one implementation here is the point — the AI
domain's copy is inline and predates this module; folding it in is a separate,
deliberately deferred change.
"""

from urllib.parse import urljoin, urlparse

# A candidate is eligible for a report only at `excerpt`. `unavailable` is
# recorded so the prompt can say plainly which candidates yielded nothing —
# never silently drop them, or the model cannot explain the gap.
STATUS_EXCERPT = "excerpt"
STATUS_UNAVAILABLE = "unavailable"

_BOT_MARKERS = ("verify you are human", "checking your browser", "enable javascript")

# (connect, read). Raised from (4, 8) on 2026-10-07 after measuring the same 4s
# connect timeout fire against hosts that are demonstrably reachable: under the
# parallel load of both domains fetching at once, philadelphiafed.org (1.2s when
# idle) and the AI domain's microsoft.com/openai.com windows all exceeded 4s. A
# slow publisher is not an unreachable publisher, and reporting it as one turns
# a readable source into a phantom "unavailable". The budget is per host, and
# the whole stage is still bounded by the caller's candidate limit.
#
# Re-measured afterwards in isolation: the same two URLs return `excerpt` under
# *either* budget (2.6s and 0.4s — both inside the old 4s). So this is headroom
# against concurrent load, not a host that needs 10s. Do not read a passing
# isolated fetch as "the old value was fine" — the failure needs both domains
# running at once to reproduce.
DEFAULT_TIMEOUT = (10, 20)


def fetch_page_evidence(url, *, max_chars=10000, max_bytes=750_000, timeout=DEFAULT_TIMEOUT):
    """Read one page into `{url, status, text, final_url, error}`.

    Never raises: a failure is data. The caller reports the status honestly
    rather than inventing content for a page that would not load.
    """
    result = {
        "url": url,
        "status": STATUS_UNAVAILABLE,
        "text": "",
        "final_url": url,
        "error": "",
    }
    if urlparse(url).scheme not in ("http", "https"):
        result["error"] = "not an http(s) URL"
        return result

    import requests
    from bs4 import BeautifulSoup

    try:
        with requests.get(url, timeout=timeout, stream=True,
                          headers={"User-Agent": "Spider/0.12 source-evidence"}) as response:
            response.raise_for_status()
            if "html" not in response.headers.get("Content-Type", ""):
                result["error"] = "Source is not HTML"
                return result
            chunks, size = [], 0
            for chunk in response.iter_content(16384):
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    result["error"] = "Source page too large for bounded excerpt"
                    return result
            soup = BeautifulSoup(b"".join(chunks), "html.parser")
            for node in soup.select("script, style, nav, footer, header"):
                node.decompose()
            article = soup.select_one("article, .markdown-body, main")
            if article:
                # Keep in-body links as text so the model can follow a citation
                # out of the excerpt it was given.
                for anchor in article.select("a[href]"):
                    target = urljoin(response.url, anchor["href"])
                    if urlparse(target).scheme in ("http", "https"):
                        anchor.replace_with(f"{anchor.get_text(' ', strip=True)} ({target})")
            text = article.get_text(" ", strip=True) if article else ""
            if len(text) < 300 or any(marker in text[:800].lower() for marker in _BOT_MARKERS):
                result["error"] = "No readable article body"
                return result
            result.update(status=STATUS_EXCERPT, text=text[:max_chars],
                          final_url=response.url)
    except Exception as exc:
        # Broad on purpose: this runs unattended, and one unreachable source must
        # not take down the day. The type name is kept so the failure stays
        # diagnosable rather than becoming a silent empty string.
        result["error"] = f"{type(exc).__name__}: {exc}"[:180]
    return result


def normalize_url(url):
    """Compare URLs the way a reader would: ignore a trailing slash, and treat
    the scheme and host as case-insensitive. Query strings stay significant."""
    url = (url or "").strip()
    parsed = urlparse(url)
    if not parsed.scheme:
        return url.rstrip("/")
    return parsed._replace(scheme=parsed.scheme.lower(),
                           netloc=parsed.netloc.lower()).geturl().rstrip("/")
