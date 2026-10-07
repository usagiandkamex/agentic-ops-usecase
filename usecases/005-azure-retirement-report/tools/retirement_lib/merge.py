"""Step 6 (G3): notice finalization, sameEventAs merge, scope filter, scoring, aggregation, highlight."""
from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from .common import (PLACEHOLDER_RE, REPO_REL_REPORTS, TOOL_VERSION, RunLock, ToolError, clean_text, id_key,
                     jst_stamp, load_state, log, ordinal_ignore_case_key, read_json, require_phase, save_state,
                     sensitive_kinds, url_violation, walk_strings, write_json, write_text)
from .plan import _UF, _recency, load_accepted, load_candidates

MATRIX = {3: {3: "High", 2: "High", 1: "Medium"}, 2: {3: "High", 2: "Medium", 1: "Low"}, 1: {3: "Medium", 2: "Low", 1: "Low"}}
IMPACT_RULE = {
    "_comment": "影響度の決定論ルール（同梱ツールの merge が適用。テンプレの値を変更しない）。",
    "severity": {"S3": "flags.workloadStop=true または flags.dataLossRisk=true",
                 "S1": "flags.autoMigration=true かつ workloadStop・dataLossRisk のいずれも true でない",
                 "S2": "上記以外（unknown を含む・保守的）"},
    "urgency": {"U3": "status=retired または status=currentMonth または daysRemaining<=90",
                "U2": "daysRemaining<=365", "U1": "daysRemaining>365"},
    "matrix": {"S3": {"U3": "High", "U2": "High", "U1": "Medium"}, "S2": {"U3": "High", "U2": "Medium", "U1": "Low"},
               "S1": {"U3": "Medium", "U2": "Low", "U1": "Low"}},
    "needsReview": "retireDate.precision=unknown または classificationStatus=insufficientEvidence の場合は impact=NeedsReview（要確認）",
}
SOURCES = {
    "primary": "Microsoft Release Communications MCP (get_recent_azure_updates / get_azure_update_by_id)",
    "fallback": "Release Communications 公開 API https://www.microsoft.com/releasecommunications/api/v2/azure（Azure Updates https://azure.microsoft.com/ja-jp/updates/ と同一データ源）",
    "remediationSupplement": "Microsoft Learn MCP（本文に公式リンクが無い場合のみ）",
}
UNDATED = "日付不明"


def update_url(nid: str) -> str:
    return f"https://azure.microsoft.com/ja-jp/updates/?id={nid}"


# ---------------------------------------------------------------- deterministic scoring (shared by merge and G3)

def score(e: dict, as_of: dt.date) -> dict:
    rd = e["retireDate"]
    if rd["precision"] == "unknown" or not rd.get("start"):
        status, days = "unknown", None
    else:
        start, end = dt.date.fromisoformat(rd["start"]), dt.date.fromisoformat(rd["end"])
        days = (start - as_of).days
        status = "retired" if end < as_of else "currentMonth" if rd["precision"] == "month" and start <= as_of else "upcoming"
    if status == "unknown" or e["classificationStatus"] == "insufficientEvidence":
        reason = "リタイア日不明 → NeedsReview" if status == "unknown" else "根拠不足（insufficientEvidence）→ NeedsReview"
        return {"status": status, "daysRemaining": days, "severityScore": None, "urgencyScore": None,
                "impact": "NeedsReview", "impactReasonJa": reason}
    f = e["flags"]
    urg = 3 if status in ("retired", "currentMonth") or days <= 90 else 2 if days <= 365 else 1
    if f["workloadStop"] == "true" or f["dataLossRisk"] == "true":
        sev = 3
        why = ("停止・データ消失の明記あり" if f["workloadStop"] == "true" and f["dataLossRisk"] == "true"
               else "停止の明記あり" if f["workloadStop"] == "true" else "データ消失の明記あり")
    elif f["autoMigration"] == "true":
        sev, why = 1, "自動移行の明記あり"
    else:
        sev, why = 2, "停止・消失の明記なし"
    u_why = "リタイア済み" if status == "retired" else "当月" if status == "currentMonth" else f"残 {days} 日"
    imp = MATRIX[sev][urg]
    return {"status": status, "daysRemaining": days, "severityScore": sev, "urgencyScore": urg, "impact": imp,
            "impactReasonJa": f"S{sev}（{why}）× U{urg}（{u_why}）→ {imp}"}


def quarter_of(e: dict) -> str:
    rd = e["retireDate"]
    if rd["precision"] == "unknown" or not rd.get("start"):
        return UNDATED
    d = dt.date.fromisoformat(rd["start"])
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _counts(evs: list[dict]) -> dict:
    return {"total": len(evs), "high": sum(e["impact"] == "High" for e in evs), "medium": sum(e["impact"] == "Medium" for e in evs),
            "low": sum(e["impact"] == "Low" for e in evs), "needsReview": sum(e["impact"] == "NeedsReview" for e in evs)}


def aggregate(events: list[dict], notices: list[dict]) -> tuple[dict, list[dict], list[dict]]:
    summary = {
        "noticeCount": len(notices), "eventCount": len(events),
        "highCount": sum(e["impact"] == "High" for e in events), "mediumCount": sum(e["impact"] == "Medium" for e in events),
        "lowCount": sum(e["impact"] == "Low" for e in events), "needsReviewCount": sum(e["impact"] == "NeedsReview" for e in events),
        "within90DaysCount": sum(e["status"] == "currentMonth" or (e["status"] == "upcoming" and e["daysRemaining"] <= 90) for e in events),
        "currentMonthCount": sum(e["status"] == "currentMonth" for e in events),
        "retiredCount": sum(e["status"] == "retired" for e in events),
        "dateConflictCount": sum(e["dateConflict"] is True for e in events),
        "inferredClassificationCount": sum(e["productSource"] == "inferred" or e["categorySource"] == "inferred" for e in events),
    }
    cats = sorted({c for e in events for c in (e["categories"] or ["Uncategorized"]) if c != "Uncategorized"}, key=ordinal_ignore_case_key)
    if any("Uncategorized" in (e["categories"] or ["Uncategorized"]) for e in events):
        cats.append("Uncategorized")
    by_cat = [{"category": c, **_counts([e for e in events if c in (e["categories"] or ["Uncategorized"])])} for c in cats]
    qs = sorted({quarter_of(e) for e in events} - {UNDATED})
    if any(quarter_of(e) == UNDATED for e in events):
        qs.append(UNDATED)
    by_q = [{"quarter": q, **_counts([e for e in events if quarter_of(e) == q])} for q in qs]
    return summary, by_cat, by_q


# ---------------------------------------------------------------- findings skeleton / base

def _metadata(st: dict) -> dict:
    return {"generatedAt": jst_stamp(), "asOfDate": st["asOfDate"], "timezone": "JST (UTC+9)", "scope": st["scope"],
            "sources": SOURCES, "collectionMethod": "", "capabilities": st["capabilities"],
            "reportFolder": f"{REPO_REL_REPORTS}/{st['runId']}/", "toolVersion": TOOL_VERSION, "snapshotId": st["snapshotId"]}


def _ledger(st: dict) -> dict:
    e = st["enumeration"]
    return {"retirementsTotal": e["retirementsTotal"], "enumeration": {k: v for k, v in e["enumeration"].items() if k != "attempts"},
            "candidateNoticeIds": e["candidateNoticeIds"], "prefilter": e["prefilter"], "workerReturnedNoticeIds": [],
            "failedNoticeIds": [], "outOfScopeAfterExtraction": [], "eventCount": 0, "mergedEvents": []}


def _batches_out(st: dict) -> list[dict]:
    m = {"done": "done", "partial": "downgraded", "failed": "failed"}
    return [{"batchId": b["batchId"], "noticeIds": b["noticeIds"], "referenceNoticeIds": b["referenceNoticeIds"],
             "dupGroupIds": b["groupIds"], "shardPath": b["shardPath"], "status": m.get(b["status"], "pending"),
             "attempts": b["attempt"]} for b in st["batches"]]


def _plan(task: str, required: str, step: int, query: str, status: str = "pending", expected: Any = None,
          result: Any = None, note: str = "") -> dict:
    return {"task": task, "requiredBy": required, "dueStep": step, "status": status,
            "evidence": {"query": query, "expectedCount": expected, "resultCount": result,
                         "collectedAt": jst_stamp() if status != "pending" else "", "note": note}}


def _collection_plan(st: dict, final: dict | None = None) -> list[dict]:
    e = st["enumeration"]
    en = e["enumeration"]
    cand = len(e["candidateNoticeIds"])
    plan = [_plan("Enumerate:retirementNotices", "常時", 4, "tags/any(t:t eq 'Retirements') ＋ 年フィルタと補集合 ＋ 補集合の本文の年による候補補完",
                  "done", en["inScopeCount"] + len(e["prefilter"]["bodyYearMatchedNoticeIds"]), cand,
                  f"consistent={'true' if en['consistent'] else 'false'}／screenStatus={e['prefilter']['screenStatus']}")]
    if final is None:
        plan += [_plan("Detail:fetchAndExtract", "常時", 5, "get_azure_update_by_id（ワーカー並列）"),
                 _plan("Remediation:learnSupplement", "learnMcp=利用可", 5, "microsoft_docs_search（本文に公式リンクが無い event のみ）"),
                 _plan("Normalize:eventsAndDedup", "常時", 6, "shard 統合・sameEventAs 統合・範囲の最終判定"),
                 _plan("Score:impactAndSummary", "常時", 6, "impactRule の決定論適用・summary/byCategory/byQuarter 集計")]
        return plan
    failed = final["failed"]
    learn = st["capabilities"]["learnMcp"]
    plan += [
        _plan("Detail:fetchAndExtract", "常時", 5, "get_azure_update_by_id（ワーカー並列）", "downgraded" if failed else "done",
              cand, final["returned"], ("取得失敗: " + ", ".join(failed)) if failed else ""),
        _plan("Remediation:learnSupplement", "learnMcp=利用可", 5, "microsoft_docs_search（本文に公式リンクが無い event のみ）",
              "downgraded" if learn == "不可" else "done", None, final["learnLinks"], f"learnMcp={learn}"),
        _plan("Normalize:eventsAndDedup", "常時", 6, "shard 統合・sameEventAs 統合・範囲の最終判定", "done",
              None, final["eventCount"], f"統合 {final['merged']} 件・範囲外 {final['outOfScope']} 件"),
        _plan("Score:impactAndSummary", "常時", 6, "impactRule の決定論適用・summary/byCategory/byQuarter 集計", "done",
              final["eventCount"], final["eventCount"], ""),
    ]
    return plan


def _empty_summary() -> dict:
    s, _, _ = aggregate([], [])
    s["statusHighlight"] = ""
    return s


def write_findings_skeleton(run: Path, st: dict, cands: list[dict]) -> None:
    notices = [{"id": n["id"], "title": n["title"], "titleJa": "", "updateUrl": update_url(n["id"]), "products": n["products"],
                "productSource": "api", "categories": n["productCategories"], "categorySource": "api",
                "availabilityMonth": n["availabilityMonth"], "created": n["created"], "modified": n["modified"],
                "fetchStatus": "pending", "fetchedVia": "", "batchId": st["noticeStatus"][n["id"]]["batchId"], "eventIds": []}
               for n in cands]
    f = {"metadata": _metadata(st), "ledger": _ledger(st), "summary": _empty_summary(), "impactRule": IMPACT_RULE,
         "notices": notices, "events": [], "byCategory": [], "byQuarter": [], "batches": _batches_out(st),
         "dupCandidateGroups": st["groups"], "collectionPlan": _collection_plan(st)}
    write_json(run, "findings.json", f)


# ---------------------------------------------------------------- merge

def _empty(v: Any) -> bool:
    return v in (None, "", [], "notFound", "Unknown")


def merge_events(cands: dict, accepted: dict, groups: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (clusters as merged event dicts without computed fields, mergedEvents ledger)."""
    uf = _UF()
    node = {}
    for nid, rec in accepted.items():
        for e in rec["events"]:
            k = f"{nid}\u0001{e['eventKey']}"
            node[k] = (nid, e)
            uf.find(k)
    for nid, rec in accepted.items():
        for e in rec["events"]:
            s = e.get("sameEventAs")
            if s:
                other = f"{s['noticeId']}\u0001{s['eventKey']}"
                if other in node:
                    uf.union(f"{nid}\u0001{e['eventKey']}", other)
    clusters: dict[str, list[str]] = {}
    for k in node:
        clusters.setdefault(uf.find(k), []).append(k)
    group_of = {i: g for g in groups for i in g["noticeIds"]}
    merged_ledger = []
    out = []
    for keys in clusters.values():
        members = [node[k] for k in keys]
        rec_of = lambda m: cands[m[0]]  # noqa: E731
        by_recency = sorted(members, key=lambda m: _recency(rec_of(m)), reverse=True)
        rep_nid = by_recency[0][0]
        rep = next(m for m in members if m[0] == rep_nid)
        rep_e = rep[1]
        date_src = next((m for m in by_recency if m[1]["retireDate"]["source"] == "description"), rep)
        de = date_src[1]
        notes = [de["dateNoteJa"]] if de["dateNoteJa"] else []
        adopted = (de["retireDate"]["start"], de["retireDate"]["precision"])
        for _, e in by_recency:
            rd = e["retireDate"]
            if rd["start"] and (rd["start"], rd["precision"]) != adopted:
                label = f"旧告知: {rd['start'][:7] if rd['precision'] == 'month' else rd['start']}"
                if label not in notes:
                    notes.append(label)
        flags, evid = {}, {}
        conflict = False
        for f in ("workloadStop", "dataLossRisk", "autoMigration"):
            vals = [e["flags"][f] for _, e in by_recency]
            v = "true" if "true" in vals else "false" if "false" in vals else "unknown"
            conflict |= "true" in vals and "false" in vals
            flags[f] = v
            evid[f] = next((e["flagEvidence"][f] for _, e in by_recency if e["flags"][f] == v and e["flagEvidence"][f]), "")
        cls = rep_e["classificationStatus"]
        if cls == "insufficientEvidence":
            cls = next((e["classificationStatus"] for _, e in by_recency if e["classificationStatus"] != "insufficientEvidence"), cls)
        if conflict:
            cls = "ambiguous"

        def pick(field: str) -> Any:
            if not _empty(rep_e[field]):
                return rep_e[field]
            return next((e[field] for _, e in by_recency if not _empty(e[field])), rep_e[field])
        if rep_e["remediationStatus"] != "notFound":
            rem, rstat = rep_e["remediationJa"], rep_e["remediationStatus"]
        else:
            alt = next((e for _, e in by_recency if e["remediationStatus"] != "notFound"), rep_e)
            rem, rstat = alt["remediationJa"], alt["remediationStatus"]
        ms, links, seen_l = [], [], set()
        for _, e in [rep] + [m for m in by_recency if m is not rep]:
            for x in e["milestones"]:
                if not any(y["date"] == x["date"] and y["labelJa"] == x["labelJa"] for y in ms):
                    ms.append(x)
            for l in e["referenceLinks"]:
                if l["url"] not in seen_l:
                    seen_l.add(l["url"])
                    links.append(l)
        nids = [rep_nid] + sorted({m[0] for m in members} - {rep_nid}, key=id_key)
        single = len(accepted[rep_nid]["events"]) == 1
        event_id = rep_nid if single else rep_e["eventKey"]
        if not single and event_id in cands:
            # A split key such as "foo-1" must not collide with another notice id "foo-1"; '~' never appears in ids.
            event_id = f"{rep_nid}~{rep_e['eventKey'].rsplit('-', 1)[1]}"
        related = sorted({i for n in nids for i in (group_of[n]["noticeIds"] if n in group_of else [])} - set(nids), key=id_key)
        out.append({"eventId": event_id, "rep": rep_nid, "noticeIds": nids, "relatedNoticeIds": related, "event": {
            "affectedScopeJa": pick("affectedScopeJa"), "retireDate": de["retireDate"], "dateConflict": de["dateConflict"],
            "dateNoteJa": clean_text(" / ".join(notes), 500), "milestones": ms[:15], "impactType": pick("impactType"),
            "flags": flags, "flagEvidence": evid, "classificationStatus": cls, "summaryJa": pick("summaryJa"),
            "remediationJa": rem, "remediationStatus": rstat, "migrationTarget": pick("migrationTarget"),
            "referenceLinks": links[:10]}})
        if len(nids) > 1:
            ev = " / ".join(dict.fromkeys(e["sameEventAs"]["evidence"] for _, e in members if e.get("sameEventAs") and e["sameEventAs"]["evidence"]))
            merged_ledger.append({"eventId": event_id, "mergedNoticeIds": nids, "evidence": clean_text(ev, 500)})
    return out, merged_ledger


def in_window(rd: dict, ws: str | None, we: str | None) -> bool:
    if rd["precision"] == "unknown" or not rd.get("start"):
        return True
    return (we is None or rd["start"] <= we) and (ws is None or rd["end"] >= ws)


def build_findings(st: dict, cands: list[dict], accepted: dict) -> dict:
    as_of = dt.date.fromisoformat(st["asOfDate"])
    meta = {n["id"]: n for n in cands}
    allowed = set(st["enumeration"]["allowedCategories"])
    final_notice: dict[str, dict] = {}
    for nid, rec in accepted.items():
        n = meta[nid]
        if n["products"]:
            prods, psrc = n["products"], "api"
        elif rec["inferredProducts"]:
            prods, psrc = rec["inferredProducts"], "inferred"
        else:
            prods, psrc = [], "api"
        inferred_cats = [c for c in rec["inferredCategories"] if c in allowed and c != "Uncategorized"]
        if n["productCategories"]:
            cats, csrc = n["productCategories"], "api"
        elif inferred_cats:
            cats, csrc = inferred_cats, "inferred"
        else:
            cats, csrc = ["Uncategorized"], "uncategorized"
        final_notice[nid] = {"id": nid, "title": n["title"], "titleJa": rec["titleJa"], "updateUrl": update_url(nid),
                             "products": prods, "productSource": psrc, "categories": cats, "categorySource": csrc,
                             "availabilityMonth": n["availabilityMonth"], "created": n["created"], "modified": n["modified"],
                             "fetchStatus": "ok", "fetchedVia": rec["fetchedVia"], "batchId": rec["batchId"], "eventIds": []}
    clusters, merged_ledger = merge_events(meta, accepted, st["groups"])
    ws, we = st["scope"]["windowStart"], st["scope"]["windowEnd"]
    events, out_of_scope = [], []
    for c in clusters:
        e = c["event"]
        if not in_window(e["retireDate"], ws, we):
            out_of_scope.append({"id": c["rep"], "eventKey": c["eventId"], "reason": "retireDateOutsideWindow"})
            continue
        rn = final_notice[c["rep"]]
        ev = {"eventId": c["eventId"], "primaryNoticeId": c["rep"], "noticeIds": c["noticeIds"], "relatedNoticeIds": c["relatedNoticeIds"],
              "title": rn["title"], "titleJa": rn["titleJa"], "updateUrl": rn["updateUrl"], "categories": rn["categories"],
              "categorySource": rn["categorySource"], "products": rn["products"], "productSource": rn["productSource"],
              "affectedScopeJa": e["affectedScopeJa"], "retireDate": e["retireDate"]}
        sc = score({**e}, as_of)
        ev.update({"status": sc["status"], "daysRemaining": sc["daysRemaining"], "dateConflict": e["dateConflict"],
                   "dateNoteJa": e["dateNoteJa"], "milestones": e["milestones"], "impactType": e["impactType"], "flags": e["flags"],
                   "flagEvidence": e["flagEvidence"], "classificationStatus": e["classificationStatus"],
                   "severityScore": sc["severityScore"], "urgencyScore": sc["urgencyScore"], "impact": sc["impact"],
                   "impactReasonJa": sc["impactReasonJa"], "summaryJa": e["summaryJa"], "remediationJa": e["remediationJa"],
                   "remediationStatus": e["remediationStatus"], "migrationTarget": e["migrationTarget"],
                   "referenceLinks": e["referenceLinks"]})
        events.append(ev)
    events.sort(key=lambda e: (e["retireDate"]["start"] is None, e["retireDate"]["start"] or "", id_key(e["primaryNoticeId"]), e["eventId"]))
    kept_ids = {e["eventId"] for e in events}
    merged_ledger = [m for m in merged_ledger if m["eventId"] in kept_ids]
    for e in events:
        for nid in e["noticeIds"]:
            final_notice[nid]["eventIds"].append(e["eventId"])
    notices = sorted([n for n in final_notice.values() if n["eventIds"]], key=lambda n: id_key(n["id"]))
    ns = st["noticeStatus"]
    failed = [{"id": i, "reason": "retriesExhausted", "attempts": ns[i]["attempts"]}
              for i in st["enumeration"]["candidateNoticeIds"] if ns[i]["status"] == "exhausted"]
    summary, by_cat, by_q = aggregate(events, notices)
    summary["statusHighlight"] = ""
    ledger = _ledger(st)
    ledger.update({"workerReturnedNoticeIds": sorted(accepted, key=id_key), "failedNoticeIds": failed,
                   "outOfScopeAfterExtraction": out_of_scope, "eventCount": len(events), "mergedEvents": merged_ledger})
    md = _metadata(st)
    via = [r["fetchedVia"] for r in accepted.values()]
    md["collectionMethod"] = (f"列挙・件数照合: 公開 API／本文取得: MRC MCP {via.count('MRC MCP')} 件・公開 API {via.count('ReleaseCommunicationsApi')} 件"
                              f"（並列ワーカー {len(st['batches'])} バッチ）")
    learn_links = sum(1 for e in events for l in e["referenceLinks"] if l["source"] == "LearnSearch")
    final = {"failed": [f["id"] for f in failed], "returned": len(accepted), "eventCount": len(events),
             "merged": len(merged_ledger), "outOfScope": len(out_of_scope), "learnLinks": learn_links}
    return {"metadata": md, "ledger": ledger, "summary": summary, "impactRule": IMPACT_RULE, "notices": notices, "events": events,
            "byCategory": by_cat, "byQuarter": by_q, "batches": _batches_out(st), "dupCandidateGroups": st["groups"],
            "collectionPlan": _collection_plan(st, final)}


# ---------------------------------------------------------------- G3

def verify_findings(f: dict) -> list[str]:
    fails: list[str] = []
    as_of = dt.date.fromisoformat(f["metadata"]["asOfDate"])
    events, notices = f["events"], f["notices"]
    for e in events:
        sc = score(e, as_of)
        diff = [k for k in ("status", "daysRemaining", "severityScore", "urgencyScore", "impact") if e.get(k) != sc[k]]
        if diff:
            fails.append(f"1 per-event mismatch {e['eventId']}: {','.join(diff)}")
    ids = [e["eventId"] for e in events]
    if len(set(ids)) != len(ids):
        fails.append("2 duplicate eventId")
    pe = {(n, e["eventId"]) for e in events for n in e["noticeIds"]}
    pn = {(n["id"], x) for n in notices for x in n["eventIds"]}
    if pe != pn:
        fails.append(f"2b notice/event pairs differ (events-only={len(pe - pn)} notices-only={len(pn - pe)})")
    if any(not e["noticeIds"] for e in events):
        fails.append("2b event without notice")
    summary, by_cat, by_q = aggregate(events, notices)
    for k, v in summary.items():
        if f["summary"].get(k) != v:
            fails.append(f"3 summary.{k}: findings={f['summary'].get(k)} expected={v}")
    if f["byCategory"] != by_cat:
        fails.append("4 byCategory (values or order) differ")
    if f["byQuarter"] != by_q:
        fails.append("5 byQuarter (values or order) differ")
    bad = [p["task"] for p in f["collectionPlan"] if p["status"] in ("pending", "failed")]
    if bad:
        fails.append("6 collectionPlan pending/failed: " + ",".join(bad))
    led = f["ledger"]
    if set(led["candidateNoticeIds"]) != set(led["workerReturnedNoticeIds"]) | {x["id"] for x in led["failedNoticeIds"]}:
        fails.append("7 candidateNoticeIds != workerReturned ∪ failed")
    return fails + safety_findings(f)


def safety_findings(f: dict) -> list[str]:
    """Pre-render safety: e-mail / SafeLinks anywhere (path + kind only), URL allowlist for events."""
    fails = []
    for path, s in walk_strings(f):
        for kind in sensitive_kinds(s):
            fails.append(f"7a sensitive {path} {kind}")
    for i, e in enumerate(f["events"]):
        cands = [("updateUrl", e.get("updateUrl"))] + [(f"referenceLinks[{j}].url", l.get("url")) for j, l in enumerate(e.get("referenceLinks") or [])]
        for p, u in cands:
            v = url_violation(u)
            if v:
                fails.append(f"7b events[{i}].{p} {v}")
    return fails


def cmd_merge(args: Any, run: Path) -> dict:
    from .progress import render_progress
    with RunLock(run):
        st = load_state(run)
        require_phase(st, ("collected", "merged", "highlighted", "rendered"), "merge")
        cands = load_candidates(run, st)
        f = build_findings(st, cands, load_accepted(run))
        fails = verify_findings(f)
        st["gates"]["G3"] = {"status": "fail" if fails else "pass", "details": fails[:20]}
        st["gates"].pop("G4", None)
        st.pop("review", None)
        write_json(run, "findings.json", f)
        if fails:
            save_state(run, st)
            raise ToolError("G3 failed", code=1, failures=fails[:20])
        st["phase"] = "merged"
        log(st, "merge", f"イベント {len(f['events'])} 件（投稿 {len(f['notices'])} 件・統合 {len(f['ledger']['mergedEvents'])} 件・範囲外 {len(f['ledger']['outOfScopeAfterExtraction'])} 件）を確定し G3 に合格")
        save_state(run, st)
        write_text(run, "progress.md", render_progress(st))
    s = f["summary"]
    top = [{"eventId": e["eventId"], "titleJa": e["titleJa"], "retireDate": e["retireDate"]["start"], "impact": e["impact"]}
           for e in f["events"] if e["impact"] == "High"][:8]
    return {"run": st["runId"], "G3": "pass", "summary": s, "highlightFacts": {"highEvents": top,
            "byCategoryTop": sorted(f["byCategory"], key=lambda c: -c["total"])[:5]},
            "next": (f"上の事実だけを使って総評（2〜4 文・日本語）を書き、set-highlight --run {st['runId']} --text \"...\" で記録する")}


def cmd_set_highlight(args: Any, run: Path) -> dict:
    from .progress import render_progress
    text = clean_text(args.text, 700)
    errors = []
    if len(text) < 20:
        errors.append("総評が短すぎる（20 文字以上）")
    if "{{" in text or PLACEHOLDER_RE.search(text) or "<" in text or ">" in text:
        errors.append("総評に山括弧・プレースホルダ・テンプレートトークンを含めない")
    if text != (args.text or "").strip() and "削除]" in text:
        errors.append("総評にメールアドレス・SafeLinks を含めない")
    if errors:
        raise ToolError("set-highlight rejected", errors=errors)
    with RunLock(run):
        st = load_state(run)
        require_phase(st, ("merged", "highlighted", "rendered"), "set-highlight")
        f = read_json(run / "findings.json")
        f["summary"]["statusHighlight"] = text
        fails = verify_findings(f)
        if fails:
            raise ToolError("G3 failed after setting the highlight", code=1, failures=fails[:20])
        write_json(run, "findings.json", f)
        st["phase"] = "highlighted"
        st["gates"].pop("G4", None)
        st.pop("review", None)
        log(st, "set-highlight", "総評を記録")
        save_state(run, st)
        write_text(run, "progress.md", render_progress(st))
    return {"run": st["runId"], "statusHighlight": text,
            "next": f"azure-retirement-report-writer に render / verify と独立レビューを委譲する（render --run {st['runId']}）"}
