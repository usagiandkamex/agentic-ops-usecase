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
from retirement_lib import api, common, merge, plan, shards  # noqa: E402

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

    def __call__(self, url):
        self.calls += 1
        p = urllib.parse.urlsplit(url)
        assert p.scheme == "https" and p.hostname == api.API_HOST
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

    def tool(self, *argv, expect=0):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = retirement_tool.main(list(argv))
        out = json.loads(buf.getvalue())
        self.assertEqual(code, expect, out)
        return out

    def init(self, scope="next12Months"):
        out = self.tool("init", "--scope", scope, "--as-of", AS_OF, "--mrc-mcp", "available")
        run = common.reports_root() / out["run"]
        self.created.append(run)
        return out["run"], run

    def simulate(self, run, spec):
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
            shard = {"batchId": b["batchId"], "attempt": inp["attempt"], "asOfDate": inp["asOfDate"], "learnMcp": "notUsed",
                     "expectedNoticeIds": ids, "returnedNoticeIds": ret, "failedNoticeIds": fail, "notices": notices}
            Path(inp["shardPath"]).write_text(json.dumps(shard, ensure_ascii=False), encoding="utf-8")

    def drive(self, run_name, run, spec, max_waves=20):
        for _ in range(max_waves):
            w = self.tool("next-wave", "--run", run_name)
            if not w["dispatch"]:
                break
            self.simulate(run, spec)
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

        evil = '</script><script>alert(1)</script>{{EVENT_COUNT}} <!-- END CATEGORY_ROWS -->'

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
        self.tool("set-highlight", "--run", name, "--text", "短い", expect=2)
        self.tool("set-highlight", "--run", name, "--text", "テスト用の総評です。High の件数と 90 日以内の件数を確認してください。")
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


class Units(unittest.TestCase):
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
                   "enumeration": {"allowedCategories": ["Uncategorized"]}}
        self.b = {"batchId": "B01", "noticeIds": ["a", "b", "c", "d"], "shardPath": ".work/batch-01.json", "referenceEvents": []}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def shard(self, obj):
        (self.tmp / ".work" / "batch-01.json").write_text(json.dumps(obj), encoding="utf-8")
        return shards.check_batch(self.tmp, self.st, self.b, self.meta, {})

    def n(self, i, same=None):
        return {"id": i, "fetchStatus": "ok", "fetchedVia": "MRC MCP", "titleJa": "x", "events": [ev(i, "2027-01-01", same=same)]}

    def test_shard_shape_never_crashes(self):
        ids = ["a", "b", "c", "d"]
        ok, fail, _, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": [],
                                     "failedNoticeIds": [{"id": i} for i in ids], "notices": [None]})
        self.assertEqual(ok, {})
        self.assertTrue(all(v.startswith("malformedShard") for v in fail.values()))
        ok, fail, _, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids + ["a"], "returnedNoticeIds": ids,
                                     "failedNoticeIds": [], "notices": [self.n(i) for i in ids]})
        self.assertEqual(ok, {})
        self.assertIn("duplicate", fail["a"])
        bad = self.n("a")
        bad["events"] = ["not-an-object"]
        ok, fail, _, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids,
                                     "failedNoticeIds": [], "notices": [bad] + [self.n(i) for i in ids[1:]]})
        self.assertIn("malformedShard", fail["a"])
        self.assertEqual(sorted(ok), ["b", "c", "d"])

    def test_same_event_requires_group_and_evidence(self):
        ids = ["a", "b", "c", "d"]
        notices = [self.n("a", {"noticeId": "c", "eventKey": "c", "evidence": "same"}),       # c is not in the group
                   self.n("b", {"noticeId": "a", "eventKey": "a", "evidence": ""}),           # no evidence
                   self.n("c"),
                   self.n("d", {"noticeId": "a", "eventKey": "a", "evidence": "Reminder"})]    # valid
        ok, fail, warn, _ = self.shard({"batchId": "B01", "expectedNoticeIds": ids, "returnedNoticeIds": ids,
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
