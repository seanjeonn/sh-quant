"""python3 -m unittest kingfish.test_kingfish -v  (네트워크 없음)"""
import io
import json
import sqlite3
import unittest
from email.message import Message
from unittest import mock
from urllib.error import HTTPError

from . import db
from .pipeline import Pipeline
from .toss import TossClient, TossError, classify


class _Resp(io.BytesIO):
    headers = Message()


def resp(obj, gz=False):
    import gzip
    raw = json.dumps(obj).encode()
    r = _Resp(gzip.compress(raw) if gz else raw)
    if gz:
        r.headers = Message()
        r.headers["Content-Encoding"] = "gzip"
    return r


def http_err(status, code, retry_after=None):
    h = Message()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    return HTTPError("u", status, "m", h, io.BytesIO(json.dumps({"error": {"code": code}}).encode()))


def candle(ts, o, h, l, c, v):
    return {"timestamp": ts, "openPrice": str(o), "highPrice": str(h), "lowPrice": str(l),
            "closePrice": str(c), "volume": str(v), "currency": "USD"}


class DbTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")

    def test_normalize(self):
        row = db.normalize("aapl", candle("2026-10-05T22:31:00+09:00", "1.5", "2", "1", "1.75", "10"))
        self.assertEqual(row, ("AAPL", "2026-10-05 13:31:00", 1.5, 2.0, 1.0, 1.75, 10.0))
        self.assertIsNone(db.normalize("AAPL", candle("2026-10-05T22:31:00+09:00", 1, 1, 2, 1, 1)))  # high<low
        self.assertIsNone(db.normalize("AAPL", candle("2026-10-05T22:31:00+09:00", 0, 1, 1, 1, 1)))  # price<=0
        self.assertIsNone(db.normalize("AAPL", {"timestamp": "bad"}))

    def test_bucket_end(self):
        self.assertEqual(db.bucket_end("2026-10-05 13:31:00"), "2026-10-05 13:35:00")
        self.assertEqual(db.bucket_end("2026-10-05 13:35:00"), "2026-10-05 13:35:00")
        self.assertEqual(db.bucket_end("2026-10-05 13:36:00"), "2026-10-05 13:40:00")

    def test_rollup_5m(self):
        bars = [("AAPL", f"2026-10-05 13:{m:02d}:00", 10 + i, 20 + i, 5 - i * 0.1, 11 + i, 100) for i, m in enumerate(range(31, 37))]
        n, lo, hi = db.upsert_1m(self.con, bars)
        self.assertEqual((n, lo, hi), (6, "2026-10-05 13:31:00", "2026-10-05 13:36:00"))
        self.assertEqual(db.rollup_5m(self.con, "AAPL", lo, hi), 2)
        r = self.con.execute("SELECT * FROM candles_5m WHERE ts='2026-10-05 13:35:00'").fetchone()
        self.assertEqual(r, ("AAPL", "2026-10-05 13:35:00", 10.0, 24.0, 4.6, 15.0, 500.0, 5, 1))
        r = self.con.execute("SELECT n_bars FROM candles_5m WHERE ts='2026-10-05 13:40:00'").fetchone()
        self.assertEqual(r, (1,))
        # 사후 정정된 봉 upsert → 재집계에 반영
        db.upsert_1m(self.con, [("AAPL", "2026-10-05 13:35:00", 14, 99, 4.6, 15, 100)])
        db.rollup_5m(self.con, "AAPL", "2026-10-05 13:35:00", "2026-10-05 13:35:00")
        self.assertEqual(self.con.execute("SELECT high FROM candles_5m WHERE ts='2026-10-05 13:35:00'").fetchone(), (99.0,))

    def test_rollup_idempotent(self):
        bars = [("AAPL", f"2026-10-05 13:{m:02d}:00", 0.1 * m, 0.3 * m, 0.01 * m, 0.2 * m, 0.7) for m in range(31, 41)]
        db.upsert_1m(self.con, bars)
        snap = lambda: self.con.execute("SELECT * FROM candles_5m ORDER BY ts").fetchall()
        db.rollup_5m(self.con, "AAPL", bars[0][1], bars[-1][1])
        first = snap()
        for _ in range(50):  # 증분이 아니라 1m에서 재계산 → 반복해도 값이 그대로
            db.upsert_1m(self.con, bars)
            db.rollup_5m(self.con, "AAPL", bars[0][1], bars[-1][1])
        self.assertEqual(snap(), first)

    def test_complete(self):
        db.upsert_1m(self.con, [("AAPL", "2026-10-05 12:05:00", 1, 1, 1, 1, 1)])
        db.rollup_5m(self.con, "AAPL", "2026-10-05 12:05:00", "2026-10-05 12:05:00", "2026-10-05 12:06:04")
        q = "SELECT complete FROM candles_5m WHERE ts='2026-10-05 12:05:00'"
        self.assertEqual(self.con.execute(q).fetchone(), (0,))
        db.rollup_5m(self.con, "AAPL", "2026-10-05 12:05:00", "2026-10-05 12:05:00", "2026-10-05 12:06:05")
        self.assertEqual(self.con.execute(q).fetchone(), (1,))

    def test_coverage_gaps(self):
        db.save_sessions(self.con, {"today": {"date": "2026-10-05", "regularMarket": {
            "startTime": "2026-10-05T22:30:00+09:00", "endTime": "2026-10-06T05:00:00+09:00"}}})
        for f in ("2026-10-05 14:00:00", "2026-10-05 14:40:00"):  # poll 성공 = 직전 30분
            db.log_sync(self.con, "poll", "AAPL", f, True, finished=f)
        db.log_sync(self.con, "poll", "AAPL", "x", False, finished="2026-10-05 14:20:00")  # 실패 poll은 무시
        gaps = db.coverage_gaps(self.con, "AAPL", "2026-10-05 00:00:00", "2026-10-05 14:50:00", 30)
        self.assertEqual(gaps, [("2026-10-05 14:00:00", "2026-10-05 14:10:00"), ("2026-10-05 14:40:00", "2026-10-05 14:50:00")])
        db.log_sync(self.con, "cover", "AAPL", "2026-10-05 14:00:00", True, finished="2026-10-05 14:10:00")
        gaps = db.coverage_gaps(self.con, "AAPL", "2026-10-05 00:00:00", "2026-10-05 14:50:00", 30)
        self.assertEqual(gaps, [("2026-10-05 14:40:00", "2026-10-05 14:50:00")])

    def test_token_db_separate(self):
        import os, stat, tempfile
        d = tempfile.mkdtemp()
        data = db.connect(os.path.join(d, "k.db"))
        db.kv_set(data, "access_token", "leaked")
        data = db.connect(os.path.join(d, "k.db"))  # 예전 버전이 남긴 토큰은 시작 시 제거
        self.assertIsNone(db.kv_get(data, "access_token"))
        tok = db.connect_token(os.path.join(d, "t.db"))
        db.kv_set(tok, "access_token", "t")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(d, "t.db")).st_mode), 0o600)

    def test_sessions(self):
        cal = {"today": {"date": "2026-10-05",
                         "regularMarket": {"startTime": "2026-10-05T22:30:00+09:00", "endTime": "2026-10-06T05:00:00+09:00"},
                         "preMarket": None}}
        self.assertEqual(db.save_sessions(self.con, cal), 1)
        self.assertEqual(db.in_session(self.con, "2026-10-05 13:30:00"), (True, None))
        self.assertEqual(db.in_session(self.con, "2026-10-05 20:00:00"), (False, None))
        self.assertEqual(db.in_session(self.con, "2026-10-05 13:00:00"), (False, "2026-10-05 13:30:00"))
        self.assertEqual(db.in_session(db.connect(":memory:"), "x"), (True, None))  # 캘린더 없으면 폴링


class TossTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")
        self.api = TossClient(self.con, "id", "secret", sleep=lambda s: None, min_interval=0)

    def test_429_then_ok_and_token_cached(self):
        with mock.patch("kingfish.toss.urlopen", side_effect=[resp({"access_token": "t1", "expires_in": 86400}),
                                                               http_err(429, "rate-limit-exceeded", 0),
                                                               resp({"result": [1]})]) as u:
            self.assertEqual(self.api.get("/x"), [1])
            self.assertEqual(u.call_count, 3)
            self.assertEqual(db.kv_get(self.con, "access_token"), "t1")
        with mock.patch("kingfish.toss.urlopen", side_effect=[resp({"result": [2]})]) as u:
            self.assertEqual(self.api.get("/x"), [2])  # 토큰 재발급 없음
            self.assertEqual(u.call_args[0][0].get_header("Authorization"), "Bearer t1")

    def test_401_reissues_token_once(self):
        db.kv_set(self.con, "access_token", "old")
        db.kv_set(self.con, "token_expires_at", "9999999999")
        with mock.patch("kingfish.toss.urlopen", side_effect=[http_err(401, "expired-token"),
                                                               resp({"access_token": "new", "expires_in": 86400}),
                                                               resp({"result": {"ok": 1}})]):
            self.assertEqual(self.api.get("/x"), {"ok": 1})
        self.assertEqual(db.kv_get(self.con, "access_token"), "new")

    def test_401_uses_token_another_process_issued(self):
        db.kv_set(self.con, "access_token", "old")
        db.kv_set(self.con, "token_expires_at", "9999999999")

        def side(req, timeout):
            if req.get_header("Authorization") == "Bearer old":
                db.kv_set(self.con, "access_token", "theirs")  # 다른 프로세스가 재발급한 상황
                raise http_err(401, "token-revoked")
            return resp({"result": 1})
        with mock.patch("kingfish.toss.urlopen", side_effect=side) as u:
            self.assertEqual(self.api.get("/x"), 1)
            self.assertEqual(u.call_count, 2)  # 토큰 발급 POST 없이 kv 토큰 재사용

    def test_gzip_body(self):
        db.kv_set(self.con, "access_token", "t")
        db.kv_set(self.con, "token_expires_at", "9999999999")
        with mock.patch("kingfish.toss.urlopen", side_effect=[resp({"result": [7]}, gz=True)]):
            self.assertEqual(self.api.get("/x"), [7])

    def test_4xx_raises(self):
        db.kv_set(self.con, "access_token", "t")
        db.kv_set(self.con, "token_expires_at", "9999999999")
        with mock.patch("kingfish.toss.urlopen", side_effect=[http_err(404, "stock-not-found")]):
            with self.assertRaises(TossError) as cm:
                self.api.get("/x")
            self.assertEqual(cm.exception.code, "stock-not-found")

    def test_before_param_encoded(self):
        db.kv_set(self.con, "access_token", "t")
        db.kv_set(self.con, "token_expires_at", "9999999999")
        with mock.patch("kingfish.toss.urlopen", side_effect=[resp({"result": {}})]) as u:
            self.api.candles("AAPL", before="2026-03-25T09:00:00+09:00")
            self.assertIn("before=2026-03-25T09%3A00%3A00%2B09%3A00", u.call_args[0][0].full_url)


class FakeApi:
    def __init__(self, candles):
        self.result, self.calls = {"candles": candles}, []

    def candles(self, symbol, before=None, count=200, interval="1m"):
        self.calls.append((symbol, before, count))
        return self.result


def at(ts):
    return lambda: db.epoch(ts)


class PipelineTest(unittest.TestCase):
    def setUp(self):
        self.con = db.connect(":memory:")

    def test_skips_in_progress_bar(self):
        api = FakeApi([candle("2026-10-05T21:07:00+09:00", 1, 1, 1, 1, 1),   # 12:07 UTC, 진행 중
                       candle("2026-10-05T21:06:00+09:00", 1, 1, 1, 1, 1)])  # 12:06 UTC, 닫힘
        p = Pipeline({"symbols": ["AAPL"]}, self.con, api, clock=at("2026-10-05 12:06:05"))
        self.assertEqual(p.sync("AAPL", "poll", max_pages=1), 1)
        self.assertEqual(self.con.execute("SELECT ts FROM candles_1m").fetchall(), [("2026-10-05 12:06:00",)])
        self.assertEqual(self.con.execute("SELECT ts, complete FROM candles_5m").fetchall(), [("2026-10-05 12:10:00", 0)])

    def test_repair_task_covers_gap(self):
        api = FakeApi([candle("2026-10-05T23:05:00+09:00", 1, 1, 1, 1, 1)])
        p = Pipeline({"symbols": ["AAPL"]}, self.con, api, clock=at("2026-10-05 15:00:00"))
        p.enqueue("gap", "AAPL", "2026-10-05 14:00:00", "2026-10-05 17:20:00")
        self.assertEqual([t[2:] for t in p.queue], [("2026-10-05 14:00:00", "2026-10-05 17:10:00"),
                                                    ("2026-10-05 17:10:00", "2026-10-05 17:20:00")])
        p.queue = p.queue[:1]
        p.drain(float("inf"))
        self.assertEqual(api.calls, [("AAPL", "2026-10-06T02:11:00+09:00", 192)])
        self.assertTrue(db.covered(self.con, "AAPL", "2026-10-05 14:00:00", "2026-10-05 17:10:00"))
        self.assertEqual(p.queue, [])

    def test_fatal_keeps_task_queued(self):
        class Boom(FakeApi):
            def candles(self, *a, **k):
                raise TossError(403, "ip-not-allowed")
        p = Pipeline({"symbols": ["AAPL"]}, self.con, Boom([]), clock=at("2026-10-05 15:00:00"))
        p.enqueue("gap", "AAPL", "2026-10-05 14:00:00", "2026-10-05 14:10:00")
        with self.assertRaises(TossError):
            p.drain(float("inf"))
        self.assertEqual(len(p.queue), 1)


class ClassifyTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(classify(TossError(401, "expired-token")), "token")
        self.assertEqual(classify(TossError(401, "invalid_client")), "fatal")
        self.assertEqual(classify(TossError(400, "invalid_client")), "fatal")
        self.assertEqual(classify(TossError(0, "missing-credentials")), "fatal")
        self.assertEqual(classify(TossError(403, "forbidden")), "blocked")
        self.assertEqual(classify(TossError(404, "stock-not-found")), "symbol")
        self.assertEqual(classify(TossError(429, "rate-limit-exceeded")), "transient")
        self.assertEqual(classify(TossError(503, "x")), "transient")
        self.assertEqual(classify(ValueError()), "transient")

    def test_retry_after_http_date(self):
        con = db.connect(":memory:")
        db.kv_set(con, "access_token", "t")
        db.kv_set(con, "token_expires_at", "9999999999")
        waits = []
        api = TossClient(con, "id", "secret", sleep=waits.append, min_interval=0)
        e = http_err(429, "rate-limit-exceeded")
        e.headers["Retry-After"] = "Wed, 21 Oct 2026 07:28:00 GMT"
        with mock.patch("kingfish.toss.urlopen", side_effect=[e, resp({"result": 1})]):
            self.assertEqual(api.get("/x"), 1)
        self.assertIn(1.0, waits)


class EnvTest(unittest.TestCase):
    def test_load_env(self):
        import os, tempfile
        from .__main__ import load_env
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("# comment\nTOSS_CLIENT_ID = 'abc'\nTOSS_CLIENT_SECRET=s=1\n\nBROKEN\n")
        os.environ.pop("TOSS_CLIENT_ID", None)
        os.environ["TOSS_CLIENT_SECRET"] = "keep"
        load_env(f.name)
        self.assertEqual(os.environ["TOSS_CLIENT_ID"], "abc")
        self.assertEqual(os.environ["TOSS_CLIENT_SECRET"], "keep")  # 기존 환경변수 우선
        load_env("/nonexistent/.env")  # 없으면 무시


if __name__ == "__main__":
    unittest.main()
