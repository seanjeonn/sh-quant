"""Usage:
  python run.py strategies/<id>.py            backtest + record
  python run.py lesson <id> "<one line>"      attach a lesson to a result
  python run.py fail strategies/<id>.py "<why>"  record a failed attempt
"""
import datetime as dt
import importlib.util
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
INDEX = RESULTS / "index.json"


def load_index() -> list[dict]:
    return json.loads(INDEX.read_text()) if INDEX.exists() else []


def save(entry: dict, detail: dict | None = None) -> None:
    RESULTS.mkdir(exist_ok=True)
    idx = [e for e in load_index() if e["id"] != entry["id"]] + [entry]
    idx.sort(key=lambda e: e["id"])
    INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=1, allow_nan=False))
    if detail is not None:
        (RESULTS / f"{entry['id']}.json").write_text(json.dumps(detail, ensure_ascii=False, allow_nan=False))


def load_strategy(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(mod)
    for k in ("name", "hypothesis"):
        if not mod.META.get(k):
            raise ValueError(f"META['{k}'] is required")
    return mod


def base_entry(path: Path, meta: dict) -> dict:
    return {"id": path.stem, "date": path.stem[:10] if path.stem[:4].isdigit() else str(dt.date.today()),
            "name": meta.get("name", path.stem), "hypothesis": meta.get("hypothesis", ""),
            "tags": meta.get("tags", []), "parents": meta.get("parents", []),
            "source": meta.get("source", "agent"), "lesson": None}


def cmd_run(path: Path) -> None:
    from engine import data
    from engine.backtest import run_market
    mod = load_strategy(path)
    entry = base_entry(path, mod.META) | {"status": "ok", "markets": {}}
    detail = {"id": entry["id"], "curves": {}}
    for m in ("US", "KR"):
        r = run_market(mod.signal, data.load(m), m)
        entry["markets"][m] = r["metrics"]
        detail["curves"][m] = r["curve"]
    old = next((e for e in load_index() if e["id"] == entry["id"]), None)
    if old:
        entry["lesson"] = old.get("lesson")
    save(entry, detail)
    print(json.dumps(entry["markets"], indent=1))


def cmd_fail(path: Path, why: str) -> None:
    try:
        meta = load_strategy(path).META
    except Exception:
        meta = {}
    save(base_entry(path, meta) | {"status": "failed", "error": why, "markets": {}})


def cmd_lesson(sid: str, text: str) -> None:
    idx = load_index()
    hit = [e for e in idx if e["id"] == sid]
    if not hit:
        sys.exit(f"no result with id {sid}")
    hit[0]["lesson"] = text
    save(hit[0])


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["lesson"] and len(a) == 3:
        cmd_lesson(a[1], a[2])
    elif a[:1] == ["fail"] and len(a) == 3:
        cmd_fail(Path(a[1]), a[2])
    elif len(a) == 1:
        try:
            cmd_run(Path(a[0]))
        except Exception:
            traceback.print_exc()
            sys.exit(1)
    else:
        sys.exit(__doc__)
