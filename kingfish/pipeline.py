"""수집 루프·재동기화·상태 보고."""
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import db
from .toss import TossError

log = logging.getLogger("kingfish")
NY = ZoneInfo("America/New_York")


class Pipeline:
    def __init__(self, cfg, con, api):
        self.cfg, self.con, self.api = cfg, con, api
        self.symbols = [s.upper() for s in cfg["symbols"]]

    # --- 개별 작업 ---
    def refresh_calendar(self):
        today = datetime.now(NY).date().isoformat()
        n = db.save_sessions(self.con, self.api.calendar_us(today))
        log.info("calendar refreshed: %d sessions", n)

    def validate_symbols(self):
        try:
            found = {s["symbol"].upper(): s for s in self.api.stocks(self.symbols)}
        except TossError as e:
            log.warning("symbol validation skipped: %s", e)
            return
        for s in list(self.symbols):
            info = found.get(s)
            if not info:
                log.error("unknown symbol %s — removed from universe", s)
                self.symbols.remove(s)
            elif info.get("status") != "ACTIVE":
                log.warning("symbol %s status=%s", s, info.get("status"))

    def sync(self, symbol, job, count=200, since=None, max_pages=None):
        """최신 봉부터 `before` 페이지네이션. since(UTC 문자열) 이전 봉에 닿으면 중단. 저장 건수 반환."""
        started, total, before, pages = db.now_utc(), 0, None, 0
        try:
            while True:
                r = self.api.candles(symbol, before=before, count=count)
                rows = [x for x in (db.normalize(symbol, c) for c in r.get("candles", [])) if x]
                n, lo, hi = db.upsert_1m(self.con, rows)
                if n:
                    db.rollup_5m(self.con, symbol, lo, hi)
                total += n
                pages += 1
                before = r.get("nextBefore")
                if not rows or not before or (since and lo < since) or (max_pages and pages >= max_pages):
                    break
            db.log_sync(self.con, job, symbol, started, True, total)
        except Exception as e:  # 심볼 하나의 실패가 나머지를 막지 않도록
            log.error("%s %s failed after %d rows: %s", job, symbol, total, e)
            db.log_sync(self.con, job, symbol, started, False, total, str(e))
            if isinstance(e, TossError) and e.status in (401, 403):
                raise  # 인증·IP 차단은 심볼과 무관하므로 전체 중단
        return total

    def poll(self):
        n = sum(self.sync(s, "poll", count=self.cfg.get("poll_overlap", 30), max_pages=1) for s in self.symbols)
        log.info("poll: %d bars", n)

    def resync_all(self, since, job):
        n = sum(self.sync(s, job, since=since) for s in self.symbols)
        log.info("%s since %s: %d bars", job, since, n)

    def repair(self):
        since = (datetime.now(db.UTC) - timedelta(days=self.cfg.get("repair_days", 3))).strftime(db.FMT)
        self.resync_all(since, "repair")

    def backfill(self, since_date):
        self.resync_all(f"{since_date} 00:00:00", "backfill")

    # --- 메인 루프 ---
    def run(self):
        self.validate_symbols()
        next_hourly = 0
        while True:
            try:
                now = time.time()
                if now >= next_hourly:
                    self.refresh_calendar()
                    self.repair()
                    next_hourly = (now // 3600 + 1) * 3600
                active, nxt = db.in_session(self.con, db.now_utc())
                if active:
                    self.poll()
                    time.sleep(max(1, 65 - time.time() % 60))  # 다음 분 :05초
                else:
                    wait = 3600
                    if nxt:
                        nxt_epoch = datetime.strptime(nxt, db.FMT).replace(tzinfo=db.UTC).timestamp()
                        wait = min(wait, max(5, nxt_epoch - time.time() + 5))
                    log.info("market closed, next session %s, sleeping %ds", nxt, wait)
                    time.sleep(wait)
            except Exception:
                log.exception("loop error, retrying in 60s")
                time.sleep(60)

    # --- 상태 ---
    def status(self):
        con, now = self.con, db.now_utc()
        day_ago = (datetime.now(db.UTC) - timedelta(days=1)).strftime(db.FMT)
        three_days = (datetime.now(db.UTC) - timedelta(days=3)).strftime(db.FMT)
        print(f"now(UTC) {now}   db {self.cfg['db_path']}")
        print(f"{'symbol':8} {'last_1m(UTC)':20} {'last_5m(UTC)':20} {'bars_24h':>8} {'last_ok_sync':20} {'err_24h':>7} {'reg_gaps_3d':>11}")
        for s in self.symbols:
            l1 = con.execute("SELECT MAX(ts) FROM candles_1m WHERE symbol=?", (s,)).fetchone()[0] or "-"
            l5 = con.execute("SELECT MAX(ts) FROM candles_5m WHERE symbol=?", (s,)).fetchone()[0] or "-"
            b24 = con.execute("SELECT COUNT(*) FROM candles_1m WHERE symbol=? AND ts>?", (s, day_ago)).fetchone()[0]
            ok = con.execute("SELECT MAX(finished) FROM sync_log WHERE symbol=? AND ok=1", (s,)).fetchone()[0] or "-"
            err = con.execute("SELECT COUNT(*) FROM sync_log WHERE symbol=? AND ok=0 AND finished>?", (s, day_ago)).fetchone()[0]
            gaps = 0
            for st, en in con.execute("SELECT start_ts,end_ts FROM market_sessions WHERE session='regularMarket'"
                                      " AND end_ts<=? AND end_ts>?", (now, three_days)):
                expected = int((datetime.strptime(en, db.FMT) - datetime.strptime(st, db.FMT)).total_seconds() // 60)
                have = con.execute("SELECT COUNT(*) FROM candles_1m WHERE symbol=? AND ts>? AND ts<=?", (s, st, en)).fetchone()[0]
                gaps += max(0, expected - have)
            print(f"{s:8} {l1:20} {l5:20} {b24:8d} {ok:20} {err:7d} {gaps:11d}")
        errs = con.execute("SELECT finished,job,symbol,error FROM sync_log WHERE ok=0 ORDER BY id DESC LIMIT 5").fetchall()
        if errs:
            print("\nrecent errors:")
            for row in errs:
                print("  ", *row)
        active, nxt = db.in_session(con, now)
        print(f"\nsession active: {active}   next session start(UTC): {nxt}")
