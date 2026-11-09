---
name: daily-backtest
description: sh-quant 일일 루프 — 새 전략 1개 작성, 백테스트, 교훈 기록, 커밋/푸시
---

# 일일 백테스트 루프

repo: 이 파일이 있는 sh-quant 저장소 루트에서 실행. 명령은 `uv run`으로.

## 규칙 (위반 금지)
- **쓰기 허용**: `strategies/<YYYY-MM-DD>_<slug>.py` 새 파일, `backlog.md` 체크 표시, `run.py`가 만든 `results/`, `news.py`가 만든 `data/news/`.
- **수정 금지**: `engine/`, `run.py`, `index.html`, 기존 전략 파일, 기존 결과. 엔진이 마음에 안 들면 고치지 말고 lesson에 적는다.
- 하루 전략 1개. 날짜는 오늘(Asia/Seoul).
- 미래 데이터 사용 금지 (`shift(-n)`, 전체 기간 통계로 정규화 등). 엔진이 truncation 검사로 거부한다.

## 절차
1. `git pull --rebase` 후 `uv run python news.py` (뉴스 축적, 실패해도 계속)
2. 전략 고르기
   - `backlog.md`에 `- [ ]` 항목이 있으면 맨 위 것을 구현하고 `- [x]`로 바꾼다. `META["source"] = "backlog"`.
   - 없으면 `results/index.json`을 읽고 가설을 직접 만든다. `META["source"] = "agent"`.
     - 참고: 미국/한국 각각 OOS Sharpe 상위 5개, 최근 7개(실패 포함)의 `hypothesis`·`lesson`.
     - 단계: 단일 기법이 15개 미만이면 단일 기법(`tags`에 `single`). 이후 상위 전략 조합(`ensemble`, `parents`에 원본 id 기록, 원본 파일을 `importlib`로 불러 signal 재사용) 비중을 늘린다.
     - 이미 해본 것과 파라미터만 살짝 다른 전략은 피한다.
3. `strategies/<date>_<slug>.py` 작성:
   ```python
   import pandas as pd
   META = {"name": "...", "hypothesis": "검증할 한 문장", "tags": ["..."], "parents": [], "source": "agent"}
   def signal(df: pd.DataFrame) -> pd.Series:  # Open/High/Low/Close/Volume → 0~1 포지션 (당일 종가 기준 결정)
       ...
   ```
4. `uv run python run.py strategies/<file>.py`
   - 실패하면 원인을 고쳐 최대 3번 재시도. 그래도 실패면 `uv run python run.py fail strategies/<file>.py "<원인 한 줄>"`.
5. 출력된 IS/OOS 지표를 Buy&Hold와 비교해 교훈 한 줄 기록:
   `uv run python run.py lesson <id> "<무엇이 통했/안 통했고 다음엔 무엇을 시도할지>"`
   - IS가 OOS보다 훨씬 좋으면 과최적화 의심이라고 적는다.
6. `git add strategies backlog.md results data/news && git commit -m "strategy: <id>" && git push`
   - push 충돌 시 `git pull --rebase` 후 다시 push. 그래도 안 되면 중단하고 보고.
7. 결과를 3줄로 보고: 전략명, 미국/한국 OOS Sharpe vs B&H, 교훈.
