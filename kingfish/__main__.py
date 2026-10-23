import argparse
import logging
import os
import sys
import tomllib
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import db
from .pipeline import Pipeline
from .toss import TossClient


def main():
    p = argparse.ArgumentParser(prog="kingfish")
    p.add_argument("--config", default="config.toml")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="상시 수집 루프")
    sub.add_parser("repair", help="최근 repair_days 재동기화")
    sub.add_parser("status", help="수집 상태 출력")
    sub.add_parser("backfill", help="과거 1분봉 백필").add_argument("--since", required=True, help="YYYY-MM-DD")
    a = p.parse_args()

    logdir = Path.home() / "Library" / "Logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[RotatingFileHandler(logdir / "kingfish.log", maxBytes=10_000_000, backupCount=5),
                                  logging.StreamHandler(sys.stderr)])

    with open(a.config, "rb") as f:
        cfg = tomllib.load(f)
    if a.cmd != "status" and not (os.environ.get("TOSS_CLIENT_ID") and os.environ.get("TOSS_CLIENT_SECRET")):
        sys.exit("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 환경변수가 필요합니다")
    con = db.connect(cfg["db_path"])
    api = TossClient(con, os.environ.get("TOSS_CLIENT_ID"), os.environ.get("TOSS_CLIENT_SECRET"))
    pipe = Pipeline(cfg, con, api)
    {"run": pipe.run, "repair": pipe.repair, "status": pipe.status,
     "backfill": lambda: pipe.backfill(a.since)}[a.cmd]()


if __name__ == "__main__":
    main()
