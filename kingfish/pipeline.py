"""수집 루프·재동기화·상태 보고."""
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import db
from .toss import TossError, classify

log = logging.getLogger("kingfish")
NY = ZoneInfo("America/New_York")
GRACE = 5           # 봉 종료 후 이 초가 지나야 저장 (진행 중인 봉 제외)
CHUNK_MIN = 190     # repair 작업 1건 = 1요청(count<=200)으로 덮을 분 수
AFTER_SESSION = 130  # 세션 종료 후에도 폴링하는 초: 마지막 봉 수집 + 마지막 5분봉 complete


class Pipeline:
    def __init__(self, cfg, con, api, clock=time.time):
        self.cfg, self.con, self.api, self.clock = cfg, con, api, clock
        self.symbols = [s.upper() for s in cfg["symbols"]]
        self.queue = []  # repair 작업 (job, symbol, start, end). 폴링 사이 남는 시간에만 소비

    def now(self):
        return db.fmt(self.clock())

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

    def sync(self, symbol, job, count=200, since=None, max_pages=None, before=None):
        """`before`부터 과거로 페이지네이션. since(UTC 문자열) 이전 봉에 닿으면 중단.
        닫힌 봉만 저장. 저장 건수 반환, 실패 시 None."""
        started, total, pages = db.now_utc(), 0, 0
        cutoff = db.fmt(self.clock() - GRACE)
        try:
            while True:
                r = self.api.candles(symbol, before=before, count=count)
                bars = [x for x in (db.normalize(symbol, c) for c in r.get("candles", [])) if x]
                n, lo, hi = db.upsert_1m(self.con, [x for x in bars if x[1] <= cutoff])
                if n:
                    db.rollup_5m(self.con, symbol, lo, hi, self.now())
                total += n
                pages += 1
                before = r.get("nextBefore")
                if not bars or not before or (since and min(x[1] for x in bars) < since) or (max_pages and pages >= max_pages):
                    break
            db.log_sync(self.con, job, symbol, started, True, total)
            return total
        except Exception as e:  # 심볼 하나의 실패가 나머지를 막지 않도록
            log.error("%s %s failed after %d rows: %s", job, symbol, total, e)
            db.log_sync(self.con, job, symbol, started, False, total, str(e))
            if classify(e) in ("fatal", "blocked"):
                raise  # 자격증명·IP 차단은 심볼과 무관하므로 전체 중단
            return None

    def poll(self):
        n = sum(self.sync(s, "poll", count=self.cfg.get("poll_overlap", 30), max_pages=1) or 0 for s in self.symbols)
        log.info("poll: %d bars", n)

    def resync_all(self, since, job):
        n = sum(self.sync(s, job, since=since) or 0 for s in self.symbols)
        log.info("%s since %s: %d bars", job, since, n)

    def repair(self):
        """CLI용 전체 재동기화 (최근 repair_days)."""
        since = db.fmt(self.clock() - self.cfg.get("repair_days", 3) * 86400)
        self.resync_all(since, "repair")

    def backfill(self, since_date):
        self.resync_all(f"{since_date} 00:00:00", "backfill")

    # --- repair 큐 ---
    def enqueue(self, job, symbol, start, end, skip_covered=False):
        a, b = db.epoch(start), db.epoch(end)
        while a < b:
            c = min(a + CHUNK_MIN * 60, b)
            task = (job, symbol, db.fmt(a), db.fmt(c))
            if not (skip_covered and db.covered(self.con, symbol, task[2], task[3])):
                self.queue.append(task)
            a = c

    def queued(self, symbol, start, end):
        return any(t[1] == symbol and t[2] < end and start < t[3] for t in self.queue)

    def run_task(self, job, symbol, start, end):
        minutes = int(db.epoch(end) - db.epoch(start)) // 60
        n = self.sync(symbol, job, count=minutes + 2, max_pages=1, before=db.to_api(db.fmt(db.epoch(end) + 60)))
        if n is not None:  # 이 구간은 조회 완료 → 다음 공백 탐색에서 제외
            db.log_sync(self.con, "cover", symbol, start, True, n, finished=end)

    def drain(self, deadline):
        while self.queue and time.time() < deadline:
            self.run_task(*self.queue[0])  # fatal/blocked면 예외로 빠지고 작업은 큐에 남는다
            self.queue.pop(0)

    def plan_repairs(self):
        """매시간: 수집 공백·정규장 결손만 재조회. 하루 1회: 끝난 마지막 거래일 전체(사후 정정 반영)."""
        if self.queue:
            log.warning("repair queue still has %d tasks, skip planning", len(self.queue))
            return
        now = self.clock()
        since = db.fmt(now - self.cfg.get("repair_days", 3) * 86400)
        until = db.fmt(now - 120)
        day = self.con.execute("SELECT date FROM market_sessions GROUP BY date HAVING MAX(end_ts)<=?"
                               " ORDER BY date DESC LIMIT 1", (until,)).fetchone()
        if day and db.kv_get(self.con, "last_daily_resync") != day[0]:
            for st, en in self.con.execute("SELECT start_ts,end_ts FROM market_sessions WHERE date=? ORDER BY start_ts",
                                           day).fetchall():
                for s in self.symbols:
                    self.enqueue("daily", s, st, en)
            # ponytail: 큐에 넣는 시점에 기록 → 소비 도중 재시작하면 그날 정정분은 CLI repair로 보완
            db.kv_set(self.con, "last_daily_resync", day[0])
        # 이미 큐에 있는 구간과 겹치면 건너뜀. 덜 메워진 부분은 다음 시간 탐색에서 다시 잡힌다
        for s in self.symbols:
            for a, b in db.coverage_gaps(self.con, s, since, until, self.cfg.get("poll_overlap", 30)):
                if not self.queued(s, a, b):
                    self.enqueue("gap", s, a, b)
            # ponytail: API에도 없는 결손(거래정지 등)은 cover 기록으로 1회만 재조회, 이후 재시도 안 함
            for st, en, missing in db.regular_gaps(self.con, s, since, until):
                if missing and not self.queued(s, st, en):
                    self.enqueue("gap", s, st, en, skip_covered=True)
        log.info("repair planned: %d tasks", len(self.queue))

    # --- 메인 루프 ---
    def run(self):
        self.validate_symbols()
        next_hourly, backoff = 0, 60
        while True:
            try:
                now = time.time()
                if now >= next_hourly:
                    self.refresh_calendar()
                    self.plan_repairs()
                    next_hourly = (now // 3600 + 1) * 3600
                active, nxt = db.in_session(self.con, db.fmt(now))
                active = active or db.in_session(self.con, db.fmt(now - AFTER_SESSION))[0]
                if active:
                    self.poll()
                    self.drain((time.time() // 60 + 1) * 60 - 5)  # 다음 폴링(:05) 10초 전까지만
                    time.sleep(max(1, 65 - time.time() % 60))  # 다음 분 :05초
                else:
                    self.drain(float("inf"))
                    wait = 3600
                    if nxt:
                        wait = min(wait, max(5, db.epoch(nxt) - time.time() + 5))
                    log.info("market closed, next session %s, sleeping %ds", nxt, wait)
                    time.sleep(wait)
                backoff = 60
            except TossError as e:
                kind = classify(e)
                if kind == "fatal":
                    wait = 1800  # 프로세스를 끝내면 launchd가 30초마다 재기동하므로 살아서 대기
                elif kind == "blocked":
                    wait, backoff = backoff, min(backoff * 2, 1800)
                else:
                    wait = 60
                log.error("%s error, retrying in %ds: %s", kind, wait, e)
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
        print(f"{'symbol':8} {'last_1m(UTC)':20} {'last_5m_complete':20} {'bars_24h':>8} {'last_ok_sync':20} {'err_24h':>7} {'reg_gaps_3d':>11}")
        for s in self.symbols:
            l1 = con.execute("SELECT MAX(ts) FROM candles_1m WHERE symbol=?", (s,)).fetchone()[0] or "-"
            l5 = con.execute("SELECT MAX(ts) FROM candles_5m WHERE symbol=? AND complete=1", (s,)).fetchone()[0] or "-"
            b24 = con.execute("SELECT COUNT(*) FROM candles_1m WHERE symbol=? AND ts>?", (s, day_ago)).fetchone()[0]
            ok = con.execute("SELECT MAX(finished) FROM sync_log WHERE symbol=? AND ok=1 AND job!='cover'", (s,)).fetchone()[0] or "-"
            err = con.execute("SELECT COUNT(*) FROM sync_log WHERE symbol=? AND ok=0 AND finished>?", (s, day_ago)).fetchone()[0]
            gaps = sum(m for _, _, m in db.regular_gaps(con, s, three_days, now))
            print(f"{s:8} {l1:20} {l5:20} {b24:8d} {ok:20} {err:7d} {gaps:11d}")
        errs = con.execute("SELECT finished,job,symbol,error FROM sync_log WHERE ok=0 ORDER BY id DESC LIMIT 5").fetchall()
        if errs:
            print("\nrecent errors:")
            for row in errs:
                print("  ", *row)
        active, nxt = db.in_session(con, now)
        print(f"\nsession active: {active}   next session start(UTC): {nxt}")
