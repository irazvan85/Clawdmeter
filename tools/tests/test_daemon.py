"""Pure-function tests for daemon/claude_usage_daemon.py. Skipped when httpx
(the daemon's one third-party import) isn't installed -- e.g. under
PlatformIO's penv python during the pre-upload gate."""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import _util  # noqa: F401  (sets sys.path)

try:
    import claude_usage_daemon as d
except ImportError as e:     # httpx missing
    d = None
    SKIP = f"daemon not importable: {e}"
else:
    SKIP = ""


@unittest.skipIf(d is None, SKIP)
class RememberPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.file = self.tmp / "last-payloads.json"
        for p in (mock.patch.object(d, "LAST_PAYLOAD_FILE", self.file),
                  mock.patch.object(d, "_last_payloads", {})):
            p.start()
            self.addCleanup(p.stop)

    def test_wifi_never_cached(self):
        # Regression: a cached {"src":"wifi",...} once sat in this file in
        # plaintext and would have been replayed on every reconnect.
        d.remember_payload({"src": "wifi", "ssid": "x", "pass": "secret"})
        self.assertFalse(self.file.exists() and "secret" in self.file.read_text())

    def test_transient_srcs_not_cached(self):
        d.remember_payload({"src": "status", "state": "ok"})
        d.remember_payload({"src": "act", "st": "idle"})
        self.assertEqual(d._last_payloads, {})

    def test_regular_payload_cached_and_default_src(self):
        d.remember_payload({"s": 10})
        d.remember_payload({"src": "ci", "state": "pass"})
        self.assertEqual(set(json.loads(self.file.read_text())), {"claude", "ci"})

    def test_load_drops_legacy_wifi_entry(self):
        self.file.write_text(json.dumps({"wifi": {"pass": "secret"}, "ci": {"state": "pass"}}))
        d.load_last_payloads()
        self.assertEqual(set(d._last_payloads), {"ci"})


@unittest.skipIf(d is None, SKIP)
class Helpers(unittest.TestCase):
    def test_extract_access_token_shapes(self):
        tok = "sk-ant-oat01-" + "a" * 30
        self.assertEqual(d._extract_access_token(json.dumps({"claudeAiOauth": {"accessToken": tok}})), tok)
        self.assertEqual(d._extract_access_token(json.dumps([{"x": {"accessToken": tok}}])), tok)
        self.assertEqual(d._extract_access_token(tok), tok)
        self.assertIsNone(d._extract_access_token(""))
        self.assertIsNone(d._extract_access_token("not a token"))

    def test_model_short(self):
        self.assertEqual(d._model_short("claude-opus-5-5"), "Opus")
        self.assertEqual(d._model_short("claude-haiku-4-5-20251001"), "Haiku")
        self.assertEqual(d._model_short(""), "")

    def test_ascii_folds_for_device_fonts(self):
        self.assertTrue(d._ascii("Timișoara").isascii())

    def test_solar_altitude_day_night(self):
        # Bucharest: high sun at local noon in June, below horizon at midnight UTC.
        noon = d._solar_altitude_deg(44.43, 26.10, datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc))
        night = d._solar_altitude_deg(44.43, 26.10, datetime(2026, 6, 21, 23, 0, tzinfo=timezone.utc))
        self.assertGreater(noon, 60)
        self.assertLess(night, 0)

    def test_status_payload_shape(self):
        self.assertEqual(d.status_payload("ok"), {"src": "status", "state": "ok"})


@unittest.skipIf(d is None, SKIP)
class ChecksCollection(unittest.TestCase):
    def collect(self, prs=None, runs=None, reviews=None, current=None, details=None):
        def run(args, cwd=None, timeout=10):
            if args[0] == "git":
                return "# branch.head main\n# branch.ab +1 -0\n"
            if args[:3] == ["gh", "repo", "view"]:
                return json.dumps({"nameWithOwner": "owner/project"})
            if args[:3] == ["gh", "pr", "list"]:
                return json.dumps(prs) if prs is not None else None
            if args[:3] == ["gh", "pr", "view"]:
                return json.dumps(current) if current is not None else None
            if args[:3] == ["gh", "run", "list"]:
                self.assertIn("--branch", args)
                self.assertEqual(args[args.index("--branch") + 1], "main")
                return json.dumps(runs) if runs is not None else None
            if args[:3] == ["gh", "run", "view"]:
                return json.dumps(details or {})
            if args[:3] == ["gh", "search", "prs"]:
                return json.dumps(reviews) if reviews is not None else None
            self.fail(f"Unexpected command: {args}")
        with mock.patch.object(d, "_active_repo", return_value=Path("project")), \
             mock.patch.object(d, "_run", side_effect=run), mock.patch.object(d, "log"):
            return d.poll_ci()

    @staticmethod
    def pr(number=42, branch="main", checks=None, decision="APPROVED"):
        return {"number": number, "title": "Fix discovery", "headRefName": branch,
                "headRefOid": "1234567890abcdef", "reviewDecision": decision,
                "url": f"https://github.com/owner/project/pull/{number}",
                "statusCheckRollup": checks or []}

    def test_failure_keeps_pr_branch_job_step_and_links_together(self):
        check = {"name": "Windows", "conclusion": "FAILURE", "status": "COMPLETED",
                 "detailsUrl": "https://github.com/owner/project/actions/runs/123/job/456"}
        details = {"workflowName": "Tests", "headBranch": "wrong-merge-ref",
                   "headSha": "wrong-sha", "jobs": [{"databaseId": 456, "name": "Windows",
                   "conclusion": "failure", "steps": [{"name": "pytest", "conclusion": "failure"}]}]}
        result = self.collect(prs=[self.pr(checks=[check])], runs=[], reviews=[], details=details)
        item = result["items"][0]
        self.assertEqual((item["pr"], item["branch"], item["sha"]), (42, "main", "12345678"))
        self.assertEqual((item["workflow"], item["job"], item["step"]), ("Tests", "Windows", "pytest"))
        self.assertEqual(item["url"], check["detailsUrl"])
        self.assertEqual(result["chg"], 1)

    def test_other_pr_failure_precedes_current_branch_success(self):
        prs = [self.pr(checks=[{"conclusion": "SUCCESS"}]),
               self.pr(number=43, branch="feature", checks=[{"context": "deploy", "state": "ERROR"}])]
        result = self.collect(prs=prs, runs=[], reviews=[])
        self.assertEqual(result["items"][0]["pr"], 43)
        self.assertEqual(result["items"][0]["job"], "deploy")

    def test_cancelled_and_requested_changes_are_not_test_failures(self):
        result = self.collect(prs=[self.pr(checks=[{"conclusion": "CANCELLED"}], decision="CHANGES_REQUESTED")], runs=[], reviews=[])
        self.assertEqual(result["state"], "changes")
        self.assertEqual({x["state"] for x in result["items"]}, {"changes", "cancelled"})
        self.assertTrue(all(x["failed"] == 0 for x in result["items"]))

    def test_latest_workflow_success_hides_older_failed_run(self):
        result = self.collect(prs=[], reviews=[], runs=[
            {"workflowName": "CI", "conclusion": "success", "headBranch": "main", "headSha": "abc"},
            {"workflowName": "CI", "conclusion": "failure", "headBranch": "main"}])
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["state"], "pass")

    def test_reviews_identify_repo_and_pr_and_payload_is_bounded(self):
        reviews = [{"number": i, "title": "Review this", "repository": {"nameWithOwner": "other/repo"},
                    "url": f"https://github.com/other/repo/pull/{i}"} for i in range(8)]
        result = self.collect(prs=[], runs=[], reviews=reviews)
        self.assertEqual((result["rev"], result["total"], len(result["items"])), (8, 8, 4))
        self.assertEqual(result["items"][0]["repo"], "other/repo")
        self.assertTrue(result["review_ok"])
        self.assertEqual(len(d._ci_item(title="x" * 500)["title"]), 95)

    def test_github_unavailable_is_not_a_clean_queue(self):
        result = self.collect()
        self.assertEqual(result["state"], "unknown")
        self.assertFalse(result["review_ok"])

    def test_current_pr_is_collected_even_if_not_authored_by_me(self):
        current = self.pr(number=9, checks=[{"state": "FAILURE"}])
        current["state"] = "OPEN"
        result = self.collect(prs=[], runs=[], reviews=[], current=current)
        self.assertEqual(result["items"][0]["pr"], 9)
        self.assertEqual(result["chg"], 0)


@unittest.skipIf(d is None, SKIP)
class ClockAndDiscovery(unittest.IsolatedAsyncioTestCase):
    def test_discovery_includes_lan_with_vpn_present(self):
        from types import SimpleNamespace
        def address(ip, mask):
            return SimpleNamespace(family=d.socket.AF_INET, address=ip, netmask=mask)
        psutil = mock.MagicMock()
        psutil.net_if_addrs.return_value = {
            "VPN": [address("10.5.0.2", "255.255.0.0")],
            "Wi-Fi": [address("192.168.1.20", "255.255.255.0")],
            "Loopback": [address("127.0.0.1", "255.0.0.0")],
        }
        with mock.patch.dict("sys.modules", {"psutil": psutil}):
            self.assertEqual(d._discovery_targets(),
                             ["10.5.255.255", "192.168.1.255", "255.255.255.255"])

    async def test_replayed_weather_uses_current_clock(self):
        sent = []

        def respond(request):
            sent.append(json.loads(request.content))
            return d.httpx.Response(200)

        session = d.Session("http://192.0.2.1", "test")
        await session.http.aclose()
        session.http = d.httpx.AsyncClient(transport=d.httpx.MockTransport(respond))
        cached = {"src": "env", "ts": 1, "tz": 0, "tp": 15, "tn": "City"}
        fresh = {"src": "env", "ts": 1792674000, "tz": 180}
        try:
            with mock.patch.object(d, "clock_payload", return_value=fresh), \
                 mock.patch.object(d, "remember_payload"), mock.patch.object(d, "log"):
                self.assertTrue(await session.write_payload(cached))
            self.assertEqual(sent, [{**cached, **fresh}])
            self.assertEqual(cached["ts"], 1)
        finally:
            await session.aclose()

    async def test_unreachable_configured_ip_falls_back_to_discovery(self):
        client = mock.AsyncMock()
        client.get.side_effect = d.httpx.ConnectTimeout("offline")
        context = mock.MagicMock()
        context.__aenter__ = mock.AsyncMock(return_value=client)
        context.__aexit__ = mock.AsyncMock(return_value=False)
        with mock.patch.object(d, "read_config", return_value={"device_host": "192.0.2.1"}), \
             mock.patch.object(d.asyncio.get_running_loop(), "getaddrinfo", new=mock.AsyncMock(
                 return_value=[(None, None, None, None, ("192.0.2.1", 80))])), \
             mock.patch.object(d.httpx, "AsyncClient", return_value=context), \
             mock.patch.object(d, "_discover_broadcast_sync", return_value="192.0.2.2") as discover, \
             mock.patch.object(d, "log"):
            self.assertEqual(await d.resolve_device_ip(), "192.0.2.2")
            discover.assert_called_once()

    async def test_connection_sends_clock_before_replay_and_polling(self):
        session = mock.AsyncMock()
        session.probe.return_value = True
        stop = d.asyncio.Event()
        fresh = {"src": "env", "ts": 1792674000, "tz": 180}
        with mock.patch.object(d, "read_config", return_value={"device_token": "test"}), \
             mock.patch.object(d, "Session", return_value=session), \
             mock.patch.object(d, "clock_payload", return_value=fresh), \
             mock.patch.object(d, "_last_payloads", {}), \
             mock.patch.object(d, "CodexUsage"), \
             mock.patch.object(d, "_poll_loop", new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(d, "log"):
            with mock.patch.object(d.CodexUsage.return_value, "run", new=mock.AsyncMock()):
                self.assertTrue(await d.run_session("192.0.2.1", stop))
        self.assertEqual(session.method_calls[1], mock.call.write_payload(fresh))
        self.assertEqual(session.method_calls[2], mock.call.replay_last_payloads())


if __name__ == "__main__":
    unittest.main()
