import asyncio
import json
import unittest
from unittest import mock

import _util  # noqa: F401
import codex_usage as c


def limits(pct=45):
    return {"rateLimitsByLimitId": {"codex": {"limitId": "codex", "planType": "team",
            "primary": {"usedPercent": pct, "windowDurationMins": 300, "resetsAt": 20000},
            "secondary": {"usedPercent": 7, "windowDurationMins": 10080, "resetsAt": 90000}}}}


class NormalizeCodex(unittest.TestCase):
    def test_real_shape_and_dynamic_windows(self):
        p = c.normalize_limits(limits(), now=10000)
        self.assertEqual((p["p1"], p["w1"], p["r1"], p["p2"], p["w2"]), (45, 300, 20000, 7, 10080))
        self.assertEqual((p["st"], p["plan"], p["ts"]), ("ok", "team", 10000))

    def test_selects_requested_bucket_not_other_model_pool(self):
        data = limits()
        data["rateLimitsByLimitId"]["other"] = {"primary": {"usedPercent": 99}}
        self.assertEqual(c.normalize_limits(data)["p1"], 45)
        self.assertEqual(c.normalize_limits(data, bucket="other")["p1"], 99)
        self.assertEqual(c.normalize_limits({"rateLimits": {"limitId": "other", "primary": {"usedPercent": 99}}})["st"], "unavailable")

    def test_legacy_single_window_and_missing_are_not_zero(self):
        p = c.normalize_limits({"rateLimits": {"primary": {"usedPercent": 0, "windowDurationMins": 15}}})
        self.assertEqual((p["st"], p["p1"], p["w1"], p["p2"], p["r1"]), ("ok", 0, 15, -1, 0))

    def test_invalid_numbers_do_not_become_usage(self):
        for value in (None, True, "45", float("nan"), float("inf"), -3, 120):
            with self.subTest(value=value):
                p = c.normalize_limits({"rateLimits": {"primary": {"usedPercent": value}}})
                self.assertEqual((p["st"], p["p1"]), ("unavailable", -1))

    def test_replay_age_preserves_reset_and_expired_quota(self):
        original = c.normalize_limits(limits(), now=10000)
        p = c.age_payload(original, now=30000)
        self.assertEqual((p["st"], p["age"], p["r1"], p["p1"]), ("stale", 20000, 20000, 45))
        self.assertEqual(original["age"], 0)

    def test_failure_retains_last_good_sample_and_recovery(self):
        watcher = c.CodexUsage()
        watcher.accept(limits())
        before = watcher.good.copy()
        watcher.failed("sign_in")
        self.assertEqual((watcher.latest["st"], watcher.latest["p1"], watcher.latest["ts"]), ("stale", 45, before["ts"]))
        watcher.accept(limits(52))
        self.assertEqual((watcher.latest["st"], watcher.latest["p1"]), ("ok", 52))

    def test_unrelated_notification_does_not_mark_quota_stale(self):
        watcher = c.CodexUsage()
        watcher.accept(limits())
        watcher.accept({"rateLimits": {"limitId": "other", "primary": {"usedPercent": 99}}})
        self.assertEqual((watcher.latest["st"], watcher.latest["p1"]), ("ok", 45))


class CodexProtocol(unittest.IsolatedAsyncioTestCase):
    async def test_response_correlation_and_notification(self):
        watcher = c.CodexUsage()
        stream = asyncio.StreamReader()
        watcher.process = mock.Mock(stdout=stream)
        future = asyncio.get_running_loop().create_future()
        watcher.pending[7] = future
        task = asyncio.create_task(watcher._read())
        stream.feed_data((json.dumps({"method": "account/rateLimits/updated", "params": limits()}) + "\n").encode())
        stream.feed_data(b'{"id":7,"result":{"ready":true}}\n')
        self.assertEqual(await asyncio.wait_for(future, 1), {"ready": True})
        self.assertEqual(watcher.latest["p1"], 45)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    async def test_missing_executable_publishes_status_and_stops(self):
        watcher = c.CodexUsage()
        stop = asyncio.Event()
        payloads = []
        async def publish(payload):
            payloads.append(payload)
            stop.set()
        with mock.patch.object(c, "find_codex", return_value=None):
            await asyncio.wait_for(watcher.run(publish, stop), 1)
        self.assertEqual((payloads[0]["st"], payloads[0]["p1"]), ("missing", -1))

    async def test_rpc_timeout_removes_pending_request(self):
        watcher = c.CodexUsage()
        async def send(_message):
            raise asyncio.TimeoutError()
        watcher._send = send
        with self.assertRaises(asyncio.TimeoutError):
            await watcher.rpc("account/rateLimits/read")
        self.assertEqual(watcher.pending, {})


if __name__ == "__main__":
    unittest.main()
