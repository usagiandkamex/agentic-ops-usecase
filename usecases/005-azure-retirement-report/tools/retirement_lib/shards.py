"""Step 5 (G2): strict shard validation + sanitizing, per-notice attempts, retry batches."""
from __future__ import annotations

import hashlib
import re
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any

from .common import (MAX_ATTEMPTS, MAX_BATCH, RunLock, ToolError, clean_list, clean_text, id_key, load_state, log,
                     month_bounds, normalize_link, parse_date, read_json, require_phase, save_state, write_json,
                     write_text)
from .api import availability_month
from .plan import _new_batch, _recency, load_accepted, load_candidates

PRECISIONS = {"day", "month", "unknown"}
DATE_SOURCES = {"description", "availability", "none"}
IMPACT_TYPES = {"ServiceRetirement", "SkuRetirement", "VersionRetirement", "FeatureRetirement", "Unknown"}
CLASS_STATUSES = {"confirmed", "ambiguous", "insufficientEvidence"}
REMEDIATION_STATUSES = {"explicit", "supplementedByLearn", "notFound"}
FLAG_NAMES = ("workloadStop", "dataLossRisk", "autoMigration")
LEARN_VALUES = {"available", "fallbackGet", "unavailable", "notUsed"}
# Manifest values whose Learn-derived links are kept (Learn MCP, or direct GET only when MCP is unavailable).
LEARN_KEEP = {"available", "fallbackGet"}
# Values meaning some events needing a Learn supplement could not get a full one (GET fallback is capped / links only).
LEARN_PARTIAL = {"fallbackGet", "unavailable"}
LEARN_CAPABILITY_FALLBACK = "不可（直接取得で補完）"
LEARN_HOST = "learn.microsoft.com"
FETCHED_VIA = ("MRC MCP", "ReleaseCommunicationsApi")


class ShardError(Exception):
    pass


# ---------------------------------------------------------------- API-mode provenance (MRC MCP unavailable)

MIN_EVIDENCE_CHARS = 8
_BODY_URL_RE = re.compile(r"\[(https://[^\s\]]+)\]")


def _norm_evidence(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").casefold()
    return re.sub(r"[^0-9a-z]+", "", s)


def _in_body(evidence: str, body_norm: str) -> bool:
    ev = _norm_evidence((evidence or "").rstrip("…"))
    return len(ev) >= MIN_EVIDENCE_CHARS and ev in body_norm


def input_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prefetched_bodies(run: Path, b: dict) -> dict:
    """Bodies the tool fetched for this dispatch, read from the input file after checking it was not modified."""
    p = run / b["inputPath"]
    want = b.get("inputSha256")
    if not isinstance(want, str) or not p.exists() or input_digest(p) != want:
        raise ShardError("input file missing or modified after dispatch")
    inp = read_json(p)
    out = {}
    for n in inp.get("notices", []):
        body = n.get("body") if isinstance(n, dict) else None
        if isinstance(body, dict) and isinstance(body.get("bodyText"), str):
            out[n["id"]] = {"text": f"{body.get('title') or ''}\n{body['bodyText']}",
                            "availabilityMonth": availability_month(body.get("availabilities"))}
    return out


def learn_capability(learns: list[str]) -> str:
    """Run-level Learn capability from the accepted batches' manifest values (MCP use takes precedence)."""
    if "available" in learns:
        return "利用可"
    if "fallbackGet" in learns:
        return LEARN_CAPABILITY_FALLBACK
    return "不可" if "unavailable" in learns else "未使用"


def _drop_learn_remediation(rec: dict, learn: str, warnings: list[str]) -> None:
    """Learn-derived remediation steps need a Learn page read through Learn MCP (the GET fallback only adds links)."""
    for e in rec["events"]:
        if e["remediationStatus"] == "supplementedByLearn":
            warnings.append(f"{e['eventKey']}: learnMcp={learn} のため remediationStatus を notFound にした")
            e["remediationStatus"], e["remediationJa"] = "notFound", []


def _drop_learn_outputs(rec: dict, learn: str, warnings: list[str]) -> None:
    """A shard that did not use Learn (MCP or the GET fallback) must not carry Learn-derived links or remediation."""
    for e in rec["events"]:
        k = e["eventKey"]
        kept = [l for l in e["referenceLinks"] if l["source"] != "LearnSearch"]
        if len(kept) != len(e["referenceLinks"]):
            warnings.append(f"{k}: learnMcp={learn} のため Learn 補完のリンクを除外した")
            e["referenceLinks"] = kept
    _drop_learn_remediation(rec, learn, warnings)


def enforce_body_provenance(rec: dict, body: dict, warnings: list[str]) -> None:
    """The offline worker may only report facts found in the tool-fetched body; anything else is weakened."""
    text = body.get("text") or ""
    body_norm = _norm_evidence(text)
    body_urls = set(_BODY_URL_RE.findall(text))
    avail_month = body.get("availabilityMonth")
    for e in rec["events"]:
        k = e["eventKey"]
        rd = e["retireDate"]
        if rd["precision"] != "unknown" and rd["source"] == "description" and not _in_body(rd["evidence"], body_norm):
            warnings.append(f"{k}: retireDate の根拠が取得済み本文に見つからないため unknown にした")
            e["retireDate"] = {"precision": "unknown", "start": None, "end": None, "source": "none", "evidence": ""}
        elif rd["precision"] != "unknown" and rd["source"] == "availability" and (
                rd["precision"] != "month" or not avail_month or rd["start"][:7] != avail_month):
            # An availability-sourced date is the month of the tool-fetched availabilities, never anything else.
            warnings.append(f"{k}: retireDate（source=availability）が取得済みの availabilities の月と一致しないため unknown にした")
            e["retireDate"] = {"precision": "unknown", "start": None, "end": None, "source": "none", "evidence": ""}
        for f in FLAG_NAMES:
            if e["flags"][f] != "unknown" and not _in_body(e["flagEvidence"][f], body_norm):
                warnings.append(f"{k}: flags.{f} の根拠が取得済み本文に見つからないため unknown にした")
                e["flags"][f] = "unknown"
                e["flagEvidence"][f] = ""
        s = e["sameEventAs"]
        if s and not _in_body(s["evidence"], body_norm):
            warnings.append(f"{k}: sameEventAs の根拠が取得済み本文に見つからないため統合候補から外した")
            e["sameEventAs"] = None
        kept = [l for l in e["referenceLinks"] if l["source"] == "Description" and l["url"] in body_urls]
        if len(kept) != len(e["referenceLinks"]):
            warnings.append(f"{k}: 取得済み本文に無いリンク（Learn 補完を含む）を除外した")
            e["referenceLinks"] = kept
        if e["remediationStatus"] == "supplementedByLearn":
            warnings.append(f"{k}: オフラインワーカーは Learn 補完できないため remediationStatus を notFound にした")
            e["remediationStatus"], e["remediationJa"] = "notFound", []


def _tri(v: Any, name: str) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str) and v.strip().lower() in ("true", "false", "unknown"):
        return v.strip().lower()
    raise ShardError(f"flags.{name} must be \"true\"/\"false\"/\"unknown\"")


def _enum(v: Any, allowed: set, name: str) -> str:
    if v not in allowed:
        raise ShardError(f"{name} has an invalid value")
    return v


def _retire_date(rd: Any, warnings: list[str], key: str) -> dict:
    if not isinstance(rd, dict):
        raise ShardError("retireDate missing")
    prec = _enum(rd.get("precision"), PRECISIONS, "retireDate.precision")
    src = rd.get("source") if rd.get("source") in DATE_SOURCES else "none"
    start, end = rd.get("start"), rd.get("end")
    evidence = clean_text(rd.get("evidence"), 300)
    # A known date drives scope, remaining days and urgency, so it must carry provenance from the notice.
    if prec != "unknown" and (src == "none" or not evidence):
        warnings.append(f"{key}: retireDate の出典（source）または根拠（evidence）が無いため unknown にした")
        prec, src = "unknown", "none"
    if prec == "unknown":
        s = e = None
    else:
        if isinstance(start, str) and re.match(r"^\d{4}-\d{2}$", start.strip()):
            start = start.strip() + "-01"
        d = parse_date(start)
        if d is None:
            raise ShardError("retireDate.start must be YYYY-MM-DD")
        if prec == "month":
            a, b = month_bounds(d.year, d.month)
            s, e = a.isoformat(), b.isoformat()
        else:
            s = e = d.isoformat()
            if end not in (None, s):
                warnings.append(f"{key}: day 精度の end を start に揃えた")
    return {"precision": prec, "start": s, "end": e, "source": src, "evidence": evidence}


def _milestones(v: Any) -> list[dict]:
    out = []
    for m in v if isinstance(v, list) else []:
        if not isinstance(m, dict):
            continue
        prec = m.get("precision") if m.get("precision") in ("day", "month") else "day"
        raw = m.get("date")
        if isinstance(raw, str) and re.match(r"^\d{4}-\d{2}$", raw.strip()):
            raw, prec = raw.strip() + "-01", "month"
        d = parse_date(raw)
        if d is None:
            continue
        if prec == "month":
            d = d.replace(day=1)
        item = {"date": d.isoformat(), "precision": prec, "labelJa": clean_text(m.get("labelJa"), 80),
                "evidence": clean_text(m.get("evidence"), 300)}
        if item not in out:
            out.append(item)
    return out[:10]


def _links(v: Any) -> list[dict]:
    out, seen = [], set()
    for l in v if isinstance(v, list) else []:
        if not isinstance(l, dict):
            continue
        url = normalize_link(l.get("url"))
        if not url or url in seen:
            continue
        source = l.get("source") if l.get("source") in ("Description", "LearnSearch") else "Description"
        if source == "LearnSearch" and urllib.parse.urlsplit(url).hostname != LEARN_HOST:
            # A Learn supplement must point to Microsoft Learn itself, whichever way it was found (MCP or GET fallback).
            continue
        seen.add(url)
        out.append({"titleJa": clean_text(l.get("titleJa"), 200) or url, "url": url, "source": source,
                    "learnQuery": clean_text(l.get("learnQuery"), 200)})
    return out[:7]


def validate_event(e: Any, key: str, warnings: list[str]) -> dict:
    if not isinstance(e, dict):
        raise ShardError("event must be an object")
    flags = e.get("flags")
    if not isinstance(flags, dict):
        raise ShardError("flags missing")
    fe = e.get("flagEvidence") if isinstance(e.get("flagEvidence"), dict) else {}
    summary = clean_text(e.get("summaryJa"), 400)
    if not summary:
        raise ShardError("summaryJa missing")
    rem = clean_list(e.get("remediationJa"), 300, 5)
    rstat = _enum(e.get("remediationStatus"), REMEDIATION_STATUSES, "remediationStatus")
    if not rem and rstat != "notFound":
        warnings.append(f"{key}: 対応策が空のため remediationStatus を notFound にした")
        rstat = "notFound"
    dc = e.get("dateConflict")
    if isinstance(dc, str) and dc.strip().lower() in ("true", "false"):
        dc = dc.strip().lower() == "true"
    if not isinstance(dc, bool):
        # Feeds the report's conflict count; a missing / invalid value must not silently become false.
        raise ShardError("dateConflict must be true/false")
    same = e.get("sameEventAs")
    if isinstance(same, dict) and isinstance(same.get("noticeId"), str) and isinstance(same.get("eventKey"), str):
        same = {"noticeId": same["noticeId"].strip(), "eventKey": same["eventKey"].strip(),
                "evidence": clean_text(same.get("evidence"), 300)}
    else:
        same = None
    tri = {f: _tri(flags.get(f), f) for f in FLAG_NAMES}
    fev = {f: clean_text(fe.get(f), 300) for f in FLAG_NAMES}
    for f in FLAG_NAMES:
        # A determined flag drives severity, so it must carry evidence from the notice.
        if tri[f] != "unknown" and not fev[f]:
            warnings.append(f"{key}: flags.{f} の根拠（flagEvidence）が空のため unknown にした")
            tri[f] = "unknown"
    return {
        "eventKey": key,
        "affectedScopeJa": clean_text(e.get("affectedScopeJa"), 300),
        "retireDate": _retire_date(e.get("retireDate"), warnings, key),
        "dateConflict": dc,
        "dateNoteJa": clean_text(e.get("dateNoteJa"), 300),
        "milestones": _milestones(e.get("milestones")),
        "impactType": _enum(e.get("impactType"), IMPACT_TYPES, "impactType"),
        "flags": tri,
        "flagEvidence": fev,
        "classificationStatus": _enum(e.get("classificationStatus"), CLASS_STATUSES, "classificationStatus"),
        "summaryJa": summary,
        "remediationJa": rem,
        "remediationStatus": rstat,
        "migrationTarget": clean_text(e.get("migrationTarget"), 200),
        "referenceLinks": _links(e.get("referenceLinks")),
        "sameEventAs": same,
    }


def validate_notice(n: Any, meta: dict, allowed: list[str], warnings: list[str], required_via: str | None = None) -> dict:
    nid = meta["id"]
    if n.get("fetchStatus", "ok") != "ok":
        raise ShardError("fetchStatus must be ok for returned notices")
    via = n.get("fetchedVia")
    if via not in FETCHED_VIA:
        raise ShardError("fetchedVia must be \"MRC MCP\" or \"ReleaseCommunicationsApi\"")
    if required_via and via != required_via:
        raise ShardError(f"fetchedVia must be \"{required_via}\" (bodies were prefetched by the tool)")
    events = n.get("events")
    if not isinstance(events, list) or not events:
        raise ShardError("events[] must have at least one event")
    keys = [str(e.get("eventKey") or "").strip() if isinstance(e, dict) else "" for e in events]
    if len(events) == 1:
        if keys[0] not in ("", nid):
            warnings.append(f"{nid}: 単一イベントの eventKey を投稿 ID に揃えた")
        keys = [nid]
    elif len(set(keys)) != len(keys) or not all(re.match(rf"^{re.escape(nid)}-\d+$", k) for k in keys):
        raise ShardError("split events must use unique eventKey <id>-<n>")
    title_ja = clean_text(n.get("titleJa"), 300)
    if not title_ja:
        warnings.append(f"{nid}: titleJa が空のため原文タイトルを使用")
        title_ja = meta["title"]
    cats = clean_list(n.get("inferredCategories"), 100, 2)
    bad = [c for c in cats if c not in allowed]
    if bad:
        warnings.append(f"{nid}: 許容集合に無い推定カテゴリを除外")
    return {"id": nid, "fetchedVia": via, "titleJa": title_ja,
            "inferredProducts": clean_list(n.get("inferredProducts"), 150, 5),
            "inferredCategories": [c for c in cats if c in allowed],
            "events": [validate_event(e, k, warnings) for e, k in zip(events, keys)]}


def _learn_incomplete(sh: dict, learn: str, api_mode: bool, warnings: list[str]) -> bool:
    """Whether some event that needed a Learn supplement was not served by Learn MCP (GET fallback or nothing).

    learnMcp is one value per batch (MCP use takes precedence), so a batch that used Learn MCP for one event and
    fell back for another reports "available"; the manifest flag learnIncomplete carries that mix.
    """
    if api_mode or learn == "notUsed":
        # Offline workers never supplement; "notUsed" means no event needed a supplement.
        if not api_mode and _tri_bool(sh.get("learnIncomplete")) is True:
            warnings.append("learnMcp=notUsed なのに learnIncomplete=true のため false とした")
        return False
    if learn in LEARN_PARTIAL:
        return True
    flag = _tri_bool(sh.get("learnIncomplete"))
    if flag is None:
        # Missing / invalid on a Learn-MCP batch: assume partial rather than report a complete supplement.
        warnings.append("learnIncomplete が無い・不正のため true（一部補完）とみなした")
        return True
    return flag


def _tri_bool(v: Any) -> bool | None:
    if isinstance(v, bool):
        return v
    if isinstance(v, str) and v.strip().lower() in ("true", "false"):
        return v.strip().lower() == "true"
    return None


def check_batch(run: Path, st: dict, b: dict, meta: dict, accepted: dict
                ) -> tuple[dict, dict, list[str], str | None, bool | None]:
    """Returns (ok records by id, failures by id -> reason, warnings, learnMcp, learnIncomplete)."""
    assigned = list(b["noticeIds"])
    path = run / b["shardPath"]
    warnings: list[str] = []
    if not path.exists():
        return {}, {i: "shardMissing" for i in assigned}, warnings, None, None
    mrc = st.get("capabilities", {}).get("mrcMcp")
    api_mode = mrc == "不可"
    pf = b.get("prefetchFailedNoticeIds")
    if (mrc not in ("利用可", "不可") or b.get("bodySource") != ("ReleaseCommunicationsApi" if api_mode else "MRC MCP")
            or not isinstance(pf, list) or not all(isinstance(x, str) and x in assigned for x in pf)
            or len(set(pf)) != len(pf) or (pf and not api_mode)):
        return {}, {i: "malformedInput: dispatch provenance missing or inconsistent (redispatch)" for i in assigned}, warnings, None, None
    prefetch_failed = set(pf)
    bodies: dict = {}
    if api_mode:
        try:
            bodies = _prefetched_bodies(run, b)
        except ShardError as ex:
            return {}, {i: f"malformedInput: {ex} (redispatch)" for i in assigned}, warnings, None, None
    try:
        sh = read_json(path)
        if not isinstance(sh, dict):
            raise ShardError("shard must be an object")
        if sh.get("batchId") not in (b["batchId"], None):
            raise ShardError("batchId mismatch")
        exp = sh.get("expectedNoticeIds")
        ret = sh.get("returnedNoticeIds")
        fail = sh.get("failedNoticeIds")
        notices = sh.get("notices")
        if not all(isinstance(x, list) for x in (exp, ret, fail, notices)):
            raise ShardError("manifest arrays missing")
        if not all(isinstance(f, dict) and isinstance(f.get("id"), str) for f in fail):
            raise ShardError("failedNoticeIds[] must be objects with a string id")
        if not all(isinstance(n, dict) and isinstance(n.get("id"), str) for n in notices):
            raise ShardError("notices[] must be objects with a string id")
        if not all(isinstance(x, str) for x in exp + ret):
            raise ShardError("manifest ids must be strings")
        fail_ids = [f["id"] for f in fail]
        note_ids = [n["id"] for n in notices]
        for name, arr in (("expectedNoticeIds", exp), ("returnedNoticeIds", ret), ("failedNoticeIds", fail_ids), ("notices[]", note_ids)):
            if len(set(arr)) != len(arr):
                raise ShardError(f"{name} has duplicate ids")
        if set(exp) != set(assigned) or len(exp) != len(assigned):
            raise ShardError("expectedNoticeIds != assigned notices")
        if set(ret) & set(fail_ids) or set(ret) | set(fail_ids) != set(assigned):
            raise ShardError("returned ∪ failed != assigned (or overlap)")
        if set(note_ids) != set(ret):
            raise ShardError("notices[] ids != returnedNoticeIds")
        learn = sh.get("learnMcp")
        if learn not in LEARN_VALUES:
            # Required manifest field: it decides the run's Learn provenance, so a missing / invalid value is malformed.
            raise ShardError('learnMcp must be "available", "fallbackGet", "unavailable" or "notUsed"')
        if api_mode and learn != "notUsed":
            # The offline worker profile has no network (no Learn MCP, no GET); any other claim is not trusted.
            warnings.append(f"learnMcp={learn} は MRC MCP 不可の実行（オフラインワーカー）では使えないため notUsed とした")
            learn = "notUsed"
        incomplete = _learn_incomplete(sh, learn, api_mode, warnings)
    except (ShardError, ValueError, OSError) as ex:
        return {}, {i: f"malformedShard: {str(ex)[:120]}" for i in assigned}, warnings, None, None
    ok: dict = {}
    failures: dict = {}
    for f in fail:
        failures[f["id"]] = "fetchFailed: " + clean_text(f.get("reason"), 100)
    for n in notices:
        nid = n["id"]
        if nid in prefetch_failed:
            failures[nid] = "fetchFailed: 本文の事前取得に失敗（入力の body.fetchError）"
            continue
        try:
            rec = validate_notice(n, meta[nid], st["enumeration"]["allowedCategories"], warnings,
                                  required_via="ReleaseCommunicationsApi" if api_mode else None)
            if api_mode:
                enforce_body_provenance(rec, bodies.get(nid, {}), warnings)
            elif learn not in LEARN_KEEP:
                _drop_learn_outputs(rec, learn, warnings)
            elif learn == "fallbackGet":
                _drop_learn_remediation(rec, learn, warnings)
            rec["batchId"] = b["batchId"]
            ok[nid] = rec
        except ShardError as ex:
            failures[nid] = f"malformedShard: {ex}"
        except (TypeError, AttributeError, KeyError, ValueError) as ex:
            failures[nid] = f"malformedShard: unexpected shape ({type(ex).__name__})"
    # sameEventAs may only link notices of the same duplicate-candidate group, with evidence.
    group_of = {i: g["groupId"] for g in st["groups"] for i in g["noticeIds"]}
    targets = {(nid, e["eventKey"]) for nid, r in ok.items() for e in r["events"]}
    targets |= {tuple(x) for x in b.get("referenceEvents", [])}
    for nid, r in ok.items():
        for e in r["events"]:
            s = e["sameEventAs"]
            if not s:
                continue
            why = None
            if s["noticeId"] == nid:
                why = "参照先が自分自身"
            elif (s["noticeId"], s["eventKey"]) not in targets and s["noticeId"] not in failures:
                # A target that failed in this shard is retried; merge links it only if it is accepted later.
                why = "参照先が存在しない"
            elif group_of.get(nid) is None or group_of.get(nid) != group_of.get(s["noticeId"]):
                why = "参照先が同じ重複候補グループに無い"
            elif not s["evidence"]:
                why = "根拠（evidence）が空"
            if why:
                warnings.append(f"{e['eventKey']}: sameEventAs の{why}ため統合候補から外した")
                e["sameEventAs"] = None
    return ok, failures, warnings, learn, incomplete


def plan_retries(st: dict, by_id: dict, ids: list[str]) -> list[str]:
    group_of = {i: g for g in st["groups"] for i in g["noticeIds"]}
    by_group: dict[str | None, list[str]] = {}
    for i in sorted(ids, key=id_key):
        g = group_of.get(i)
        by_group.setdefault(g["groupId"] if g else None, []).append(i)
    created: list[str] = []

    def bid_for(ids_: list[str]) -> tuple[str, int]:
        src = st["noticeStatus"][ids_[0]]["batchId"].split("-r")[0]
        attempt = max(st["noticeStatus"][i]["attempts"] for i in ids_) + 1
        bid, k = f"{src}-r{attempt}", 1
        existing = {b["batchId"] for b in st["batches"]}
        while bid in existing:
            k += 1
            bid = f"{src}-r{attempt}{chr(ord('a') + k - 1)}"
        return bid, attempt

    singles = by_group.pop(None, [])
    for gid, mem in by_group.items():
        g = next(x for x in st["groups"] if x["groupId"] == gid)
        has_ref = any(m not in mem and st["noticeStatus"][m]["status"] == "ok" for m in g["noticeIds"])
        size = MAX_BATCH - 1 if has_ref else MAX_BATCH
        for k in range(0, len(mem), size):
            chunk = mem[k:k + size]
            bid, att = bid_for(chunk)
            b = _new_batch(st, bid, chunk, ref_group=gid if has_ref else None, attempt=att)
            b["groupIds"].append(gid)
            g["batchIds"].append(bid)
            created.append(bid)
    for k in range(0, len(singles), MAX_BATCH):
        chunk = singles[k:k + MAX_BATCH]
        bid, att = bid_for(chunk)
        _new_batch(st, bid, chunk, attempt=att)
        created.append(bid)
    return created


def cmd_check_shards(args: Any, run: Path) -> dict:
    from .progress import render_progress
    with RunLock(run):
        st = load_state(run)
        require_phase(st, ("planned",), "check-shards")
        meta = {n["id"]: n for n in load_candidates(run, st)}
        accepted = load_accepted(run)
        report = []
        retry_ids: list[str] = []
        for b in [x for x in st["batches"] if x["status"] == "dispatched"]:
            ok, failures, warnings, learn, incomplete = check_batch(run, st, b, meta, accepted)
            for nid, rec in ok.items():
                accepted[nid] = rec
                st["noticeStatus"][nid].update({"status": "ok", "reason": None})
            for nid, reason in failures.items():
                ns = st["noticeStatus"][nid]
                ns["reason"] = reason
                if ns["attempts"] >= MAX_ATTEMPTS:
                    ns["status"] = "exhausted"
                else:
                    ns["status"] = "failed"
                    retry_ids.append(nid)
            b["status"] = "done" if not failures else ("failed" if not ok else "partial")
            b["learnMcp"] = learn
            b["learnIncomplete"] = incomplete
            b["warnings"] = warnings[:50]
            report.append({"batchId": b["batchId"], "status": b["status"], "returned": len(ok),
                           "failed": {k: v for k, v in failures.items()}, "warnings": len(warnings)})
            if failures:
                log(st, "check-shards", f"{b['batchId']}: 失敗 {len(failures)} 件（{', '.join(sorted(failures, key=id_key))}）")
        write_json(run, ".work/accepted.json", accepted)
        created = plan_retries(st, meta, retry_ids) if retry_ids else []
        if created:
            log(st, "check-shards", f"再委譲バッチ {', '.join(created)} を作成")
        remaining = [b["batchId"] for b in st["batches"] if b["status"] in ("pending", "dispatched")]
        result: dict = {"run": st["runId"], "checked": report, "retryBatches": created}
        if not remaining:
            ns = st["noticeStatus"]
            cand = st["enumeration"]["candidateNoticeIds"]
            okc = [i for i in cand if ns[i]["status"] == "ok"]
            ex = [i for i in cand if ns[i]["status"] == "exhausted"]
            g2 = len(okc) + len(ex) == len(cand)
            # Only batches whose records were finally accepted decide the run's Learn provenance (not superseded attempts).
            effective = {accepted[i]["batchId"] for i in okc if i in accepted}
            eff_batches = [b for b in st["batches"] if b["batchId"] in effective and b["learnMcp"]]
            learns = [b["learnMcp"] for b in eff_batches]
            st["capabilities"]["learnMcp"] = learn_capability(learns)
            # A batch can mix Learn MCP and the GET fallback while reporting "available"; its flag is OR-ed in.
            st["learnSupplementIncomplete"] = any(x in LEARN_PARTIAL for x in learns) or any(
                b.get("learnIncomplete") for b in eff_batches)
            st["gates"]["G2"] = {"status": "pass" if g2 else "fail", "returned": len(okc), "failed": ex}
            if g2:
                st["phase"] = "collected"
                log(st, "check-shards", f"G2 合格: 返却 {len(okc)} 件・取得失敗（再試行上限）{len(ex)} 件")
            result["G2"] = st["gates"]["G2"]
            result["next"] = f"merge --run {st['runId']}"
        else:
            result["next"] = f"next-wave --run {st['runId']}"
        save_state(run, st)
        write_text(run, "progress.md", render_progress(st))
    return result
