import argparse
import logging
import os
import sys
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import db
from .pipeline import Pipeline
from .toss import TossClient, TossError


def load_env(path=".env"):
    """KEY=VALUE 줄을 os.environ에 넣는다(이미 설정된 변수는 유지). 파일 없으면 무시."""
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def main():
    p = argparse.ArgumentParser(prog="kingfish")
    p.add_argument("--config", default="config.toml")
    p.add_argument("--env", default=".env")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="상시 수집 루프")
    sub.add_parser("repair", help="최근 repair_days 재동기화")
    sub.add_parser("status", help="수집 상태 출력")
    sub.add_parser("backfill", help="과거 1분봉 백필").add_argument("--since", required=True, help="YYYY-MM-DD")
    a = p.parse_args()
    load_env(a.env)

    logdir = Path.home() / "Library" / "Logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[RotatingFileHandler(logdir / "kingfish.log", maxBytes=10_000_000, backupCount=5),
                                  logging.StreamHandler(sys.stderr)])

    with open(a.config, "rb") as f:
        cfg = tomllib.load(f)
    if a.cmd != "status" and not (os.environ.get("TOSS_CLIENT_ID") and os.environ.get("TOSS_CLIENT_SECRET")):
        sys.exit("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 가 필요합니다 (.env 또는 환경변수)")
    con = db.connect(cfg["db_path"])
    api = TossClient(con, os.environ.get("TOSS_CLIENT_ID"), os.environ.get("TOSS_CLIENT_SECRET"))
    pipe = Pipeline(cfg, con, api)
    try:
        if a.cmd in ("repair", "backfill"):
            pipe.refresh_calendar()  # status의 정규장 결손 집계가 캘린더를 쓴다
        {"run": pipe.run, "repair": pipe.repair, "status": pipe.status,
         "backfill": lambda: pipe.backfill(a.since)}[a.cmd]()
    except TossError as e:
        sys.exit(f"중단: {e}")


if __name__ == "__main__":
    main()
