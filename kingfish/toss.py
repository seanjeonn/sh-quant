"""토스증권 Open API 클라이언트 (stdlib urllib). 토큰은 SQLite kv로 프로세스 간 공유."""
import gzip
import json
import logging
import time
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from . import db

log = logging.getLogger("kingfish.toss")
BASE = "https://openapi.tossinvest.com"
AUTH_ERRORS = {"expired-token", "token-revoked", "invalid-token"}


class TossError(Exception):
    def __init__(self, status, code, message="", request_id=None):
        super().__init__(f"{status} {code}: {message} (requestId={request_id})")
        self.status, self.code, self.request_id = status, code, request_id


def _body(resp):
    """응답 본문 → JSON. 서버가 Accept-Encoding 없이도 gzip으로 내려주므로 직접 해제."""
    raw = resp.read()
    if (resp.headers or Message()).get("Content-Encoding") == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw or b"{}")


def _parse_error(e: HTTPError):
    try:
        body = _body(e)
    except (ValueError, OSError):
        body = {}
    err = body.get("error")
    if isinstance(err, dict):  # API envelope
        return err.get("code", ""), err.get("message", ""), err.get("requestId")
    # OAuth 형식: {"error": "invalid_client", "error_description": ...}
    return str(err or ""), body.get("error_description", ""), None


class TossClient:
    def __init__(self, con, client_id, client_secret, sleep=time.sleep, min_interval=0.06):
        self.con, self.client_id, self.client_secret = con, client_id, client_secret
        self.sleep, self.min_interval = sleep, min_interval  # ponytail: 고정 간격, 토큰버킷 필요 시 X-RateLimit-Remaining 참조

    # --- 저수준 전송: 429/5xx/네트워크 재시도 ---
    def _send(self, req, retries=5):
        last = None
        for attempt in range(retries + 1):
            self.sleep(self.min_interval)
            try:
                with urlopen(req, timeout=15) as r:
                    return _body(r)
            except HTTPError as e:
                code, msg, rid = _parse_error(e)
                if e.code == 429:
                    wait = float((e.headers or Message()).get("Retry-After") or 1)
                    log.warning("429 %s, retry in %.1fs", code, wait)
                    last = TossError(e.code, code, msg, rid)
                    self.sleep(wait)
                    continue
                if e.code >= 500:
                    last = TossError(e.code, code, msg, rid)
                else:
                    raise TossError(e.code, code, msg, rid) from None
            except (URLError, OSError, ValueError) as e:  # 네트워크·타임아웃·깨진 JSON
                last = e
            wait = 2 ** attempt
            log.warning("%s failed (%s), retry in %ss", req.full_url, last, wait)
            self.sleep(wait)
        raise TossError(0, "retries-exhausted", str(last))

    # --- 토큰 ---
    def _issue_token(self):
        if not (self.client_id and self.client_secret):
            raise TossError(0, "missing-credentials", "TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 환경변수가 필요합니다")
        body = urlencode({"grant_type": "client_credentials", "client_id": self.client_id,
                          "client_secret": self.client_secret}).encode()
        req = Request(BASE + "/oauth2/token", data=body,
                      headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        data = self._send(req)
        tok = data["access_token"]
        db.kv_set(self.con, "access_token", tok)
        db.kv_set(self.con, "token_expires_at", str(time.time() + int(data.get("expires_in", 86400))))
        log.info("issued new access token")
        return tok

    def _token(self):
        tok, exp = db.kv_get(self.con, "access_token"), db.kv_get(self.con, "token_expires_at")
        if tok and exp and float(exp) - time.time() > 300:
            return tok
        return self._issue_token()

    # --- 공개 API ---
    def get(self, path, **params):
        qs = urlencode({k: v for k, v in params.items() if v is not None})
        url = BASE + path + ("?" + qs if qs else "")
        tok = self._token()
        for _ in range(2):
            req = Request(url, headers={"Authorization": f"Bearer {tok}", "Accept": "application/json", "Accept-Encoding": "gzip"})
            try:
                return self._send(req)["result"]
            except TossError as e:
                if e.status != 401 or e.code not in AUTH_ERRORS:
                    raise
                # 다른 프로세스가 이미 재발급했으면 그 토큰을 쓰고, 아니면 직접 재발급
                fresh = db.kv_get(self.con, "access_token")
                tok = fresh if fresh and fresh != tok else self._issue_token()
        raise TossError(401, "auth-retry-failed", "토큰 재발급 후에도 401")

    def candles(self, symbol, before=None, count=200, interval="1m"):
        return self.get("/api/v1/candles", symbol=symbol, interval=interval, count=count, before=before)

    def calendar_us(self, date=None):
        return self.get("/api/v1/market-calendar/US", date=date)

    def stocks(self, symbols):
        return self.get("/api/v1/stocks", symbols=",".join(symbols))
