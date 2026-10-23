"""python3 -m unittest kingfish.test_kingfish -v  (네트워크 없음)"""
import io
import json
import sqlite3
import unittest
from email.message import Message
from unittest import mock
from urllib.error import HTTPError

from . import db
from .toss import TossClient, TossError


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
        self.assertEqual(r, ("AAPL", "2026-10-05 13:35:00", 10.0, 24.0, 4.6, 15.0, 500.0, 5))
        r = self.con.execute("SELECT n_bars FROM candles_5m WHERE ts='2026-10-05 13:40:00'").fetchone()
        self.assertEqual(r, (1,))
        # 사후 정정된 봉 upsert → 재집계에 반영
        db.upsert_1m(self.con, [("AAPL", "2026-10-05 13:35:00", 14, 99, 4.6, 15, 100)])
        db.rollup_5m(self.con, "AAPL", "2026-10-05 13:35:00", "2026-10-05 13:35:00")
        self.assertEqual(self.con.execute("SELECT high FROM candles_5m WHERE ts='2026-10-05 13:35:00'").fetchone(), (99.0,))

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
