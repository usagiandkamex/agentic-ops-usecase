"""Steps 2-4.5: scope, public API access (GET only, exact origin), probe / init / enumerate."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .common import (MAX_ATTEMPTS, REPO_REL_REPORTS, SCHEMA_VERSION, TOOL_VERSION, NOTICE_ID_RE, RunLock,
                     ToolError, add_months, clean_list, clean_text, id_key, jst_stamp, load_state, log,
                     month_bounds, month_number, now_jst, ordinal_ignore_case_key, reports_root, require_phase,
                     save_state, snapshot_id, write_json, write_text)

API_BASE = "https://www.microsoft.com/releasecommunications/api/v2/azure"
API_HOST = "www.microsoft.com"
API_PATH = "/releasecommunications/api/v2/azure"
PAGE_SIZE = 100
MAX_PAGES = 100
MAX_RESPONSE_BYTES = 30 * 1024 * 1024
RET_FILTER = "tags/any(t:t eq 'Retirements')"
META_SELECT = "id,title,products,productCategories,availabilities,created,modified"
YEAR_RE = re.compile(r"(?<!\d)20\d{2}(?!\d)")
SCOPE_TYPES = ("default", "futureOnly", "next12Months", "all", "custom")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _check_api_url(url: str) -> None:
    p = urllib.parse.urlsplit(url)
    if p.scheme != "https" or p.hostname != API_HOST or p.port not in (None, 443) or not p.path.startswith(API_PATH):
        raise ToolError("refusing to request a URL outside the Release Communications API")


def _http_get_json(url: str) -> Any:
    _check_api_url(url)
    last: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "agentic-ops-usecase-005/" + TOOL_VERSION})
            with _OPENER.open(req, timeout=60) as r:
                if r.status != 200:
                    raise ToolError(f"API returned HTTP {r.status}")
                if "json" not in (r.headers.get("Content-Type") or "").lower():
                    raise ToolError("API returned a non-JSON response")
                data = r.read(MAX_RESPONSE_BYTES + 1)
                if len(data) > MAX_RESPONSE_BYTES:
                    raise ToolError("API response too large")
                return json.loads(data.decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 and e.code != 429:
                break
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = e
        time.sleep(2 * (attempt + 1))
    raise ToolError(f"Release Communications API GET failed: {type(last).__name__}: {str(last)[:200]}", code=3)


# Indirection so tests can replace network access.
http_get_json: Callable[[str], Any] = _http_get_json


def _url(filter_: str, **params: Any) -> str:
    q = [("$filter", filter_)] + [(f"${k}", str(v)) for k, v in params.items()]
    return API_BASE + "?" + "&".join(f"{k}={urllib.parse.quote(v, safe='')}" for k, v in q)


def api_count(filter_: str) -> int:
    d = http_get_json(_url(filter_, count="true", top=1, select="id"))
    c = d.get("@odata.count") if isinstance(d, dict) else None
    if not isinstance(c, int) or c < 0:
        raise ToolError("unexpected API response: @odata.count missing", code=3)
    return c


def api_list(filter_: str, select: str) -> tuple[list[dict], int, int, list[str]]:
    """Returns (raw items, pages, enumerated count, duplicate ids) paging by $skip with a stable $orderby."""
    items: list[dict] = []
    seen: set[str] = set()
    dups: list[str] = []
    pages = 0
    for page in range(MAX_PAGES):
        d = http_get_json(_url(filter_, select=select, orderby="id", top=PAGE_SIZE, skip=page * PAGE_SIZE))
        vals = d.get("value") if isinstance(d, dict) else None
        if not isinstance(vals, list):
            raise ToolError("unexpected API response: value[] missing", code=3)
        pages += 1
        for v in vals:
            if not isinstance(v, dict) or not isinstance(v.get("id"), str) or not NOTICE_ID_RE.match(v["id"]):
                raise ToolError("unexpected API response: invalid id", code=3)
            if v["id"] in seen:
                dups.append(v["id"])
            seen.add(v["id"])
            items.append(v)
        if len(vals) < PAGE_SIZE:
            break
    else:
        raise ToolError("too many pages; narrow the scope", code=3)
    return items, pages, len(items), sorted(set(dups), key=id_key)


def inscope_filter(y: int) -> str:
    return f"{RET_FILTER} and (availabilities/any(a:a/year ge {y}) or not availabilities/any())"


def complement_filter(y: int) -> str:
    return f"{RET_FILTER} and availabilities/any() and not availabilities/any(a:a/year ge {y})"


# ---------------------------------------------------------------- scope

def compute_scope(type_: str, as_of: dt.date, start: str | None = None, end: str | None = None) -> dict:
    ws: dt.date | None
    we: dt.date | None = None
    if type_ == "default":
        ws = add_months(as_of.replace(day=1), -3)
        label = f"今後予定のすべて＋直近 3 か月にリタイア済み（{ws.isoformat()} 以降）"
    elif type_ == "futureOnly":
        ws = as_of
        label = f"今後予定のみ（基準日 {as_of.isoformat()} 以降）"
    elif type_ == "next12Months":
        ws = as_of
        we = add_months(as_of, 12) - dt.timedelta(days=1)
        label = f"今後 12 か月以内（{ws.isoformat()}〜{we.isoformat()}）"
    elif type_ == "all":
        ws = None
        label = "全件（過去分を含む）"
    elif type_ == "custom":
        def ym(v: str | None, name: str) -> tuple[int, int]:
            m = re.match(r"^(\d{4})-(\d{2})$", v or "")
            if not m or not 1 <= int(m.group(2)) <= 12:
                raise ToolError(f"--{name} must be YYYY-MM for scope custom")
            return int(m.group(1)), int(m.group(2))
        ws = month_bounds(*ym(start, "start"))[0]
        we = month_bounds(*ym(end, "end"))[1]
        if we < ws:
            raise ToolError("--end must not be before --start")
        label = f"カスタム（{ws.isoformat()}〜{we.isoformat()}）"
    else:
        raise ToolError(f"unknown scope type: {type_}")
    y = add_months(ws, -6).year if ws else None
    return {"type": type_, "label": label, "windowStart": ws.isoformat() if ws else None,
            "windowEnd": we.isoformat() if we else None, "prefilterStartYear": y}


def as_of_date(v: str | None) -> dt.date:
    if v:
        try:
            return dt.date.fromisoformat(v)
        except ValueError:
            raise ToolError("--as-of must be YYYY-MM-DD")
    return now_jst().date()


def cmd_probe(args: Any) -> dict:
    as_of = as_of_date(args.as_of)
    scope = compute_scope(args.scope, as_of, args.start, args.end)
    out: dict = {"asOfDate": as_of.isoformat(), "scope": scope}
    try:
        total = api_count(RET_FILTER)
        y = scope["prefilterStartYear"]
        in_scope = total if y is None else api_count(inscope_filter(y))
        comp = 0 if y is None else api_count(complement_filter(y))
        out.update({"releaseCommunicationsApi": "利用可", "retirementsTotal": total,
                    "inScopeCount": in_scope, "complementCount": comp, "consistent": in_scope + comp == total})
        if in_scope > 300:
            out["advice"] = "範囲の候補が 300 件を超えます。処理時間が長くなるため、範囲を狭める選択肢（今後 12 か月 等）も併せて提示してください。"
    except ToolError as e:
        out.update({"releaseCommunicationsApi": "不可", "error": str(e),
                    "advice": "公開 API に接続できません。列挙は公開 API が必須のため、ネットワーク設定を確認してください。"})
    out["next"] = "利用者に収集範囲・規模を示して最終承認を取り、承認後に `init` を実行する"
    return out


# ---------------------------------------------------------------- init

def cmd_init(args: Any) -> dict:
    from .progress import render_progress
    as_of = as_of_date(args.as_of)
    scope = compute_scope(args.scope, as_of, args.start, args.end)
    api_count(RET_FILTER)  # the public API is mandatory for enumeration
    now = now_jst()
    root = reports_root()
    root.mkdir(parents=True, exist_ok=True)
    base = now.strftime("%Y%m%d-%H%M%S")
    name, n = base, 1
    while (root / name).exists():
        n += 1
        name = f"{base}-{n}"
    run = root / name
    run.mkdir()
    st = {
        "schemaVersion": SCHEMA_VERSION, "toolVersion": TOOL_VERSION, "runId": name,
        "createdAt": jst_stamp(now), "asOfDate": as_of.isoformat(), "scope": scope,
        "capabilities": {"mrcMcp": "利用可" if args.mrc_mcp == "available" else "不可",
                         "releaseCommunicationsApi": "利用可", "learnMcp": "未判定"},
        "phase": "initialized", "gates": {}, "log": [],
    }
    log(st, "init", f"保存先 {REPO_REL_REPORTS}/{name}/ を作成（収集範囲: {scope['label']}）")
    with RunLock(run):
        save_state(run, st)
        write_text(run, "progress.md", render_progress(st))
    return {"run": name, "reportFolder": str(run), "scope": scope, "asOfDate": as_of.isoformat(),
            "next": f"enumerate --run {name}"}


# ---------------------------------------------------------------- enumerate

def availability_month(avails: Any) -> str | None:
    if not isinstance(avails, list):
        return None
    rows = [a for a in avails if isinstance(a, dict)]
    ret = [a for a in rows if str(a.get("ring", "")).lower() == "retirement"]
    best: tuple[int, int] | None = None
    for a in ret or rows:
        y, m = a.get("year"), month_number(a.get("month"))
        if isinstance(y, int) and not isinstance(y, bool) and m and (best is None or (y, m) > best):
            best = (y, m)
    return f"{best[0]:04d}-{best[1]:02d}" if best else None


def notice_meta(v: dict) -> dict:
    return {
        "id": v["id"],
        "title": clean_text(v.get("title"), 400),
        "products": clean_list(v.get("products"), 150, 20),
        "productCategories": clean_list(v.get("productCategories"), 100, 10),
        "availabilityMonth": availability_month(v.get("availabilities")),
        "created": clean_text(v.get("created"), 40),
        "modified": clean_text(v.get("modified"), 40),
    }


def _has_year_ge(text: str, y: int) -> bool:
    return any(int(m.group(0)) >= y for m in YEAR_RE.finditer(text))


def cmd_enumerate(args: Any, run) -> dict:
    from .plan import write_same_target_request
    from .progress import render_progress
    with RunLock(run):
        st = load_state(run)
        require_phase(st, ("initialized", "enumerated"), "enumerate")
        y = st["scope"]["prefilterStartYear"]
        in_filter = RET_FILTER if y is None else inscope_filter(y)
        attempts = 0
        while True:
            attempts += 1
            first = api_count(RET_FILTER)
            in_count = first if y is None else api_count(in_filter)
            comp_count = 0 if y is None else api_count(complement_filter(y))
            raw, pages, enum_count, dups = api_list(in_filter, META_SELECT)
            last = api_count(RET_FILTER)
            uniq = {v["id"]: v for v in raw}
            ok = len(uniq) == in_count and first == last and in_count + comp_count == first
            if ok or attempts >= 2:
                break
        if not ok:
            log(st, "enumerate", f"列挙の件数が一致しないため再列挙したが不一致が残った（consistent=false）: 一意 {len(uniq)} / inScope {in_count} / 全件 {first}→{last} / 補集合 {comp_count}")
        prefilter: dict
        extra: dict[str, dict] = {}
        if y is None:
            prefilter = {"screenStatus": "notNeeded", "screenedCount": 0, "bodyYearMatchedNoticeIds": [], "excludedCount": 0}
        else:
            status = "fallbackAll"
            comp_uniq: dict[str, dict] = {}
            comp_union: dict[str, dict] = {}
            for _ in range(2):
                comp_raw, _, screened, _ = api_list(complement_filter(y), META_SELECT + ",description")
                comp_uniq = {v["id"]: v for v in comp_raw}
                comp_union.update(comp_uniq)
                if screened == comp_count and len(comp_uniq) == screened:
                    status = "done"
                    break
            if status == "done":
                keep = [v for v in comp_uniq.values()
                        if _has_year_ge(f"{v.get('title') or ''} {v.get('description') or ''}", y)]
                extra = {v["id"]: v for v in keep}
                matched = sorted(extra, key=id_key)
                prefilter = {"screenStatus": "done", "screenedCount": comp_count,
                             "bodyYearMatchedNoticeIds": matched, "excludedCount": comp_count - len(matched)}
            else:
                # Keep every complement row seen in any attempt; completeness is judged on the union.
                extra = comp_union
                prefilter = {"screenStatus": "fallbackAll", "screenedCount": len(comp_union),
                             "bodyYearMatchedNoticeIds": [], "excludedCount": 0}
                log(st, "enumerate", f"補集合の本文年スクリーニングで件数が一致しないため、補集合の全件（{len(comp_union)} 件）を候補にした（fallbackAll）")
                if len(comp_union) != comp_count:
                    ok = False
                    log(st, "enumerate", f"補集合の取得結果（一意 {len(comp_union)} 件）が complementCount {comp_count} と一致しないため、列挙の整合が取れていないとして記録した（consistent=false）")
        notices = [notice_meta(v) for v in list(uniq.values()) + [v for k, v in extra.items() if k not in uniq]]
        notices.sort(key=lambda n: id_key(n["id"]))
        cats = sorted({c for n in notices for c in n["productCategories"] if c != "Uncategorized"}, key=ordinal_ignore_case_key)
        snap = snapshot_id(notices)
        st["enumeration"] = {
            "retirementsTotal": {"firstObserved": first, "lastObserved": last, "query": RET_FILTER},
            "enumeration": {"inScopeQuery": in_filter, "inScopeCount": in_count,
                            "complementQuery": complement_filter(y) if y is not None else None,
                            "complementCount": comp_count, "consistent": ok, "enumeratedAt": jst_stamp(),
                            "pages": pages, "enumeratedIdCount": enum_count, "uniqueNoticeIdCount": len(uniq),
                            "duplicatePageIds": dups, "attempts": attempts},
            "inScopeNoticeIds": sorted(uniq, key=id_key),
            "prefilter": prefilter,
            "candidateNoticeIds": [n["id"] for n in notices],
            "allowedCategories": cats + ["Uncategorized"],
        }
        st["snapshotId"] = snap
        st["sameTarget"] = None
        st["phase"] = "enumerated"
        write_json(run, ".work/candidates.json", {"schemaVersion": SCHEMA_VERSION, "snapshotId": snap, "notices": notices})
        req = write_same_target_request(run, st, notices)
        log(st, "enumerate", f"候補 {len(notices)} 件を確定（年フィルタ内 {len(uniq)} 件＋本文の年で補完 {len(prefilter['bodyYearMatchedNoticeIds'])} 件・事前除外 {prefilter['excludedCount']} 件・整合 {'はい' if ok else 'いいえ'}）")
        save_state(run, st)
        write_text(run, "progress.md", render_progress(st))
    return {"run": st["runId"], "retirementsTotal": first, "inScopeCount": in_count, "complementCount": comp_count,
            "consistent": ok, "candidateCount": len(notices), "prefilter": {k: (len(v) if isinstance(v, list) else v) for k, v in prefilter.items()},
            "snapshotId": snap, "sameTargetRequest": str(req),
            "next": ("同一対象の重複候補を判定する: sameTargetRequest のファイルを読み、同じ製品で同じ対象（SKU / シリーズ / 機能 / API・ランタイム版）を指す投稿の組を "
                     f"`record-same-target --run {st['runId']} --pairs \"<id>,<id>;...\"`（無ければ `--none`）で記録し、続けて `plan-batches` を実行する")}
