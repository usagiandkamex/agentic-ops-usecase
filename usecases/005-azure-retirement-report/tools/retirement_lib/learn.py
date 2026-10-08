"""Step 5b (`learn-fallback`): Microsoft Learn search, done once by this tool when Learn MCP was unavailable.

Parallel workers never GET learn.microsoft.com (many concurrent GETs trigger HTTP 429 "Too Many Requests").
Workers that could not use Learn MCP record a `learnRequest` per event; this command serves those requests
serially, with a minimum interval, Retry-After handling, a per-run cap and a circuit breaker.
Only links are added (source=LearnSearch); remediation steps are never derived from search results.
"""
from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .common import (TOOL_VERSION, RunLock, ToolError, clean_text, id_key, load_state, log, normalize_link,
                     require_phase, save_state, write_json, write_text)

LEARN_HOST = "learn.microsoft.com"
LEARN_SEARCH_PATH = "/api/search"
LEARN_SEARCH_URL = f"https://{LEARN_HOST}{LEARN_SEARCH_PATH}"
LEARN_CAPABILITY_FALLBACK = "不可（直接取得で補完）"
MIN_INTERVAL_SEC = 2.0
MAX_SEARCHES = 30
MAX_429_RETRIES = 2
DEFAULT_RETRY_AFTER_SEC = 10
MAX_RETRY_AFTER_SEC = 60
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_LINKS_PER_EVENT = 2
TOP = 5
RETIRE_RE = re.compile(r"retire|deprecat|end of (support|life)|migrat|sunset", re.I)
REMAINING_STATUSES = ("pending", "stopped", "capped", "error")


class LearnHttpError(Exception):
    def __init__(self, status: int | None, retry_after: str | None, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


class _Stop(Exception):
    """Circuit breaker: no further Learn requests in this invocation."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def search_url(query: str) -> str:
    q = [("search", query), ("locale", "en-us"), ("$top", str(TOP))]
    return LEARN_SEARCH_URL + "?" + "&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in q)


def _check_learn_url(url: str) -> None:
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname != LEARN_HOST or p.port not in (None, 443) or p.path != LEARN_SEARCH_PATH:
        raise ToolError("refusing to request a URL outside the Microsoft Learn search API")


def _http_get_learn(url: str) -> Any:
    """One GET, no retries (the caller paces requests and decides on retries)."""
    _check_learn_url(url)
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "agentic-ops-usecase-005/" + TOOL_VERSION})
    try:
        with _OPENER.open(req, timeout=30) as r:
            if r.status != 200:
                raise LearnHttpError(r.status, None, f"HTTP {r.status}")
            if "json" not in (r.headers.get("Content-Type") or "").lower():
                raise LearnHttpError(None, None, "non-JSON response")
            data = r.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as e:
        raise LearnHttpError(e.code, e.headers.get("Retry-After") if e.headers else None, f"HTTP {e.code}")
    except (urllib.error.URLError, http.client.HTTPException, TimeoutError, ConnectionError) as e:
        raise LearnHttpError(None, None, f"{type(e).__name__}: {str(e)[:120]}")
    if len(data) > MAX_RESPONSE_BYTES:
        raise LearnHttpError(None, None, "response too large")
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError as e:
        raise LearnHttpError(None, None, f"unparsable response: {type(e).__name__}")


# Indirections so tests can replace network access and waiting.
http_get_learn: Callable[[str], Any] = _http_get_learn
sleep: Callable[[float], None] = time.sleep


def _retry_after_sec(v: str | None) -> float:
    try:
        sec = float(v) if v is not None else DEFAULT_RETRY_AFTER_SEC
    except ValueError:  # HTTP-date form: use the default wait
        sec = DEFAULT_RETRY_AFTER_SEC
    return min(max(sec, 1.0), MAX_RETRY_AFTER_SEC)


def _search(query: str) -> list[dict]:
    """Search with 429 handling. Raises _Stop when Learn keeps refusing or is unreachable."""
    url = search_url(query)
    for attempt in range(MAX_429_RETRIES + 1):
        try:
            data = http_get_learn(url)
        except LearnHttpError as e:
            if e.status == 429 and attempt < MAX_429_RETRIES:
                sleep(_retry_after_sec(e.retry_after))
                continue
            if e.status is not None and 400 <= e.status < 500 and e.status != 429:
                return []  # this query only (e.g. rejected search text)
            raise _Stop(f"Learn 検索 API: {e}")
        res = data.get("results") if isinstance(data, dict) else None
        return [r for r in res if isinstance(r, dict)] if isinstance(res, list) else []
    raise _Stop("Learn 検索 API: 429 が続いた")  # pragma: no cover - loop always returns or raises


def pick_links(results: list[dict], key_terms: list[str]) -> list[dict]:
    """Deterministic relevance: a Learn page whose title/description names a key term and a retirement word."""
    terms = [t.casefold() for t in key_terms if t]
    out: list[dict] = []
    for r in results:
        url = normalize_link(r.get("url"))
        if not url or urllib.parse.urlsplit(url).hostname != LEARN_HOST:
            continue
        title = clean_text(r.get("title"), 200)
        text = f"{title} {clean_text(r.get('description'), 600)}"
        if not title or not RETIRE_RE.search(text) or not any(t in text.casefold() for t in terms):
            continue
        if url not in {o["url"] for o in out}:
            out.append({"titleJa": title, "url": url})
        if len(out) >= MAX_LINKS_PER_EVENT:
            break
    return out


def collect_requests(accepted: dict, ok_ids: list[str]) -> list[dict]:
    items = []
    for nid in sorted(ok_ids, key=id_key):
        for e in accepted[nid]["events"]:
            r = e.get("learnRequest")
            if r:
                items.append({"noticeId": nid, "eventKey": e["eventKey"], "query": r["query"], "keyTerms": r["keyTerms"],
                              "status": "pending", "links": 0})
    return items


def cmd_learn_fallback(args: Any, run: Path) -> dict:
    from .plan import load_accepted
    from .progress import render_progress
    with RunLock(run):
        st = load_state(run)
        require_phase(st, ("collected",), "learn-fallback")
        lf = st.get("learnFallback") or {"status": "notNeeded", "items": []}
        if lf["status"] == "notNeeded":
            return {"run": st["runId"], "learnFallback": {"status": "notNeeded"}, "next": f"merge --run {st['runId']}"}
        accepted = load_accepted(run)
        cache: dict[str, list[dict]] = {}
        searches = 0
        stopped: str | None = None
        for it in [x for x in lf["items"] if x["status"] in REMAINING_STATUSES]:
            rec = accepted.get(it["noticeId"])
            ev = next((e for e in rec["events"] if e["eventKey"] == it["eventKey"]), None) if rec else None
            if ev is None:
                it["status"] = "gone"
                continue
            if stopped:
                it["status"] = "stopped"
                continue
            q = it["query"]
            if q not in cache:
                if searches >= MAX_SEARCHES:
                    it["status"] = "capped"
                    continue
                if searches:
                    sleep(MIN_INTERVAL_SEC)
                searches += 1
                try:
                    cache[q] = _search(q)
                    lf["responses"] = lf.get("responses", 0) + 1
                except _Stop as ex:
                    stopped = str(ex)[:200]
                    it["status"] = "stopped"
                    continue
            have = {l["url"] for l in ev["referenceLinks"]}
            new = [{"titleJa": l["titleJa"], "url": l["url"], "source": "LearnSearch", "learnQuery": q}
                   for l in pick_links(cache[q], it["keyTerms"]) if l["url"] not in have]
            ev["referenceLinks"] = ev["referenceLinks"] + new
            it["links"] = len(new)
            it["status"] = "linked" if new else "noMatch"
        lf.update({"status": "done", "searches": lf.get("searches", 0) + searches, "stoppedReason": stopped})
        st["learnFallback"] = lf
        if lf.get("responses") and st["capabilities"].get("learnMcp") in ("不可", "未使用"):
            st["capabilities"]["learnMcp"] = LEARN_CAPABILITY_FALLBACK
        counts = {s: sum(1 for x in lf["items"] if x["status"] == s) for s in ("linked", "noMatch", "stopped", "capped", "gone")}
        log(st, "learn-fallback", f"Learn 検索 API（逐次）{searches} 回: リンク追加 {counts['linked']} 件・該当なし {counts['noMatch']} 件"
            + (f"・中止 {counts['stopped']} 件（{stopped}）" if counts["stopped"] else "")
            + (f"・上限超過 {counts['capped']} 件" if counts["capped"] else ""))
        write_json(run, ".work/accepted.json", accepted)
        save_state(run, st)
        write_text(run, "progress.md", render_progress(st))
    return {"run": st["runId"], "learnFallback": {"searches": searches, **counts, "stoppedReason": stopped},
            "capabilities": {"learnMcp": st["capabilities"]["learnMcp"]},
            "next": f"merge --run {st['runId']}（中止・上限超過の件があっても続行できる。時間を置いて learn-fallback を再実行すれば残りを再試行する）"}
