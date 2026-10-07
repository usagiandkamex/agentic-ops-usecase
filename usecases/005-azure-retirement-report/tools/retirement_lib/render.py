"""Step 7-8 (G4): template rendering with per-sink escaping, report gates, review record, finalize."""
from __future__ import annotations

import base64
import csv
import hashlib
import html
import io
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

from .common import (EMAIL_RE, PLACEHOLDER_RE, SAFELINKS_RE, TEMPLATE_DIR, RunLock, ToolError, clean_text,
                     deep_unescape, html_escape, load_state, log, read_json, require_phase, save_state, url_violation,
                     write_text)
from .merge import safety_findings, verify_findings

FALLBACK_TEXT = "該当なし（対象期間のリタイア情報はありません）"
FALLBACK_ROW = f'<tr><td colspan="6" class="empty">{FALLBACK_TEXT}</td></tr>'
NUMERIC_COLS = {"daysRemaining", "severityScore", "urgencyScore"}
SECTIONS = ("summary", "retirement-list", "by-category", "by-quarter", "impact-rule", "sources")
SCRIPT_RE = re.compile(r"<script>([\s\S]*?)</script>")
CSP_RE = re.compile(r'<meta http-equiv="Content-Security-Policy"[^>]*>')
ISLAND_RE = re.compile(r'<script type="application/json" id="retirement-data">([\s\S]*?)</script>')
BLOCK_OR_TOKEN_RE = re.compile(r"<!-- BEGIN (\w+) -->\n([\s\S]*?)<!-- END \1 -->\n?|\{\{([A-Z0-9_]+)\}\}")


def _template(name: str) -> str:
    return (TEMPLATE_DIR / name).read_text(encoding="utf-8").replace("\r\n", "\n")


def _strip_head_comment(t: str) -> str:
    return re.sub(r"^(<!DOCTYPE html>\n)<!--[\s\S]*?-->\n", r"\1", t, count=1)


def island_json(events: list) -> str:
    s = json.dumps(events, ensure_ascii=False, separators=(",", ":"))
    return s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _rows(items: list[dict], key: str, row_tpl: str, prefix: str) -> str:
    if not items:
        return FALLBACK_ROW + "\n"
    out = []
    for it in items:
        vals = {prefix[0]: html_escape(it[key]), f"{prefix[1]}_TOTAL": str(it["total"]), f"{prefix[1]}_HIGH": str(it["high"]),
                f"{prefix[1]}_MEDIUM": str(it["medium"]), f"{prefix[1]}_LOW": str(it["low"]),
                f"{prefix[1]}_NEEDS_REVIEW": str(it["needsReview"])}
        out.append(re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: vals[m.group(1)], row_tpl))
    return "".join(out)


def render_html(f: dict) -> str:
    t = _strip_head_comment(_template("index.html"))
    md, s, led = f["metadata"], f["summary"], f["ledger"]
    tok = {
        "META_DATETIME": md["generatedAt"], "AS_OF_DATE": md["asOfDate"], "SCOPE_LABEL": md["scope"]["label"],
        "COLLECTION_METHOD": md["collectionMethod"], "CAP_MRC_MCP": md["capabilities"]["mrcMcp"],
        "CAP_RC_API": md["capabilities"]["releaseCommunicationsApi"], "CAP_LEARN_MCP": md["capabilities"]["learnMcp"],
        "NOTICE_COUNT": s["noticeCount"], "EVENT_COUNT": s["eventCount"], "HIGH_COUNT": s["highCount"],
        "MEDIUM_COUNT": s["mediumCount"], "LOW_COUNT": s["lowCount"], "NEEDS_REVIEW_COUNT": s["needsReviewCount"],
        "WITHIN_90_COUNT": s["within90DaysCount"], "RETIRED_COUNT": s["retiredCount"], "DATE_CONFLICT_COUNT": s["dateConflictCount"],
        "STATUS_HIGHLIGHT": s["statusHighlight"],
        "RETIREMENTS_TOTAL": led["retirementsTotal"]["lastObserved"], "INSCOPE_COUNT": led["enumeration"]["inScopeCount"],
        "COMPLEMENT_COUNT": led["enumeration"]["complementCount"],
        "ENUM_CONSISTENT": "はい" if led["enumeration"]["consistent"] else "いいえ",
        "CANDIDATE_COUNT": len(led["candidateNoticeIds"]), "PREFILTERED_OUT_COUNT": led["prefilter"]["excludedCount"],
        "WORKER_RETURNED_COUNT": len(led["workerReturnedNoticeIds"]), "FAILED_COUNT": len(led["failedNoticeIds"]),
        "OUT_OF_SCOPE_COUNT": len(led["outOfScopeAfterExtraction"]), "MERGED_COUNT": len(led["mergedEvents"]),
    }
    island = island_json(f["events"])

    def sub(m: re.Match) -> str:
        if m.group(1) == "CATEGORY_ROWS":
            return _rows(f["byCategory"], "category", m.group(2), ("CATEGORY", "CAT"))
        if m.group(1) == "QUARTER_ROWS":
            return _rows(f["byQuarter"], "quarter", m.group(2), ("QUARTER", "Q"))
        if m.group(1):
            raise ToolError(f"unknown template block {m.group(1)}")
        name = m.group(3)
        if name == "EVENTS_JSON":
            return island
        if name not in tok:
            raise ToolError(f"unknown template token {name}")
        return html_escape(tok[name])

    # Single pass: inserted data is never re-scanned for tokens or markers.
    return BLOCK_OR_TOKEN_RE.sub(sub, t)


def csv_cells(e: dict) -> dict:
    j = lambda a: " | ".join(str(x) for x in (a or []) if x is not None)  # noqa: E731
    rem = " ".join(f"{i}) {x}" for i, x in enumerate([x for x in (e.get("remediationJa") or []) if x is not None], 1))
    dc = e.get("dateConflict")
    return {
        "eventId": e["eventId"], "primaryNoticeId": e["primaryNoticeId"], "noticeIds": j(e["noticeIds"]),
        "relatedNoticeIds": j(e["relatedNoticeIds"]), "retireDateStart": e["retireDate"]["start"],
        "retireDateEnd": e["retireDate"]["end"], "datePrecision": e["retireDate"]["precision"], "status": e["status"],
        "daysRemaining": e["daysRemaining"], "impact": e["impact"], "severityScore": e["severityScore"],
        "urgencyScore": e["urgencyScore"], "impactType": e["impactType"], "workloadStop": e["flags"]["workloadStop"],
        "dataLossRisk": e["flags"]["dataLossRisk"], "autoMigration": e["flags"]["autoMigration"],
        "classificationStatus": e["classificationStatus"], "categories": j(e["categories"]), "categorySource": e["categorySource"],
        "products": j(e["products"]), "productSource": e["productSource"], "title": e["title"], "titleJa": e["titleJa"],
        "affectedScopeJa": e["affectedScopeJa"], "summaryJa": e["summaryJa"], "remediationJa": rem,
        "remediationStatus": e["remediationStatus"], "migrationTarget": e["migrationTarget"],
        "milestones": j([f"{m['labelJa']}:{m['date']}" for m in (e.get("milestones") or []) if m]),
        "dateConflict": "" if dc is None else "true" if dc is True else "false", "dateNoteJa": e["dateNoteJa"],
        "updateUrl": e["updateUrl"], "referenceUrls": j([l["url"] for l in (e.get("referenceLinks") or []) if l]),
    }


def cell_text(col: str, v: Any) -> str:
    s = "" if v is None else str(v)
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if col not in NUMERIC_COLS and s[:1] in ("=", "+", "-", "@", "\t", "\n"):
        s = "'" + s
    return s


def render_csv(f: dict) -> str:
    header = _template("retirements.csv").split("\n", 1)[0]
    cols = header.split(",")
    if list(csv_cells(_blank_event()).keys()) != cols:
        raise ToolError("CSV column map does not match the template header")
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    buf.write(header + "\r\n")
    for e in f["events"]:
        c = csv_cells(e)
        w.writerow([cell_text(k, c[k]) for k in cols])
    return buf.getvalue()


def _blank_event() -> dict:
    return {"eventId": "", "primaryNoticeId": "", "noticeIds": [], "relatedNoticeIds": [], "retireDate": {"start": None, "end": None, "precision": ""},
            "status": "", "daysRemaining": None, "impact": "", "severityScore": None, "urgencyScore": None, "impactType": "",
            "flags": {"workloadStop": "", "dataLossRisk": "", "autoMigration": ""}, "classificationStatus": "", "categories": [],
            "categorySource": "", "products": [], "productSource": "", "title": "", "titleJa": "", "affectedScopeJa": "",
            "summaryJa": "", "remediationJa": [], "remediationStatus": "", "migrationTarget": "", "milestones": [],
            "dateConflict": None, "dateNoteJa": "", "updateUrl": "", "referenceLinks": []}


# ---------------------------------------------------------------- G4

def _section_rows(h: str, frm: str, to: str) -> list[str]:
    sec = re.search(rf"<!-- SECTION: {frm} -->([\s\S]*?)<!-- SECTION: {to} -->", h)
    body = re.search(r"<tbody>([\s\S]*?)</tbody>", sec.group(1)) if sec else None
    if not body:
        return ["<missing>"]
    return ["\x1f".join(html.unescape(c) for c in re.findall(r"<td[^>]*>([\s\S]*?)</td>", r))
            for r in re.findall(r"<tr>([\s\S]*?)</tr>", body.group(1))]


def verify_report(run: Path) -> dict[str, str]:
    g: dict[str, str] = {}

    def gate(name: str, ok: bool, info: str = "") -> None:
        g[name] = "pass" if ok else f"fail: {info}"[:300]

    raw_f = (run / "findings.json").read_text(encoding="utf-8")
    f = json.loads(raw_f)
    h = (run / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")
    tp = _template("index.html")
    csv_bytes = (run / "retirements.csv").read_bytes()
    csv_text = csv_bytes.decode("utf-8-sig")
    marker = re.compile(r"\{\{[A-Z0-9_]+\}\}|<!-- BEGIN|<!-- END|_HERE -->|__ROWS_HERE__|__EVENTS_CHUNK__|__NOTICES_CHUNK__")
    # Data regions (island, CSV records) may legitimately contain token-like text; they are checked cell-exactly by 3c / 5d.
    h_static = ISLAND_RE.sub("", h)
    csv_head = csv_text.split("\n", 1)[0]
    gate("1 no token residue", not marker.search(h_static) and not marker.search(csv_head))
    miss = [s for s in SECTIONS if f"<!-- SECTION: {s} -->" not in h]
    gate("2 section anchors", not miss, ",".join(miss))
    im = ISLAND_RE.search(h)
    island = im.group(1) if im else ""
    gate("3a island has no raw <", bool(im) and "<" not in island)
    try:
        ev = json.loads(island)
    except ValueError:
        ev = None
    ids = [e["eventId"] for e in f["events"]]
    gate("3b island eventIds = findings.events", isinstance(ev, list) and [e.get("eventId") for e in ev] == ids)
    deep = isinstance(ev, list) and json.dumps(ev, ensure_ascii=False) == json.dumps(f["events"], ensure_ascii=False)
    gate("3c island = findings.events (deep, key order)", deep)
    sh, st_ = SCRIPT_RE.findall(h), SCRIPT_RE.findall(tp)
    gate("4a logic script unchanged", len(sh) == 1 and len(st_) == 1 and sh[0] == st_[0], f"scripts html={len(sh)} template={len(st_)}")
    csp_h, csp_t = CSP_RE.search(h), CSP_RE.search(tp)
    gate("4b CSP meta unchanged", bool(csp_h) and bool(csp_t) and csp_h.group(0) == csp_t.group(0))
    digest = base64.b64encode(hashlib.sha256(sh[0].encode("utf-8")).digest()).decode() if sh else ""
    gate("4c CSP hash matches the logic script", bool(csp_h) and f"'sha256-{digest}'" in csp_h.group(0))
    gate("5a csv BOM", csv_bytes[:3] == b"\xef\xbb\xbf")
    header = _template("retirements.csv").split("\n", 1)[0]
    gate("5b csv header", csv_text.split("\r\n", 1)[0].split("\n", 1)[0] == header)
    recs = list(csv.reader(io.StringIO(csv_text, newline="")))
    rows = recs[1:]
    gate("5c csv rows/eventIds = findings.events", [r[0] if r else "" for r in rows] == ids, f"csv={len(rows)} findings={len(ids)}")
    cols = header.split(",")
    diffs = []
    for i, (r, e) in enumerate(zip(rows, f["events"])):
        if len(r) != len(cols):
            diffs.append(f"events[{i}]: columns={len(r)}")
            continue
        c = csv_cells(e)
        diffs += [f"events[{i}].{k}" for n, k in enumerate(cols) if r[n].replace("\r\n", "\n") != cell_text(k, c[k])]
    gate("5d csv cells = findings.events", not diffs and len(rows) == len(ids), ", ".join(diffs[:5]))
    cards = re.findall(r'<div class="card[^"]*"><div class="n">([^<]*)</div><div class="l">', h)
    s = f["summary"]
    exp = [s[k] for k in ("eventCount", "highCount", "mediumCount", "lowCount", "needsReviewCount", "within90DaysCount", "retiredCount", "dateConflictCount")]
    gate("6a summary cards = findings.summary", cards == [str(x) for x in exp], ",".join(cards))
    exp_rows = lambda items, key: ["\x1f".join(str(x) for x in (it[key], it["total"], it["high"], it["medium"], it["low"], it["needsReview"])) for it in items] or [FALLBACK_TEXT]  # noqa: E731
    gate("6b category rows = findings.byCategory", _section_rows(h, "by-category", "by-quarter") == exp_rows(f["byCategory"], "category"))
    gate("6c quarter rows = findings.byQuarter", _section_rows(h, "by-quarter", "impact-rule") == exp_rows(f["byQuarter"], "quarter"))
    gate("6d status highlight", bool(s["statusHighlight"]) and f"<p>{html_escape(s['statusHighlight'])}</p>" in h)
    bad = []
    for name, text in (("index.html", h), ("retirements.csv", csv_text), ("findings.json", raw_f)):
        u = text + "\n" + deep_unescape(text)
        if EMAIL_RE.search(u):
            bad.append(f"{name}: email")
        if SAFELINKS_RE.search(u):
            bad.append(f"{name}: SafeLinks")
        if name != "findings.json" and PLACEHOLDER_RE.search(text):
            bad.append(f"{name}: placeholder")
    bad += [x for x in safety_findings(f) if x.startswith("7a")]
    gate("7a no email/safelinks/placeholder", not bad, " / ".join(bad[:3]))
    bad_url = [x for x in safety_findings(f) if x.startswith("7b")]
    if isinstance(ev, list):
        for i, e in enumerate(ev):
            for p, u in [("updateUrl", e.get("updateUrl"))] + [(f"referenceLinks[{j}].url", l.get("url")) for j, l in enumerate(e.get("referenceLinks") or [])]:
                if url_violation(u):
                    bad_url.append(f"island[{i}].{p} {url_violation(u)}")
    gate("7b all URLs pass the allowlist", not bad_url, " / ".join(bad_url[:5]))
    names = sorted(p.name for p in run.iterdir() if p.name != ".work")
    gate("8 folder contents", names == ["findings.json", "index.html", "progress.md", "retirements.csv"], ",".join(names))
    g3 = verify_findings(f)
    gate("G3 findings recomputation", not g3, " / ".join(g3[:3]))
    return g


def cmd_render(args: Any, run: Path) -> dict:
    from .progress import render_progress
    with RunLock(run):
        st = load_state(run)
        require_phase(st, ("highlighted", "rendered"), "render")
        f = read_json(run / "findings.json")
        pre = verify_findings(f)
        if pre:
            raise ToolError("findings.json failed G3 / safety checks; not rendering", code=1, failures=pre[:20])
        write_text(run, "index.html", render_html(f))
        write_text(run, "retirements.csv", render_csv(f), bom=True)
        gates = verify_report(run)
        ok = all(v == "pass" for v in gates.values())
        st["gates"]["G4"] = {"status": "pass" if ok else "fail", "gates": gates}
        st.pop("review", None)
        st["phase"] = "rendered"
        log(st, "render", f"index.html / retirements.csv を生成（G4 {'合格' if ok else '不合格'}）")
        save_state(run, st)
        write_text(run, "progress.md", render_progress(st))
    if not ok:
        raise ToolError("G4 failed", code=1, gates=gates)
    return {"run": st["runId"], "G4": gates, "indexHtml": str(run / "index.html"), "csv": str(run / "retirements.csv"),
            "next": "独立レビュー（index.html を読み直して findings.json と矛盾しないか確認）を行い、record-review で結果を記録する"}


def cmd_verify(args: Any, run: Path) -> dict:
    f = read_json(run / "findings.json")
    out: dict = {"run": run.name, "G3": verify_findings(f) or "pass"}
    if (run / "index.html").exists() and (run / "retirements.csv").exists():
        out["G4"] = verify_report(run)
    ok = out["G3"] == "pass" and all(v == "pass" for v in out.get("G4", {}).values())
    if not ok:
        raise ToolError("verification failed", code=1, **out)
    return out


def cmd_record_review(args: Any, run: Path) -> dict:
    from .progress import render_progress
    note = clean_text(args.note, 500)
    with RunLock(run):
        st = load_state(run)
        require_phase(st, ("rendered", "reviewed"), "record-review")
        if st["gates"].get("G4", {}).get("status") != "pass":
            raise ToolError("G4 has not passed; run render first")
        st["review"] = {"result": args.result, "note": note}
        st["phase"] = "reviewed" if args.result == "pass" else "rendered"
        log(st, "record-review", f"独立レビュー: {args.result}{'（' + note + '）' if note else ''}")
        save_state(run, st)
        write_text(run, "progress.md", render_progress(st))
    nxt = f"finalize --run {st['runId']}" if args.result == "pass" else "指摘を修正（必要なら merge / set-highlight / render をやり直す）してから再レビューする"
    return {"run": st["runId"], "review": st["review"], "next": nxt}


def cmd_finalize(args: Any, run: Path) -> dict:
    from .progress import render_progress
    with RunLock(run):
        st = load_state(run)
        require_phase(st, ("reviewed",), "finalize")
        if st.get("review", {}).get("result") != "pass":
            raise ToolError("independent review has not passed")
        gates = verify_report(run)
        if not all(v == "pass" for v in gates.values()):
            raise ToolError("G4 failed at finalize", code=1, gates=gates)
        f = read_json(run / "findings.json")
        work = run / ".work"
        real_work = os.path.realpath(work)
        if os.path.normcase(real_work) != os.path.normcase(os.path.join(os.path.realpath(run), ".work")):
            raise ToolError(".work is not inside the run folder")
        # Remove everything except state.json first: if this fails, the state stays `reviewed`, so finalize is retryable.
        try:
            for child in sorted(Path(real_work).iterdir()):
                if child.name == "state.json":
                    continue
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child)
                else:
                    child.unlink()
        except OSError as e:
            log(st, "finalize", f".work/ の削除に失敗（{type(e).__name__}）。state は reviewed のまま")
            save_state(run, st)
            write_text(run, "progress.md", render_progress(st))
            raise ToolError(f".work cleanup failed ({type(e).__name__}: {str(e)[:200]}); the run stays 'reviewed'",
                            next=f"ファイルを使用中のプロセスを閉じてから finalize --run {st['runId']} を再実行する")
        # Remove state.json before marking progress.md finalized, so a failure here leaves both at `reviewed`.
        try:
            os.remove(os.path.join(real_work, "state.json"))
        except OSError as e:
            raise ToolError(f"state.json removal failed ({type(e).__name__}: {str(e)[:200]}); the run stays 'reviewed'",
                            next=f"ファイルを使用中のプロセスを閉じてから finalize --run {st['runId']} を再実行する")
        st["phase"] = "finalized"
        log(st, "finalize", ".work/ を削除して完了")
        write_text(run, "progress.md", render_progress(st))
        try:
            os.rmdir(real_work)
        except OSError as e:
            raise ToolError(f".work cleanup failed ({type(e).__name__}: {str(e)[:200]})",
                            next=f"state は削除済みのため完了として扱われる（status --run {st['runId']} で確認できる）。"
                                 "空の .work フォルダが残っている場合は利用者に削除を依頼する")
    s = f["summary"]
    led = f["ledger"]
    return {"run": run.name, "reportFolder": str(run), "files": sorted(p.name for p in run.iterdir()),
            "summary": {k: s[k] for k in ("noticeCount", "eventCount", "highCount", "mediumCount", "lowCount", "needsReviewCount",
                                          "within90DaysCount", "retiredCount", "dateConflictCount")},
            "statusHighlight": s["statusHighlight"],
            "completeness": {"retirementsTotal": led["retirementsTotal"]["lastObserved"], "consistent": led["enumeration"]["consistent"],
                             "candidates": len(led["candidateNoticeIds"]), "failed": [x["id"] for x in led["failedNoticeIds"]],
                             "outOfScope": len(led["outOfScopeAfterExtraction"]), "merged": len(led["mergedEvents"])},
            "next": "完了報告: 上の要点（件数・High の主な対象・90 日以内・要確認・完全性）と index.html のパスを利用者に伝える"}
