"""Unit / end-to-end tests for the bundled 005 tool. Synthetic data only; network is faked.

Run from the repository root:
    python -m unittest discover -s usecases/005-azure-retirement-report/tools/tests -v
"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import os
import re
import shutil
import sys
import unittest
import urllib.parse
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS))

import retirement_tool  # noqa: E402
from retirement_lib import api, common, learn, merge, plan, progress, render, shards  # noqa: E402

AS_OF = "2026-10-07"
FIXED_NOW = dt.datetime(1999, 1, 1, 0, 0, 0, tzinfo=common.JST)


def avail(y, m):
    return [{"ring": "Retirement", "year": y, "month": m}]


def notice(i, title, products=("Azure Foo",), cats=("Compute",), av=None, modified="2026-01-01T00:00:00Z", desc=""):
    return {"id": str(i), "title": title, "products": list(products), "productCategories": list(cats),
            "availabilities": av if av is not None else avail(2027, "March"), "created": "2025-01-01T00:00:00Z",
            "modified": modified, "description": desc}


def dataset():
    d = []
    # 10 notices with the same normalized title (> 8 -> anchor + chunks). 100 is the newest (anchor).
    for k in range(10):
        d.append(notice(100 + k, ("Retirement: " if k % 2 else "Reminder: ") + "Foo v1 API",
                        modified=f"2026-0{9 - k if k < 9 else 1}-01T00:00:00Z" if k else "2026-09-30T00:00:00Z"))
    d.append(notice(200, "Retirement: Bar SKU", products=("Azure Bar",), cats=("Networking",)))
    d.append(notice(201, "Retirement: Baz feature", products=(), cats=(), av=[]))  # no availability, no product
    d.append(notice(202, "Retirement: Qux far future", products=("Azure Qux",), cats=("Storage",)))
    d.append(notice(203, "Retirement: Always failing", products=("Azure Bar",), cats=("Networking",)))
    d.append(notice(204, "Retirement: Old date but body says 2027", av=avail(2024, "May"), desc="<p>Now retiring on March 1, 2027</p>"))
    d.append(notice(205, "Retirement: Really old", av=avail(2023, "May"), desc="Retired in 2023."))
    d.append(notice("slug-notice-2026", "Retirement: Slug id notice", products=("Azure Bar",), cats=("Networking",)))
    return d


class FakeApi:
    def __init__(self, data):
        self.data = data
        self.calls = 0
        self.body_failures: set[str] = set()
        self.down = False

    def __call__(self, url):
        self.calls += 1
        if self.down:
            raise common.ToolError("Release Communications API GET failed: test outage", code=3)
        p = urllib.parse.urlsplit(url)
        assert p.scheme == "https" and p.hostname == api.API_HOST
        if p.path != api.API_PATH:  # single notice: /azure/<id>
            nid = urllib.parse.unquote(p.path.rsplit("/", 1)[1])
            if nid in self.body_failures:
                raise common.ToolError("Release Communications API GET failed: test", code=3)
            return dict(next(r for r in self.data if r["id"] == nid))
        q = dict(urllib.parse.parse_qsl(p.query))
        flt = q["$filter"]
        m = re.search(r"year ge (\d{4})", flt)
        y = int(m.group(1)) if m else None
        rows = self.data
        if y is not None and "not availabilities/any(a:a/year ge" in flt:
            rows = [r for r in rows if r["availabilities"] and not any(a["year"] >= y for a in r["availabilities"])]
        elif y is not None:
            rows = [r for r in rows if not r["availabilities"] or any(a["year"] >= y for a in r["availabilities"])]
        rows = sorted(rows, key=lambda r: r["id"])
        skip, top = int(q.get("$skip", 0)), int(q.get("$top", 100))
        sel = q.get("$select", "id").split(",")
        out = {"value": [{k: r[k] for k in sel} for r in rows[skip:skip + top]]}
        if q.get("$count") == "true":
            out["@odata.count"] = len(rows)
        return out


def ev(key, start, prec="day", flags=("unknown", "unknown", "unknown"), same=None, **kw):
    e = {"eventKey": key, "affectedScopeJa": kw.get("scope", "v1"),
         "retireDate": {"precision": prec, "start": start, "end": start, "source": "description", "evidence": "Retiring."},
         "dateConflict": False, "dateNoteJa": "", "milestones": [], "impactType": "VersionRetirement",
         "flags": dict(zip(("workloadStop", "dataLossRisk", "autoMigration"), flags)),
         "flagEvidence": {k: ("" if v == "unknown" else "Stated in the notice.")
                          for k, v in zip(("workloadStop", "dataLossRisk", "autoMigration"), flags)},
         "classificationStatus": kw.get("cls", "confirmed"), "summaryJa": kw.get("summary", "v1 が廃止される。"),
         "remediationJa": kw.get("rem", ["v2 へ移行する"]), "remediationStatus": "explicit", "migrationTarget": "v2",
         "referenceLinks": kw.get("links", [{"titleJa": "Docs", "url": "https://learn.microsoft.com/azure/foo", "source": "Description", "learnQuery": ""}]),
         "sameEventAs": same}
    return e


class DroppingComplementApi(FakeApi):
    """Drops complement rows from description listings: `drops` holds the id to omit per listing attempt."""

    def __init__(self, data, drops):
        super().__init__(data)
        self.drops = list(drops)
        self.listings = 0

    def __call__(self, url):
        out = super().__call__(url)
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if "not availabilities/any(a:a/year ge" in q["$filter"] and "description" in q.get("$select", ""):
            drop = self.drops[min(self.listings, len(self.drops) - 1)]
            self.listings += 1
            out["value"] = [v for v in out["value"] if v["id"] != drop]
        return out


class Pipeline(unittest.TestCase):
    run_names: list[str] = []

    def setUp(self):
        self.fake = FakeApi(dataset())
        self._orig_http, self._orig_now = api.http_get_json, api.now_jst
        api.http_get_json = self.fake
        api.now_jst = lambda: FIXED_NOW
        self.created: list[Path] = []

    def tearDown(self):
        api.http_get_json, api.now_jst = self._orig_http, self._orig_now
        for d in self.created:
            shutil.rmtree(d, ignore_errors=True)
            (d.parent / f".{d.name}.lock").unlink(missing_ok=True)

    def tool(self, *argv, expect=0):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = retirement_tool.main(list(argv))
        out = json.loads(buf.getvalue())
        self.assertEqual(code, expect, out)
        return out

    def highlight(self, run, text, expect=0):
        (run / common.HIGHLIGHT_INPUT).write_text(text, encoding="utf-8")
        return self.tool("set-highlight", "--run", run.name, expect=expect)

    def init(self, scope="next12Months", mrc="available"):
        out = self.tool("init", "--scope", scope, "--as-of", AS_OF, "--mrc-mcp", mrc)
        run = common.reports_root() / out["run"]
        self.created.append(run)
        return out["run"], run

    def simulate(self, run, spec, learn="notUsed", incomplete=False):
        """spec(nid, attempt, inp) -> notice dict | None (fetch failure) | 'raw' (to write raw shard text)."""
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        for b in st["batches"]:
            if b["status"] != "dispatched":
                continue
            inp = json.loads((run / b["inputPath"]).read_text(encoding="utf-8"))
            ids = [n["id"] for n in inp["notices"]]
            ret, fail, notices = [], [], []
            for nid in ids:
                n = spec(nid, inp["attempt"], inp)
                if n is None:
                    fail.append({"id": nid, "reason": "fetchFailed: test"})
                else:
                    ret.append(nid)
                    notices.append(n)
            shard = {"batchId": b["batchId"], "attempt": inp["attempt"], "asOfDate": inp["asOfDate"],
                     "learnMcp": learn(b["batchId"]) if callable(learn) else learn,
                     "learnIncomplete": incomplete(b["batchId"]) if callable(incomplete) else incomplete,
                     "expectedNoticeIds": ids, "returnedNoticeIds": ret, "failedNoticeIds": fail, "notices": notices}
            Path(inp["shardPath"]).write_text(json.dumps(shard, ensure_ascii=False), encoding="utf-8")

    def drive(self, run_name, run, spec, max_waves=20, learn="notUsed", incomplete=False):
        for _ in range(max_waves):
            w = self.tool("next-wave", "--run", run_name)
            if not w["dispatch"]:
                break
            self.simulate(run, spec, learn=learn, incomplete=incomplete)
            c = self.tool("check-shards", "--run", run_name)
            if c.get("G2"):
                return c
        self.fail("did not reach G2")

    # ------------------------------------------------------------------ full flow

    def test_full_pipeline(self):
        name, run = self.init()
        e = self.tool("enumerate", "--run", name)
        self.assertTrue(e["consistent"])
        self.assertEqual(e["prefilter"]["screenStatus"], "done")
        self.assertEqual(e["prefilter"]["bodyYearMatchedNoticeIds"], 1)  # 204 kept, 205 excluded
        self.assertEqual(e["candidateCount"], 16)
        self.tool("plan-batches", "--run", name, expect=2)  # same-target decision is mandatory
        self.tool("record-same-target", "--run", name, "--pairs", "200,slug-notice-2026")
        p = self.tool("plan-batches", "--run", name)
        self.assertEqual(p["G1"]["status"], "pass")
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        g_big = next(g for g in st["groups"] if len(g["noticeIds"]) == 10)
        self.assertEqual(g_big["anchorNoticeId"], "100")
        self.assertEqual(len(g_big["batchIds"]), 2)
        owner, chunk = [next(b for b in st["batches"] if b["batchId"] == x) for x in g_big["batchIds"]]
        self.assertIn("100", owner["noticeIds"])
        self.assertEqual(chunk["waitFor"], owner["batchId"])
        self.assertTrue(all(len(b["noticeIds"]) + (1 if b["refGroupId"] else 0) <= 8 for b in st["batches"]))

        evil = '</script><script>alert(1)</script>{{EVENT_COUNT}} {{RETIREMENT_ROWS}} <!-- END CATEGORY_ROWS -->'

        def spec(nid, attempt, inp):
            if nid == "203":
                return None  # always fails -> exhausted after 3 attempts
            if nid == "100" and attempt == 1:
                return None  # anchor fails first -> replacement for the chunk batch
            base = {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": f"タイトル {nid}",
                    "inferredProducts": [], "inferredCategories": [], "events": []}
            if nid == "100":
                refs = inp["referenceNotices"]
                same = {"noticeId": refs[0]["id"], "eventKey": refs[0]["events"][0]["eventKey"], "evidence": "Update of the same retirement."} if refs else None
                base["events"] = [ev("100-1", "2027-03-31", flags=("true", "unknown", "unknown"), same=same), ev("100-2", "2030-01-01")]
            elif nid.startswith("10"):
                refs = [r for r in inp["referenceNotices"]]
                target = None
                if refs:
                    target = {"noticeId": refs[0]["id"], "eventKey": refs[0]["events"][0]["eventKey"], "evidence": "Reminder of the same retirement."}
                elif nid != "101":
                    target = {"noticeId": "101", "eventKey": "101", "evidence": "Same retirement."} if "101" in [n["id"] for n in inp["notices"]] else None
                base["events"] = [ev(nid, "2027-03-31", flags=("false", "unknown", "unknown"), same=target)]
            elif nid == "200":
                base["titleJa"] = "=cmd|' /C calc'!A0"
                base["events"] = [ev(nid, "2026-11-15", flags=("unknown", "true", "unknown"), summary=evil + " contact foo@example.com",
                                     links=[{"titleJa": "x", "url": "https://evilmicrosoft.com/a"},
                                            {"titleJa": "sl", "url": "https://nam06.safelinks.protection.outlook.com/?url=https%3A%2F%2Flearn.microsoft.com%2Fx&data=abc"},
                                            {"titleJa": "gh", "url": "https://github.com/Azure/foo"},
                                            {"titleJa": "bad", "url": "https://github.com/someone/foo"}])]
            elif nid == "201":
                base["inferredCategories"] = ["Networking", "NotAllowed"]
                base["inferredProducts"] = ["Azure Baz"]
                base["events"] = [ev(nid, None, prec="unknown")]
            elif nid == "202":
                base["events"] = [ev(nid, "2031-01-01")]  # outside the window
            elif nid == "slug-notice-2026":
                base["events"] = [ev(nid, "2026-10", prec="month", flags=("unknown", "unknown", "true"))]
            else:
                base["events"] = [ev(nid, "2027-03-01", cls="insufficientEvidence")]
            return base

        c = self.drive(name, run, spec)
        self.assertEqual(c["G2"]["status"], "pass")
        self.assertEqual(c["G2"]["failed"], ["203"])
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(st["noticeStatus"]["203"]["attempts"], 3)
        chunk = next(b for b in st["batches"] if b["batchId"] == chunk["batchId"])
        self.assertTrue(chunk["referenceNoticeIds"] and chunk["referenceNoticeIds"][0] != "100")  # anchor replaced

        m = self.tool("merge", "--run", name)
        f = json.loads((run / "findings.json").read_text(encoding="utf-8"))
        ids = [x["eventId"] for x in f["events"]]
        self.assertIn("slug-notice-2026", ids)  # month precision, currentMonth
        cur = next(x for x in f["events"] if x["eventId"] == "slug-notice-2026")
        self.assertEqual((cur["status"], cur["impact"]), ("currentMonth", "Medium"))  # S1 x U3
        self.assertNotIn("202", ids)
        self.assertTrue(any(o["id"] == "202" for o in f["ledger"]["outOfScopeAfterExtraction"]))
        self.assertTrue(any(o["eventKey"] == "100-2" for o in f["ledger"]["outOfScopeAfterExtraction"]))
        big = [x for x in f["events"] if set(x["noticeIds"]) & {str(i) for i in range(100, 110)}]
        self.assertEqual(len(big), 1, [x["noticeIds"] for x in big])  # all ten merged across batches into one event
        self.assertEqual(big[0]["eventId"], "100-1")
        self.assertEqual(big[0]["flags"]["workloadStop"], "true")
        self.assertEqual(big[0]["classificationStatus"], "ambiguous")  # true/false conflict
        self.assertEqual(sorted(big[0]["noticeIds"], key=common.id_key), [str(i) for i in range(100, 110)])
        e200 = next(x for x in f["events"] if x["eventId"] == "200")
        self.assertNotIn("@", e200["summaryJa"])
        self.assertEqual([l["url"] for l in e200["referenceLinks"]], ["https://learn.microsoft.com/x", "https://github.com/Azure/foo"])
        self.assertEqual(e200["relatedNoticeIds"], ["slug-notice-2026"])
        e201 = next(x for x in f["events"] if x["eventId"] == "201")
        self.assertEqual((e201["impact"], e201["categories"], e201["categorySource"], e201["productSource"]),
                         ("NeedsReview", ["Networking"], "inferred", "inferred"))
        self.assertEqual(f["ledger"]["failedNoticeIds"], [{"id": "203", "reason": "retriesExhausted", "attempts": 3}])
        self.assertEqual([p_["status"] for p_ in f["collectionPlan"]][1], "downgraded")
        self.assertEqual(m["summary"]["eventCount"], len(f["events"]))

        self.tool("render", "--run", name, expect=2)  # highlight required first
        self.tool("set-highlight", "--run", name, expect=2)  # input file missing
        self.highlight(run, "短い", expect=2)
        self.assertTrue((run / common.HIGHLIGHT_INPUT).exists())  # kept for rewriting after a rejection
        self.highlight(run, "テスト用の総評です。High の件数と 90 日以内の件数を確認してください。")
        self.assertFalse((run / common.HIGHLIGHT_INPUT).exists())  # consumed
        r = self.tool("render", "--run", name)
        self.assertTrue(all(v == "pass" for v in r["G4"].values()), r["G4"])
        h = (run / "index.html").read_text(encoding="utf-8")
        island = re.search(r'id="retirement-data">([\s\S]*?)</script>', h).group(1)
        self.assertNotIn("<", island)
        self.assertEqual(h.count("<script>"), 1)
        csv_text = (run / "retirements.csv").read_bytes()
        self.assertTrue(csv_text.startswith(b"\xef\xbb\xbf"))
        self.assertIn("'=cmd", csv_text.decode("utf-8-sig"))

        self.tool("finalize", "--run", name, expect=2)  # review required
        self.tool("record-review", "--run", name, "--result", "pass")
        fin = self.tool("finalize", "--run", name)
        self.assertEqual(fin["files"], ["findings.json", "index.html", "progress.md", "retirements.csv"])
        self.assertFalse((run / ".work").exists())

    def test_fallback_all_unions_complement_attempts(self):
        api.http_get_json = DroppingComplementApi(dataset(), ["204", "205"])  # each attempt misses a different row
        name, run = self.init()
        e = self.tool("enumerate", "--run", name)
        self.assertTrue(e["consistent"])
        self.assertEqual((e["prefilter"]["screenStatus"], e["prefilter"]["screenedCount"]), ("fallbackAll", 2))
        self.assertEqual(e["candidateCount"], 17)  # 15 in scope + both complement rows
        self.tool("record-same-target", "--run", name, "--none")
        self.assertEqual(self.tool("plan-batches", "--run", name)["G1"]["status"], "pass")

    def test_fallback_all_incomplete_complement_is_inconsistent(self):
        api.http_get_json = DroppingComplementApi(dataset(), ["205"])  # the same row is missed every time
        name, run = self.init()
        e = self.tool("enumerate", "--run", name)
        self.assertFalse(e["consistent"])
        self.assertEqual((e["prefilter"]["screenStatus"], e["prefilter"]["screenedCount"]), ("fallbackAll", 1))
        self.tool("record-same-target", "--run", name, "--none")
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        st["enumeration"]["enumeration"]["consistent"] = True  # a consistent=true claim must not hide the gap
        self.assertTrue(any("prefilter" in f for f in plan.check_g1(dict(st, batches=[], groups=[]))))
        g1 = self.tool("plan-batches", "--run", name)["G1"]
        self.assertEqual(g1["status"], "pass")  # recorded (soft) failure: continues, shown in the report
        self.assertTrue(any("consistent=false" in d for d in g1["details"]))

    def _plan_big_group(self):
        name, run = self.init()
        self.tool("enumerate", "--run", name)
        self.tool("record-same-target", "--run", name, "--none")
        self.tool("plan-batches", "--run", name)
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        g = next(x for x in st["groups"] if len(x["noticeIds"]) == 10)
        owner, chunk = [next(b for b in st["batches"] if b["batchId"] == x) for x in g["batchIds"]]
        return name, run, set(owner["noticeIds"]), chunk["batchId"]

    def _wave_trace(self, name, run, fails):
        waves = []
        for _ in range(20):
            w = self.tool("next-wave", "--run", name)
            if not w["dispatch"]:
                break
            waves.append({d["batchId"]: d["referenceNoticeIds"] for d in w["dispatch"]})
            self.simulate(run, lambda nid, attempt, inp: None if fails(nid, attempt) else
                          {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": "x", "events": [ev(nid, "2027-03-31")]})
            if self.tool("check-shards", "--run", name).get("G2"):
                return waves
        self.fail("did not reach G2")

    def test_chunk_waits_for_owner_retry_after_whole_batch_failure(self):
        name, run, owner_ids, chunk_id = self._plan_big_group()
        waves = self._wave_trace(name, run, lambda nid, attempt: nid in owner_ids and attempt == 1)
        chunk_wave = next(i for i, w in enumerate(waves) if chunk_id in w)
        retry_wave = next(i for i, w in enumerate(waves) if any(b.endswith("-r2") for b in w))
        self.assertGreater(chunk_wave, retry_wave)  # not dispatched alongside the owner retry
        self.assertTrue(waves[chunk_wave][chunk_id])  # a returned group member is used as the reference

    def test_chunk_runs_without_reference_when_owner_exhausted(self):
        name, run, owner_ids, chunk_id = self._plan_big_group()
        waves = self._wave_trace(name, run, lambda nid, attempt: nid in owner_ids)
        chunk_wave = next(i for i, w in enumerate(waves) if chunk_id in w)
        self.assertEqual(waves[chunk_wave][chunk_id], [])
        self.assertTrue(any(b.endswith("-r3") for w in waves[:chunk_wave] for b in w))

    def test_malformed_shards_are_retried(self):
        name, run = self.init(scope="all")
        self.tool("enumerate", "--run", name)
        self.tool("record-same-target", "--run", name, "--none")
        self.tool("plan-batches", "--run", name)
        w = self.tool("next-wave", "--run", name)
        first = w["dispatch"][0]
        Path(first["shardPath"]).write_text("{not json", encoding="utf-8")
        for d in w["dispatch"][1:]:
            inp = json.loads(Path(d["inputPath"]).read_text(encoding="utf-8"))
            ids = [n["id"] for n in inp["notices"]]
            bad = {"id": ids[0], "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": "x", "events": [dict(ev(ids[0], "2027-01-01"), impactType="Nope")]}
            good = [{"id": i, "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": "x", "events": [ev(i, "2027-01-01")]} for i in ids[1:]]
            Path(d["shardPath"]).write_text(json.dumps({"batchId": d["batchId"], "attempt": 1, "learnMcp": "notUsed", "expectedNoticeIds": ids,
                                                        "returnedNoticeIds": ids, "failedNoticeIds": [], "notices": [bad] + good}), encoding="utf-8")
        c = self.tool("check-shards", "--run", name)
        self.assertTrue(c["retryBatches"])
        statuses = {x["batchId"]: x for x in c["checked"]}
        self.assertEqual(statuses[first["batchId"]]["status"], "failed")
        self.assertTrue(all("malformedShard" in v for v in statuses[first["batchId"]]["failed"].values()))
        st = self.tool("status", "--run", name)
        self.assertIn("next-wave", st["next"])


    def _plan_all(self, mrc="available"):
        name, run = self.init(scope="all", mrc=mrc)
        self.tool("enumerate", "--run", name)
        self.tool("record-same-target", "--run", name, "--none")
        self.tool("plan-batches", "--run", name)
        return name, run

    def test_mrc_unavailable_prefetches_bodies_with_the_reviewed_client(self):
        self.fake.body_failures = {"203"}
        name, run = self._plan_all(mrc="unavailable")
        w = self.tool("next-wave", "--run", name)
        self.assertTrue(all("ReleaseCommunicationsApi" in d["workerPrompt"] for d in w["dispatch"]))
        bodies = {}
        for d in w["dispatch"]:
            inp = json.loads(Path(d["inputPath"]).read_text(encoding="utf-8"))
            self.assertEqual(inp["bodySource"], "ReleaseCommunicationsApi")
            bodies.update({n["id"]: n["body"] for n in inp["notices"]})
        self.assertIn("March 1, 2027", bodies["204"]["bodyText"])
        self.assertNotIn("<p>", bodies["204"]["bodyText"])
        self.assertIn("fetchError", bodies["203"])

        def spec(nid, attempt, inp):
            body = next(n["body"] for n in inp["notices"] if n["id"] == nid)
            if "fetchError" in body:
                return None
            return {"id": nid, "fetchStatus": "ok", "fetchedVia": "ReleaseCommunicationsApi", "titleJa": "x",
                    "events": [ev(nid, "2027-01-01")]}
        self.simulate(run, spec)
        self.tool("check-shards", "--run", name)
        self.assertEqual(self.drive(name, run, spec)["G2"]["failed"], ["203"])

    def test_mrc_unavailable_enforces_dispatch_provenance(self):
        self.fake.body_failures = {"203"}
        name, run = self._plan_all(mrc="unavailable")
        self.tool("next-wave", "--run", name)
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        b203 = next(b for b in st["batches"] if "203" in b["noticeIds"])
        self.assertEqual(b203["bodySource"], "ReleaseCommunicationsApi")
        self.assertEqual(b203["prefetchFailedNoticeIds"], ["203"])
        # Worker ignores body.fetchError for 203 and claims MRC MCP for 204; both must be rejected.
        self.simulate(run, lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok",
                                                       "fetchedVia": "MRC MCP" if nid == "204" else "ReleaseCommunicationsApi",
                                                       "titleJa": "x", "events": [ev(nid, "2027-01-01")]})
        c = self.tool("check-shards", "--run", name)
        failed = {k: v for r in c["checked"] for k, v in r["failed"].items()}
        self.assertTrue(failed["203"].startswith("fetchFailed"))
        self.assertIn("fetchedVia", failed["204"])
        self.assertEqual(set(failed), {"203", "204"})
        # Retries: the body for 203 can now be fetched, so it is accepted on redispatch.
        self.fake.body_failures = set()
        g2 = self.drive(name, run, lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok", "fetchedVia": "ReleaseCommunicationsApi",
                                                              "titleJa": "x", "events": [ev(nid, "2027-01-01")]})
        self.assertEqual(g2["G2"]["failed"], [])

    def test_missing_dispatch_provenance_fails_closed(self):
        name, run = self._plan_all(mrc="unavailable")
        self.tool("next-wave", "--run", name)
        sp = run / ".work" / "state.json"
        st = json.loads(sp.read_text(encoding="utf-8"))
        b = next(x for x in st["batches"] if x["status"] == "dispatched")
        del b["bodySource"]
        sp.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        self.simulate(run, lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok", "fetchedVia": "ReleaseCommunicationsApi",
                                                       "titleJa": "x", "events": [ev(nid, "2027-01-01")]})
        c = self.tool("check-shards", "--run", name)
        r = next(x for x in c["checked"] if x["batchId"] == b["batchId"])
        self.assertTrue(r["failed"] and all(v.startswith("malformedInput") for v in r["failed"].values()))

    def test_malformed_dispatch_provenance_never_crashes(self):
        ids = ["a", "b", "c", "d"]
        st = {"groups": [], "enumeration": {"allowedCategories": ["Uncategorized"]}, "capabilities": {"mrcMcp": "不可"}}
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / ".work").mkdir()
            (tmp / ".work" / "s.json").write_text(json.dumps({"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": [],
                                                               "failedNoticeIds": [{"id": i} for i in ids], "notices": []}), encoding="utf-8")
            meta = {i: {"id": i, "title": i} for i in ids}
            for pf in ([["a"]], ["zz"], ["a", "a"], None, "a"):
                b = {"batchId": "B01", "noticeIds": ids, "shardPath": ".work/s.json", "bodySource": "ReleaseCommunicationsApi",
                     "prefetchFailedNoticeIds": pf}
                ok, fail, _, _, _ = shards.check_batch(tmp, st, b, meta, {})
                self.assertEqual(ok, {})
                self.assertTrue(all(v.startswith("malformedInput") for v in fail.values()), pf)
            b = {"batchId": "B01", "noticeIds": ids, "shardPath": ".work/s.json", "bodySource": "MRC MCP", "prefetchFailedNoticeIds": ["a"]}
            ok, fail, _, _, _ = shards.check_batch(tmp, dict(st, capabilities={"mrcMcp": "利用可"}), b, meta, {})
            self.assertTrue(all(v.startswith("malformedInput") for v in fail.values()))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_body_prefetch_outage_leaves_state_unchanged(self):
        name, run = self._plan_all(mrc="unavailable")
        self.fake.down = True
        before = (run / ".work" / "state.json").read_text(encoding="utf-8")
        self.tool("next-wave", "--run", name, expect=3)
        self.assertEqual((run / ".work" / "state.json").read_text(encoding="utf-8"), before)
        self.assertIn("next-wave", self.tool("status", "--run", name)["next"])

    def test_mrc_available_does_not_fetch_bodies(self):
        name, run = self._plan_all()
        calls = self.fake.calls
        w = self.tool("next-wave", "--run", name)
        self.assertEqual(self.fake.calls, calls)
        inp = json.loads(Path(w["dispatch"][0]["inputPath"]).read_text(encoding="utf-8"))
        self.assertTrue(all("body" not in n for n in inp["notices"]))

    def _to_reviewed(self):
        name, run = self._plan_all()
        self.drive(name, run, lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP",
                                                          "titleJa": "x", "events": [ev(nid, "2027-01-01")]})
        self.tool("merge", "--run", name)
        self.highlight(run, "テスト用の総評です。High の件数と 90 日以内の件数を確認してください。")
        self.tool("render", "--run", name)
        self.tool("record-review", "--run", name, "--result", "pass")
        return name, run

    def test_finalize_cleanup_failure_is_retryable(self):
        name, run = self._to_reviewed()
        orig = render.shutil.rmtree

        def boom(*a, **k):
            raise PermissionError("locked")
        render.shutil.rmtree = boom
        try:
            out = self.tool("finalize", "--run", name, expect=2)
        finally:
            render.shutil.rmtree = orig
        self.assertIn("finalize", out["next"])
        self.assertEqual(self.tool("status", "--run", name)["phase"], "reviewed")
        orig_rm = render.os.remove
        render.os.remove = boom
        try:
            self.tool("finalize", "--run", name, expect=2)
        finally:
            render.os.remove = orig_rm
        self.assertEqual(self.tool("status", "--run", name)["phase"], "reviewed")
        self.assertIn("現在地: reviewed", (run / "progress.md").read_text(encoding="utf-8"))
        fin = self.tool("finalize", "--run", name)
        self.assertEqual(fin["files"], ["findings.json", "index.html", "progress.md", "retirements.csv"])
        self.assertEqual(self.tool("status", "--run", name)["phase"], "finalized")

    def test_free_text_is_read_from_run_files_not_argv(self):
        name, run = self._plan_all()
        self.drive(name, run, lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP",
                                                          "titleJa": "x", "events": [ev(nid, "2027-01-01")]})
        self.tool("merge", "--run", name)
        self.tool("set-highlight", "--run", name, "--text", "x", expect=2)  # no command-line free text
        shell_like = 'High は 3 件です。"; $(touch pwned) `id` を含む文字列もそのまま記録される。'
        out = self.highlight(run, shell_like)
        self.assertEqual(out["statusHighlight"], shell_like)
        self.tool("render", "--run", name)
        self.tool("record-review", "--run", name, "--result", "fail", "--note", "x", expect=2)
        (run / common.REVIEW_NOTE_INPUT).write_text("総評と件数が一致しない。\n再確認する。", encoding="utf-8")
        out = self.tool("record-review", "--run", name, "--result", "fail")
        self.assertEqual(out["review"]["note"], "総評と件数が一致しない。 再確認する。")
        self.assertFalse((run / common.REVIEW_NOTE_INPUT).exists())
        out = self.tool("record-review", "--run", name, "--result", "pass")
        self.assertEqual(out["review"]["note"], "")  # a consumed note is never reused
        (run / common.REVIEW_NOTE_INPUT).write_bytes(b"x" * (common.MAX_INPUT_BYTES + 1))
        self.tool("record-review", "--run", name, "--result", "pass", expect=2)
        (run / common.REVIEW_NOTE_INPUT).unlink()
        if hasattr(os, "symlink"):
            outside = run.parent / f".{name}-outside.txt"
            outside.write_text("外部ファイルの内容を総評として読ませない。十分な長さの文字列。", encoding="utf-8")
            try:
                try:
                    os.symlink(outside, run / common.HIGHLIGHT_INPUT)
                except OSError:
                    return
                self.tool("set-highlight", "--run", name, expect=2)
            finally:
                outside.unlink(missing_ok=True)

    def test_status_when_only_an_empty_work_dir_remains(self):
        name, run = self._to_reviewed()
        self.tool("finalize", "--run", name)
        (run / ".work").mkdir()  # e.g. the final rmdir failed after state.json was removed
        self.assertEqual(self.tool("status", "--run", name)["phase"], "finalized")
        self.assertIn("finalized", (run / "progress.md").read_text(encoding="utf-8"))

    def test_init_picks_next_suffix_when_folder_is_created_concurrently(self):
        root = common.reports_root()
        root.mkdir(parents=True, exist_ok=True)
        base = FIXED_NOW.strftime("%Y%m%d-%H%M%S")
        taken = [p for p in (root / base, *(root / f"{base}-{i}" for i in range(2, 50))) if p.exists()]
        orig_mkdir, raced = Path.mkdir, []

        def racing_mkdir(p, *a, **kw):
            if p.parent == root and not raced and not p.exists():
                orig_mkdir(p)  # another init wins the race between the name choice and mkdir
                raced.append(p)
                self.created.append(p)
            return orig_mkdir(p, *a, **kw)

        Path.mkdir = racing_mkdir
        try:
            name, run = self.init()
        finally:
            Path.mkdir = orig_mkdir
        self.assertEqual(len(raced), 1)
        self.assertNotEqual(run, raced[0])
        self.assertNotIn(run, taken)
        self.assertTrue((run / ".work" / "state.json").is_file())

    def test_usage_errors_are_json(self):
        for argv in (["init", "--scope", "next12Months"], ["init", "--scope", "bogus", "--mrc-mcp", "available"],
                     ["next-wave", "--run", "x", "--max", "many"], ["no-such-command"], []):
            out = self.tool(*argv, expect=2)
            self.assertFalse(out["ok"])
            self.assertTrue(out["error"])
            self.assertIn("next", out)
            self.assertIn("usage", out)

    # ------------------------------------------------------------------ PR #56 review (API-only boundary etc.)

    def _api_wave(self):
        name, run = self._plan_all(mrc="unavailable")
        w = self.tool("next-wave", "--run", name)
        d = next(x for x in w["dispatch"] if any(n["id"] == "204" for n in json.loads(Path(x["inputPath"]).read_text(encoding="utf-8"))["notices"]))
        return name, run, w, d

    def test_offline_worker_profile_and_collection_plan(self):
        name, run, w, _ = self._api_wave()
        self.assertTrue(all(d["workerAgent"] == "azure-retirement-summarizer-offline" for d in w["dispatch"]))
        f = json.loads((run / "findings.json").read_text(encoding="utf-8"))
        detail = next(p for p in f["collectionPlan"] if p["task"] == "Detail:fetchAndExtract")
        self.assertIn("公開 API", detail["evidence"]["query"])
        self.assertNotIn("get_azure_update_by_id", detail["evidence"]["query"])
        name2, _ = self._plan_all()
        w2 = self.tool("next-wave", "--run", name2)
        self.assertTrue(all(d["workerAgent"] == "azure-retirement-summarizer" for d in w2["dispatch"]))

    def test_api_mode_enforces_body_provenance(self):
        name, run, w, d = self._api_wave()

        def spec(nid, attempt, inp):
            e = ev(nid, "2027-03-01", flags=("true", "unknown", "false"))
            e["retireDate"]["evidence"] = "Now retiring on March 1, 2027" if nid == "204" else "Invented sentence not in the body."
            e["flagEvidence"]["workloadStop"] = "now retiring on MARCH 1, 2027"  # case / punctuation insensitive
            e["flagEvidence"]["autoMigration"] = "Fabricated evidence text."
            e["referenceLinks"] = [{"titleJa": "x", "url": "https://learn.microsoft.com/azure/foo", "source": "Description"},
                                   {"titleJa": "y", "url": "https://learn.microsoft.com/azure/bar", "source": "LearnSearch"}]
            e["remediationStatus"] = "supplementedByLearn"
            return {"id": nid, "fetchStatus": "ok", "fetchedVia": "ReleaseCommunicationsApi", "titleJa": "x", "events": [e]}
        self.simulate(run, spec)
        shard = Path(d["shardPath"])
        sh = json.loads(shard.read_text(encoding="utf-8"))
        sh["learnMcp"] = "available"
        shard.write_text(json.dumps(sh), encoding="utf-8")
        self.tool("check-shards", "--run", name)
        acc = json.loads((run / ".work" / "accepted.json").read_text(encoding="utf-8"))
        e204 = acc["204"]["events"][0]
        self.assertEqual((e204["retireDate"]["precision"], e204["retireDate"]["start"]), ("day", "2027-03-01"))
        self.assertEqual(e204["flags"], {"workloadStop": "true", "dataLossRisk": "unknown", "autoMigration": "unknown"})
        self.assertEqual(e204["referenceLinks"], [])
        self.assertEqual((e204["remediationStatus"], e204["remediationJa"]), ("notFound", []))
        other = next(v for k, v in acc.items() if k != "204")["events"][0]
        self.assertEqual(other["retireDate"]["precision"], "unknown")
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(all(b["learnMcp"] in (None, "notUsed") for b in st["batches"]))

    def _learn_fake(self, responses):
        """responses(query, n) -> dict | LearnHttpError; records calls and waits."""
        calls, waits = [], []

        def fake(url):
            p = urllib.parse.urlsplit(url)
            assert p.scheme == "https" and p.hostname == learn.LEARN_HOST and p.path == learn.LEARN_SEARCH_PATH
            q = dict(urllib.parse.parse_qsl(p.query))["search"]
            calls.append(q)
            r = responses(q, sum(1 for c in calls if c == q))
            if isinstance(r, Exception):
                raise r
            return r
        orig = (learn.http_get_learn, learn.sleep)
        learn.http_get_learn, learn.sleep = fake, waits.append
        self.addCleanup(lambda: setattr(learn, "http_get_learn", orig[0]) or setattr(learn, "sleep", orig[1]))
        return calls, waits

    def _drive_with_requests(self, learn_v="unavailable"):
        name, run = self._plan_all()

        def spec(nid, attempt, inp):
            e = ev(nid, "2027-01-01", links=[])
            e["remediationStatus"], e["remediationJa"] = "notFound", []
            e["learnRequest"] = {"query": "Azure Foo v1 retirement migration" if nid.startswith("10") else f"Azure Bar {nid} retirement",
                                 "keyTerms": ["Foo"] if nid.startswith("10") else ["Bar"]}
            return {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": "x", "events": [e]}
        c = self.drive(name, run, spec, learn=learn_v)
        return name, run, c

    def test_learn_fallback_is_served_serially_by_the_tool(self):
        good = {"results": [
            {"title": "Migrate from Foo v1 before retirement", "url": "https://learn.microsoft.com/azure/foo/migrate", "description": "Foo v1 retires."},
            {"title": "Foo overview", "url": "https://learn.microsoft.com/azure/foo/overview", "description": "About Foo."},
            {"title": "Foo v1 retirement (blog)", "url": "https://techcommunity.microsoft.com/foo", "description": "Foo retirement"},
            {"title": "Foo v1 deprecation FAQ", "url": "https://learn.microsoft.com/azure/foo/faq", "description": ""},
            {"title": "Foo v1 end of support", "url": "https://learn.microsoft.com/azure/foo/eos", "description": ""}]}
        calls, waits = self._learn_fake(lambda q, n: good if "Foo" in q else {"results": []})
        name, run, c = self._drive_with_requests()
        self.assertIn("learn-fallback", c["next"])
        self.assertGreater(c["learnRequests"], 0)
        self.tool("merge", "--run", name, expect=2)  # pending requests block merge
        self.assertIn("learn-fallback", self.tool("status", "--run", name)["next"])
        out = self.tool("learn-fallback", "--run", name)
        # One request per distinct query (the ten Foo notices share one query), paced by the minimum interval.
        self.assertEqual(len(calls), len(set(calls)))
        self.assertEqual(out["learnFallback"]["searches"], len(calls))
        self.assertEqual(waits, [learn.MIN_INTERVAL_SEC] * (len(calls) - 1))
        self.assertEqual(out["capabilities"]["learnMcp"], learn.LEARN_CAPABILITY_FALLBACK)
        self.tool("merge", "--run", name)
        f = json.loads((run / "findings.json").read_text(encoding="utf-8"))
        foo = next(x for x in f["events"] if x["eventId"] == "100-1" or x["eventId"] == "100")
        self.assertEqual([l["url"] for l in foo["referenceLinks"]],
                         ["https://learn.microsoft.com/azure/foo/migrate", "https://learn.microsoft.com/azure/foo/faq"])
        self.assertTrue(all(l["source"] == "LearnSearch" and l["learnQuery"] for l in foo["referenceLinks"]))
        self.assertTrue(all(x["remediationStatus"] == "notFound" for x in f["events"]))  # links only
        plan = next(p for p in f["collectionPlan"] if p["task"] == "Remediation:learnSupplement")
        self.assertEqual(plan["status"], "downgraded")
        self.assertIn("learn-fallback", plan["evidence"]["note"])
        self.assertEqual(f["metadata"]["capabilities"]["learnMcp"], learn.LEARN_CAPABILITY_FALLBACK)

    def test_learn_fallback_honors_retry_after_and_stops_on_persistent_429(self):
        err = lambda ra: learn.LearnHttpError(429, ra, "HTTP 429")
        calls, waits = self._learn_fake(lambda q, n: err("3") if n == 1 else {"results": []})
        name, run, _ = self._drive_with_requests()
        self.tool("learn-fallback", "--run", name)
        self.assertIn(3.0, waits)  # Retry-After honored
        self.assertTrue(all(c == 2 for c in (calls.count(q) for q in set(calls))))  # one 429 then success per query
        name2, run2, _ = self._drive_with_requests()
        calls.clear()
        waits.clear()
        self._learn_fake(lambda q, n: err("999"))
        out = self.tool("learn-fallback", "--run", name2)
        st = json.loads((run2 / ".work" / "state.json").read_text(encoding="utf-8"))
        items = st["learnFallback"]["items"]
        self.assertTrue(items and all(x["status"] == "stopped" for x in items))
        self.assertEqual(out["learnFallback"]["searches"], 1)  # circuit breaker: no further queries
        self.assertIn("429", out["learnFallback"]["stoppedReason"])
        self.assertEqual(st["capabilities"]["learnMcp"], "不可")
        self.tool("merge", "--run", name2)  # stopped requests do not block the report

    def test_learn_fallback_cap_and_rerun(self):
        calls, _ = self._learn_fake(lambda q, n: {"results": []})
        name, run, _ = self._drive_with_requests()
        orig = learn.MAX_SEARCHES
        learn.MAX_SEARCHES = 1
        try:
            self.tool("learn-fallback", "--run", name)
            st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
            items = st["learnFallback"]["items"]
            queries = {x["query"] for x in items}
            self.assertGreater(len(queries), 1)
            self.assertIn("capped", {x["status"] for x in items})
            for _ in range(len(queries) - 1):
                self.tool("learn-fallback", "--run", name)  # each re-run serves the remaining requests
        finally:
            learn.MAX_SEARCHES = orig
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(calls), sorted(queries))  # one search per distinct query in total
        self.assertEqual({x["status"] for x in st["learnFallback"]["items"]}, {"noMatch"})

    def test_no_learn_requests_skips_learn_fallback(self):
        name, run = self._plan_all()
        c = self.drive(name, run, lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP",
                                                              "titleJa": "x", "events": [ev(nid, "2027-01-01")]})
        self.assertTrue(c["next"].startswith("merge"))
        self.assertEqual(self.tool("learn-fallback", "--run", name)["learnFallback"]["status"], "notNeeded")
        self.tool("merge", "--run", name)

    def test_learn_url_guard(self):
        learn._check_learn_url(learn.search_url("Azure Foo retirement"))
        for bad in ("https://learn.microsoft.com/azure/foo", "http://learn.microsoft.com/api/search?search=x",
                    "https://evil.example/api/search", "https://learn.microsoft.com.evil/api/search"):
            with self.assertRaises(common.ToolError):
                learn._check_learn_url(bad)

    def test_learn_capability_uses_only_accepted_attempts(self):
        name, run = self._plan_all()
        ok = lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": "x",
                                        "events": [ev(nid, "2027-01-01")]}
        self.tool("next-wave", "--run", name)
        self.simulate(run, lambda nid, attempt, inp: None, learn="available")  # first attempts all fail
        self.tool("check-shards", "--run", name)
        c = self.drive(name, run, ok, learn="unavailable")
        self.assertEqual(c["G2"]["status"], "pass")
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        self.assertIn("available", [b["learnMcp"] for b in st["batches"]])
        self.assertEqual(st["capabilities"]["learnMcp"], "不可")

    def test_partial_learn_failure_downgrades_the_supplement_task(self):
        name, run = self._plan_all()
        first: list[str] = []

        def learn(batch_id):
            if not first:
                first.append(batch_id)
            return "available" if batch_id == first[0] else "unavailable"
        c = self.drive(name, run, lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP",
                                                              "titleJa": "x", "events": [ev(nid, "2027-01-01")]}, learn=learn)
        self.assertEqual(c["G2"]["status"], "pass")
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        self.assertGreater(len(st["batches"]), 1)
        self.assertEqual(st["capabilities"]["learnMcp"], "利用可")
        self.assertTrue(st["learnSupplementIncomplete"])
        self.tool("merge", "--run", name)
        f = json.loads((run / "findings.json").read_text(encoding="utf-8"))
        plan = next(p for p in f["collectionPlan"] if p["task"] == "Remediation:learnSupplement")
        self.assertEqual(plan["status"], "downgraded")
        self.assertIn("補完不可", plan["evidence"]["note"])

    def test_mcp_and_fallback_mixed_in_one_batch_downgrades(self):
        # One batch used Learn MCP for one event and fell back to GET for another: learnMcp stays "available"
        # (MCP-derived remediation is kept) while learnIncomplete reports the partial supplement.
        name, run = self._plan_all()
        first: list[str] = []

        def incomplete(batch_id):
            if not first:
                first.append(batch_id)
            return batch_id == first[0]

        def spec(nid, attempt, inp):
            e = ev(nid, "2027-01-01", links=[{"titleJa": "Learn", "url": "https://learn.microsoft.com/azure/bar",
                                              "source": "LearnSearch", "learnQuery": "q"}])
            e["remediationStatus"] = "supplementedByLearn"
            return {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": "x", "events": [e]}
        c = self.drive(name, run, spec, learn="available", incomplete=incomplete)
        self.assertEqual(c["G2"]["status"], "pass")
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(all(b["learnMcp"] == "available" for b in st["batches"]))
        self.assertEqual(sum(1 for b in st["batches"] if b["learnIncomplete"]), 1)
        self.assertEqual(st["capabilities"]["learnMcp"], "利用可")
        self.assertTrue(st["learnSupplementIncomplete"])
        self.tool("merge", "--run", name)
        f = json.loads((run / "findings.json").read_text(encoding="utf-8"))
        self.assertTrue(all(x["remediationStatus"] == "supplementedByLearn" for x in f["events"]))
        plan = next(p for p in f["collectionPlan"] if p["task"] == "Remediation:learnSupplement")
        self.assertEqual(plan["status"], "downgraded")

    def test_complete_learn_mcp_run_is_done(self):
        name, run = self._plan_all()
        c = self.drive(name, run, lambda nid, attempt, inp: {"id": nid, "fetchStatus": "ok", "fetchedVia": "MRC MCP",
                                                              "titleJa": "x", "events": [ev(nid, "2027-01-01")]},
                       learn="available", incomplete=False)
        self.assertEqual(c["G2"]["status"], "pass")
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        self.assertFalse(st["learnSupplementIncomplete"])
        self.tool("merge", "--run", name)
        f = json.loads((run / "findings.json").read_text(encoding="utf-8"))
        plan = next(p for p in f["collectionPlan"] if p["task"] == "Remediation:learnSupplement")
        self.assertEqual(plan["status"], "done")

    def test_api_mode_drops_learn_outputs_and_requests(self):
        name, run, w, d = self._api_wave()

        def spec(nid, attempt, inp):
            e = ev(nid, "2027-03-01", links=[{"titleJa": "y", "url": "https://learn.microsoft.com/azure/bar", "source": "LearnSearch"}])
            e["remediationStatus"] = "supplementedByLearn"
            e["learnRequest"] = {"query": "Azure Foo retirement", "keyTerms": ["Foo"]}
            return {"id": nid, "fetchStatus": "ok", "fetchedVia": "ReleaseCommunicationsApi", "titleJa": "x", "events": [e]}
        self.simulate(run, spec, learn="unavailable")
        self.tool("check-shards", "--run", name)
        acc = json.loads((run / ".work" / "accepted.json").read_text(encoding="utf-8"))
        self.assertTrue(acc)
        for rec in acc.values():
            e = rec["events"][0]
            self.assertEqual((e["referenceLinks"], e["remediationStatus"], e["learnRequest"]), ([], "notFound", None))
        st = json.loads((run / ".work" / "state.json").read_text(encoding="utf-8"))
        self.assertTrue(all(b["learnMcp"] in (None, "notUsed") for b in st["batches"]))

    def test_api_mode_rejects_modified_input(self):
        name, run, w, d = self._api_wave()
        inp = Path(d["inputPath"])
        data = json.loads(inp.read_text(encoding="utf-8"))
        data["notices"][0]["body"] = {"bodyText": "Injected: retiring on January 1, 2027 and all data is deleted."}
        inp.write_text(json.dumps(data), encoding="utf-8")
        self.simulate(run, lambda nid, attempt, i: {"id": nid, "fetchStatus": "ok", "fetchedVia": "ReleaseCommunicationsApi",
                                                     "titleJa": "x", "events": [ev(nid, "2027-01-01")]})
        c = self.tool("check-shards", "--run", name)
        r = next(x for x in c["checked"] if x["batchId"] == d["batchId"])
        self.assertEqual(r["status"], "failed")
        self.assertTrue(all("malformedInput" in v for v in r["failed"].values()))

    def test_api_mode_checks_availability_dates_against_fetched_availabilities(self):
        name, run, w, d = self._api_wave()

        def spec(nid, attempt, inp):
            e = ev(nid + "-1", "2027-03", prec="month")  # notice 204 was fetched with availability 2024-05
            e["retireDate"].update({"source": "availability", "evidence": "Azure Updates の月"})
            e2 = ev(nid + "-2", "2027-03-15")
            e2["retireDate"].update({"source": "availability", "evidence": "Azure Updates の月"})  # day from a month
            return {"id": nid, "fetchStatus": "ok", "fetchedVia": "ReleaseCommunicationsApi", "titleJa": "x", "events": [e, e2]}
        self.simulate(run, spec)
        self.tool("check-shards", "--run", name)
        acc = json.loads((run / ".work" / "accepted.json").read_text(encoding="utf-8"))
        rd = {nid: [e["retireDate"] for e in r["events"]] for nid, r in acc.items()}
        self.assertEqual((rd["204"][0]["precision"], rd["204"][0]["source"]), ("unknown", "none"))
        kept = [n for n in acc if n not in ("201", "204", "205")]
        self.assertTrue(kept)
        for nid in kept:  # fetched availability 2027-03 matches
            self.assertEqual((rd[nid][0]["precision"], rd[nid][0]["start"]), ("month", "2027-03-01"))
        for nid, dates in rd.items():
            self.assertEqual(dates[1]["precision"], "unknown")

    def test_verify_takes_the_run_lock(self):
        name, run = self._plan_all()
        with common.RunLock(run):
            out = self.tool("verify", "--run", name, expect=2)
        self.assertIn("running", out["error"])


class ApiResponses(unittest.TestCase):
    class _Resp:
        def __init__(self, ctype, data, status=200):
            self.status, self.headers, self._data = status, {"Content-Type": ctype}, data

        def read(self, n=-1):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _with(self, resp):
        orig = api._OPENER
        api._OPENER = type("O", (), {"open": staticmethod(lambda req, timeout=None: resp)})()
        try:
            with self.assertRaises(common.ToolError) as cm:
                api._http_get_json(api.API_BASE + "?$top=1")
        finally:
            api._OPENER = orig
        return cm.exception

    def test_malformed_responses_are_network_errors(self):
        for resp in (self._Resp("text/html", b"<html>"), self._Resp("application/json", b"\xff\xfe\x00bad"),
                     self._Resp("application/json", b"{not json"), self._Resp("application/json", b"{}", status=203)):
            self.assertEqual(self._with(resp).code, 3)


class Units(unittest.TestCase):
    def test_failed_g4_routes_back_to_render(self):
        st = {"runId": "r", "phase": "rendered", "gates": {"G4": {"status": "fail", "gates": {"4c CSP": "fail: x", "1": "pass"}}}}
        self.assertIn("render --run r", progress.next_action(st))
        self.assertIn("4c CSP", progress.next_action(st))
        st["gates"]["G4"]["status"] = "pass"
        self.assertIn("record-review", progress.next_action(st))

    def test_scope(self):
        d = dt.date(2026, 10, 15)
        self.assertEqual(api.compute_scope("default", d)["windowStart"], "2026-07-01")
        s = api.compute_scope("next12Months", dt.date(2026, 10, 7))
        self.assertEqual((s["windowEnd"], s["prefilterStartYear"]), ("2027-10-06", 2026))
        self.assertEqual(api.compute_scope("all", d)["prefilterStartYear"], None)
        c = api.compute_scope("custom", d, "2027-02", "2027-02")
        self.assertEqual((c["windowStart"], c["windowEnd"]), ("2027-02-01", "2027-02-28"))

    def test_score_matrix(self):
        as_of = dt.date(2026, 10, 7)

        def e(start, prec="day", flags=("unknown", "unknown", "unknown"), cls="confirmed"):
            end = start
            if prec == "month" and start:
                end = common.month_bounds(int(start[:4]), int(start[5:7]))[1].isoformat()
            return {"retireDate": {"precision": prec, "start": start, "end": end}, "classificationStatus": cls,
                    "flags": dict(zip(("workloadStop", "dataLossRisk", "autoMigration"), flags))}
        self.assertEqual(merge.score(e("2026-12-01", flags=("true", "unknown", "unknown")), as_of)["impact"], "High")
        self.assertEqual(merge.score(e("2027-06-01"), as_of)["impact"], "Medium")
        self.assertEqual(merge.score(e("2028-06-01"), as_of)["impact"], "Low")
        self.assertEqual(merge.score(e("2028-06-01", flags=("unknown", "true", "unknown")), as_of)["impact"], "Medium")
        self.assertEqual(merge.score(e("2026-12-01", flags=("unknown", "unknown", "true")), as_of)["impact"], "Medium")
        r = merge.score(e("2026-10-01", "month"), as_of)
        self.assertEqual((r["status"], r["daysRemaining"], r["urgencyScore"]), ("currentMonth", -6, 3))
        self.assertEqual(merge.score(e("2026-01-01"), as_of)["status"], "retired")
        self.assertEqual(merge.score(e(None, "unknown"), as_of)["impact"], "NeedsReview")
        self.assertEqual(merge.score(e("2027-01-01", cls="insufficientEvidence"), as_of)["severityScore"], None)
        self.assertEqual(merge.score(e("2027-01-05"), as_of)["urgencyScore"], 3)  # 90 days

    def test_url_allowlist(self):
        ok = ["https://learn.microsoft.com/x", "https://aka.ms/x", "https://portal.azure.com/", "https://github.com/MicrosoftDocs/a"]
        bad = {"https://evilmicrosoft.com": "disallowedHostOrPath", "http://learn.microsoft.com": "notHttps",
               "https://u:p@learn.microsoft.com": "userInfo", "https://x.azurewebsites.net": "disallowedHostOrPath",
               "https://github.com/evil/repo": "disallowedHostOrPath", "": "empty/invalid",
               "https://eur01.safelinks.protection.outlook.com/?url=x": "SafeLinks"}
        for u in ok:
            self.assertIsNone(common.url_violation(u), u)
        for u, k in bad.items():
            self.assertEqual(common.url_violation(u), k, u)
        self.assertEqual(common.normalize_link("http://aka.ms/x"), "https://aka.ms/x")
        self.assertEqual(common.normalize_link("https://nam.safelinks.protection.outlook.com/?url=https%3A%2F%2Faka.ms%2Fy&data=a"), "https://aka.ms/y")
        self.assertIsNone(common.normalize_link("https://nam.safelinks.protection.outlook.com/?url=https%3A%2F%2Fevil.com"))

    def test_clean_text(self):
        self.assertEqual(common.clean_text("a\nb\x00c  d", 50), "a b c d")
        self.assertNotIn("@", common.clean_text("mail me: a.b@example.co.jp", 100))
        self.assertEqual(common.clean_text("x%40example.com y@z", 100), common.clean_text("x%40example.com y@z", 100))
        self.assertFalse(common.sensitive_kinds(common.clean_text("user%40example.com", 100)))
        self.assertEqual(len(common.clean_text("あ" * 500, 100)), 100)

    def test_normalize_title_and_order(self):
        self.assertEqual(plan.normalize_title("Reminder: Retirement: Foo v1 API!"), "foo v1 api")
        keys = sorted(["b", "Developer tools", "DevOps", "a"], key=common.ordinal_ignore_case_key)
        self.assertEqual(keys, ["a", "b", "Developer tools", "DevOps"])

    def test_run_path_safety(self):
        for bad in ("..", "../x", "20260101-000000/../../x", "not-a-run", "C:\\Windows"):
            with self.assertRaises(common.ToolError):
                common.resolve_run(bad)

    def test_api_url_guard(self):
        with self.assertRaises(common.ToolError):
            api._check_api_url("https://evil.example.com/releasecommunications/api/v2/azure")
        with self.assertRaises(common.ToolError):
            api._check_api_url("http://www.microsoft.com/releasecommunications/api/v2/azure")
        api._check_api_url(api.API_BASE + "?$top=1")


class ReviewRegressions(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / ".work").mkdir()
        self.meta = {i: {"id": i, "title": f"t {i}", "products": [], "productCategories": [], "availabilityMonth": None,
                         "created": "", "modified": "2026-01-01T00:00:00Z"} for i in ("a", "b", "c", "d")}
        self.st = {"groups": [{"groupId": "G01", "noticeIds": ["a", "b", "d"], "anchorNoticeId": "a"}],
                   "enumeration": {"allowedCategories": ["Uncategorized"]}, "capabilities": {"mrcMcp": "利用可"}}
        self.b = {"batchId": "B01", "noticeIds": ["a", "b", "c", "d"], "shardPath": ".work/batch-01.json", "referenceEvents": [],
                  "bodySource": "MRC MCP", "prefetchFailedNoticeIds": []}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def shard(self, obj):
        obj = {"learnMcp": "notUsed", "learnIncomplete": False, **obj}
        (self.tmp / ".work" / "batch-01.json").write_text(json.dumps(obj), encoding="utf-8")
        return shards.check_batch(self.tmp, self.st, self.b, self.meta, {})

    def test_learn_mcp_manifest_is_required_and_consistent(self):
        ids = ["a", "b", "c", "d"]
        base = {"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids, "failedNoticeIds": [],
                "notices": [self.n(i) for i in ids]}
        for bad in (None, "", "yes", "Available", "fallbackGet"):  # workers never GET Learn themselves
            ok, fail, _, _, _ = self.shard(dict(base, learnMcp=bad))
            self.assertEqual(ok, {})
            self.assertTrue(all("learnMcp" in v for v in fail.values()))
        learned = self.n("a")
        learned["events"][0]["referenceLinks"] = [{"titleJa": "d", "url": "https://learn.microsoft.com/azure/foo", "source": "Description"},
                                                  {"titleJa": "l", "url": "https://learn.microsoft.com/azure/bar", "source": "LearnSearch"}]
        learned["events"][0]["remediationStatus"] = "supplementedByLearn"
        notices = [learned] + [self.n(i) for i in ids[1:]]
        ok, fail, warn, learn, _ = self.shard(dict(base, notices=notices, learnMcp="notUsed"))
        self.assertFalse(fail)
        e = ok["a"]["events"][0]
        self.assertEqual([l["source"] for l in e["referenceLinks"]], ["Description"])
        self.assertEqual((e["remediationStatus"], e["remediationJa"], learn), ("notFound", [], "notUsed"))
        self.assertEqual(len(warn), 2)
        ok, _, warn, learn, _ = self.shard(dict(base, notices=notices, learnMcp="available"))
        e = ok["a"]["events"][0]
        self.assertEqual((len(e["referenceLinks"]), e["remediationStatus"], learn), (2, "supplementedByLearn", "available"))
        self.assertFalse(warn)
        ok, _, warn, learn, _ = self.shard(dict(base, notices=notices, learnMcp="unavailable"))
        e = ok["a"]["events"][0]
        self.assertEqual(([l["source"] for l in e["referenceLinks"]], e["remediationStatus"], learn),
                         (["Description"], "notFound", "unavailable"))
        self.assertEqual(len(warn), 2)

    def test_learn_incomplete_flag(self):
        ids = ["a", "b", "c", "d"]
        base = {"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids, "failedNoticeIds": [],
                "notices": [self.n(i) for i in ids]}
        cases = [("available", True, True, 0), ("available", "true", True, 0), ("available", False, False, 0),
                 ("available", None, True, 1), ("available", "yes", True, 1),
                 ("unavailable", False, True, 0),
                 ("notUsed", False, False, 0), ("notUsed", True, False, 1)]
        for learn_v, flag, want, nwarn in cases:
            ok, fail, warn, learn, inc = self.shard(dict(base, learnMcp=learn_v, learnIncomplete=flag))
            self.assertFalse(fail, (learn_v, flag))
            self.assertEqual((learn, inc, len(warn)), (learn_v, want, nwarn), (learn_v, flag))
        (self.tmp / ".work" / "batch-01.json").write_text(json.dumps(dict(base, learnMcp="available")), encoding="utf-8")
        *_, inc = shards.check_batch(self.tmp, self.st, self.b, self.meta, {})
        self.assertTrue(inc)  # missing on a Learn MCP batch: conservatively partial

    def test_learn_search_links_must_point_to_learn(self):
        ids = ["a", "b", "c", "d"]
        a = self.n("a")
        a["events"][0]["referenceLinks"] = [
            {"titleJa": "ok", "url": "https://learn.microsoft.com/azure/bar", "source": "LearnSearch"},
            {"titleJa": "other", "url": "https://azure.microsoft.com/updates/x", "source": "LearnSearch"},
            {"titleJa": "desc", "url": "https://azure.microsoft.com/updates/y", "source": "Description"}]
        base = {"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids, "failedNoticeIds": [],
                "notices": [a] + [self.n(i) for i in ids[1:]]}
        ok, fail, _, _, _ = self.shard(dict(base, learnMcp="available"))
        self.assertFalse(fail)
        self.assertEqual([l["url"] for l in ok["a"]["events"][0]["referenceLinks"]],
                         ["https://learn.microsoft.com/azure/bar", "https://azure.microsoft.com/updates/y"])

    def test_learn_requests_are_settled(self):
        ids = ["a", "b", "c", "d"]
        req = {"query": "Azure Foo v1 retirement", "keyTerms": ["Foo"]}
        linked, bare, bad = self.n("a"), self.n("b"), self.n("c")
        linked["events"][0]["learnRequest"] = dict(req)  # already has a link -> dropped
        bare["events"][0]["referenceLinks"] = []
        bare["events"][0]["learnRequest"] = dict(req)  # kept
        bad["events"][0]["referenceLinks"] = []
        bad["events"][0]["learnRequest"] = {"query": "", "keyTerms": []}  # invalid -> dropped
        base = {"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids, "failedNoticeIds": [],
                "notices": [linked, bare, bad, self.n("d")]}
        ok, fail, warn, _, inc = self.shard(dict(base, learnMcp="available", learnIncomplete=False))
        self.assertFalse(fail)
        self.assertEqual([ok[i]["events"][0]["learnRequest"] for i in ("a", "b", "c")], [None, req, None])
        self.assertTrue(inc)  # a remaining request means that event was not served by Learn MCP
        self.assertEqual(len(warn), 3)
        ok, _, _, _, inc = self.shard(dict(base, learnMcp="notUsed", learnIncomplete=False))
        self.assertTrue(all(r["events"][0]["learnRequest"] is None for r in ok.values()))
        self.assertFalse(inc)

    def test_learn_search_pick_is_deterministic(self):
        res = [{"title": "Foo v1 retirement", "url": "https://learn.microsoft.com/a"},
               {"title": "Foo v1 retirement", "url": "https://learn.microsoft.com/a"},
               {"title": "Bar retirement", "url": "https://learn.microsoft.com/b"},
               {"title": "Foo overview", "url": "https://learn.microsoft.com/c"},
               {"title": "Foo migration", "url": "http://learn.microsoft.com/d"},
               {"title": "Foo end of support", "url": "https://learn.microsoft.com/e"},
               {"title": "Foo deprecation", "url": "https://learn.microsoft.com/f"}]
        self.assertEqual([l["url"] for l in learn.pick_links(res, ["foo"])],
                         ["https://learn.microsoft.com/a", "https://learn.microsoft.com/d"])

    def test_learn_capability_aggregation(self):
        cap = shards.learn_capability
        self.assertEqual(cap([]), "未使用")
        self.assertEqual(cap(["notUsed"]), "未使用")
        self.assertEqual(cap(["notUsed", "unavailable"]), "不可")
        self.assertEqual(cap(["available", "unavailable"]), "利用可")

    def n(self, i, same=None):
        return {"id": i, "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": "x", "events": [ev(i, "2027-01-01", same=same)]}

    def test_shard_shape_never_crashes(self):
        ids = ["a", "b", "c", "d"]
        ok, fail, _, _, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": [],
                                     "failedNoticeIds": [{"id": i} for i in ids], "notices": [None]})
        self.assertEqual(ok, {})
        self.assertTrue(all(v.startswith("malformedShard") for v in fail.values()))
        ok, fail, _, _, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids + ["a"], "returnedNoticeIds": ids,
                                     "failedNoticeIds": [], "notices": [self.n(i) for i in ids]})
        self.assertEqual(ok, {})
        self.assertIn("duplicate", fail["a"])
        bad = self.n("a")
        bad["events"] = ["not-an-object"]
        ok, fail, _, _, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids,
                                     "failedNoticeIds": [], "notices": [bad] + [self.n(i) for i in ids[1:]]})
        self.assertIn("malformedShard", fail["a"])
        self.assertEqual(sorted(ok), ["b", "c", "d"])

    def test_same_event_requires_group_and_evidence(self):
        ids = ["a", "b", "c", "d"]
        notices = [self.n("a", {"noticeId": "c", "eventKey": "c", "evidence": "same"}),       # c is not in the group
                   self.n("b", {"noticeId": "a", "eventKey": "a", "evidence": ""}),           # no evidence
                   self.n("c"),
                   self.n("d", {"noticeId": "a", "eventKey": "a", "evidence": "Reminder"})]    # valid
        ok, fail, warn, _, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids,
                                        "failedNoticeIds": [], "notices": notices})
        self.assertFalse(fail)
        self.assertIsNone(ok["a"]["events"][0]["sameEventAs"])
        self.assertIsNone(ok["b"]["events"][0]["sameEventAs"])
        self.assertEqual(ok["d"]["events"][0]["sameEventAs"]["noticeId"], "a")
        self.assertEqual(len(warn), 2)

    def test_flags_without_evidence_become_unknown(self):
        e = ev("a", "2027-01-01", flags=("true", "false", "true"))
        e["flagEvidence"] = {"workloadStop": "", "dataLossRisk": "  ", "autoMigration": "Migrated automatically."}
        warn: list[str] = []
        out = shards.validate_event(e, "a", warn)
        self.assertEqual(out["flags"], {"workloadStop": "unknown", "dataLossRisk": "unknown", "autoMigration": "true"})
        self.assertEqual(len([w for w in warn if "flagEvidence" in w]), 2)
        e["flagEvidence"] = {"workloadStop": "Stops.", "dataLossRisk": "No data loss.", "autoMigration": ""}
        e["flags"]["autoMigration"] = "unknown"
        warn = []
        out = shards.validate_event(e, "a", warn)
        self.assertEqual(out["flags"], {"workloadStop": "true", "dataLossRisk": "false", "autoMigration": "unknown"})
        self.assertFalse(warn)

    def test_known_date_without_provenance_becomes_unknown(self):
        for rd in ({"source": "none", "evidence": "Retiring."}, {"evidence": "Retiring."},
                   {"source": "description", "evidence": "  "}, {"source": "availability"}):
            e = ev("a", "2027-01-01")
            e["retireDate"] = {"precision": "day", "start": "2027-01-01", "end": "2027-01-01", **rd}
            warn: list[str] = []
            out = shards.validate_event(e, "a", warn)
            self.assertEqual((out["retireDate"]["precision"], out["retireDate"]["start"], out["retireDate"]["source"]),
                             ("unknown", None, "none"))
            self.assertEqual(len([w for w in warn if "retireDate" in w]), 1)
        e = ev("a", "2027-01", prec="month")
        e["retireDate"]["source"] = "availability"
        warn = []
        out = shards.validate_event(e, "a", warn)
        self.assertEqual((out["retireDate"]["precision"], out["retireDate"]["end"]), ("month", "2027-01-31"))
        self.assertFalse(warn)

    def test_date_conflict_must_be_boolean(self):
        for v, want in ((True, True), ("false", False), (" TRUE ", True)):
            e = ev("a", "2027-01-01")
            e["dateConflict"] = v
            self.assertIs(shards.validate_event(e, "a", [])["dateConflict"], want)
        for v in ("invalid", None, 1, "yes"):
            e = ev("a", "2027-01-01")
            e["dateConflict"] = v
            with self.assertRaises(shards.ShardError):
                shards.validate_event(e, "a", [])
        e = ev("a", "2027-01-01")
        del e["dateConflict"]
        with self.assertRaises(shards.ShardError):
            shards.validate_event(e, "a", [])

    def test_fetched_via_must_match_exactly(self):
        meta = self.meta["a"]
        for via in ("MRC MCP", "ReleaseCommunicationsApi"):
            self.assertEqual(shards.validate_notice(dict(self.n("a"), fetchedVia=via), meta, ["Uncategorized"], [])["fetchedVia"], via)
        for via in ("not api", "mcp", "api", "", None, "mrc mcp"):
            with self.assertRaises(shards.ShardError):
                shards.validate_notice(dict(self.n("a"), fetchedVia=via), meta, ["Uncategorized"], [])

    def test_same_event_to_a_failing_target_is_kept_for_retry(self):
        ids = ["a", "b", "c", "d"]
        bad = self.n("a")
        bad["events"][0]["impactType"] = "Nope"  # a fails validation and will be retried
        notices = [bad, self.n("b", {"noticeId": "a", "eventKey": "a", "evidence": "Reminder of the retirement."}),
                   self.n("c"), self.n("d")]
        ok, fail, warn, _, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids,
                                        "failedNoticeIds": [], "notices": notices})
        self.assertIn("a", fail)
        self.assertEqual(ok["b"]["events"][0]["sameEventAs"]["noticeId"], "a")
        self.assertFalse(warn)
        # Once a is accepted on retry, merge links both notices into one event.
        cands = {i: {"id": i, "modified": "2026-01-01T00:00:00Z"} for i in ("a", "b")}
        retried = shards.validate_event(ev("a", "2027-01-01"), "a", [])
        out, _ = merge.merge_events(cands, {"a": {"events": [retried]}, "b": ok["b"]}, self.st["groups"])
        self.assertEqual(len(out), 1)
        self.assertEqual(sorted(out[0]["noticeIds"]), ["a", "b"])

    def test_split_event_id_does_not_collide(self):
        cands = {"foo": {"id": "foo", "modified": "2026-02-01"}, "foo-1": {"id": "foo-1", "modified": "2026-01-01"}}
        mk = lambda key: shards.validate_event(ev(key, "2027-01-01"), key, [])  # noqa: E731
        accepted = {"foo": {"events": [mk("foo-1"), mk("foo-2")]}, "foo-1": {"events": [mk("foo-1")]}}
        out, _ = merge.merge_events(cands, accepted, [])
        ids = sorted(c["eventId"] for c in out)
        self.assertEqual(ids, ["foo-1", "foo-2", "foo~1"])

    def test_lock_contention_and_ownership(self):
        run = self.tmp / "20990101-000000"
        run.mkdir()
        with common.RunLock(run) as first:
            with self.assertRaises(common.ToolError):
                common.RunLock(run).__enter__()
            other = common.RunLock(run)
            other.held = True  # simulate an instance that wrongly believes it holds the lock
            other.release()
            with self.assertRaises(common.ToolError):  # a non-owner release must not free our lock
                common.RunLock(run).__enter__()
            old = 0  # an old mtime must never make a live lock look stale
            os.utime(first.path, (old, old))
            with self.assertRaises(common.ToolError):
                common.RunLock(run).__enter__()
        # a leftover lock file without a live holder (e.g. after a crash) does not block the next command
        self.assertTrue(first.path.exists())
        with common.RunLock(run) as again:
            self.assertTrue(again.held)


if __name__ == "__main__":
    unittest.main()
