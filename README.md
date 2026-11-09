# sh-quant

매일 새 전략 하나를 백테스트하고 기록한다. Hermes Agent가 자동으로 돌리고, Vercel 단일 페이지(`index.html`)가 `results/`를 보여준다.

## 로컬
```sh
uv sync
uv run pytest -q engine                               # 룩어헤드·비용 테스트
uv run python run.py strategies/2026-11-09_sma_cross.py
python3 -m http.server 8787                           # http://localhost:8787
```

## 구조
- `engine/` 고정 규칙(유니버스, t+1 체결, 비용, IS ~2022 / OOS 2023~). 에이전트 수정 금지.
- `strategies/<date>_<slug>.py` 하루 1개. `META` + `signal(df) -> 0~1`.
- `results/` `run.py`가 쓴다. `index.json`은 요약, `<id>.json`은 주간 에퀴티 커브.
- `backlog.md` 사람이 넣는 아이디어 큐. 비면 에이전트가 자율 생성.
- `news.py` 헤드라인을 `data/news/`에 매일 축적(뉴스 전략용).

## Vercel
repo 연결만 하면 된다. `vercel.json`이 `index.html`과 `results/`만 `public/`으로 복사해 배포.

## Hermes 자동화
1. 스킬 설치: `mkdir -p ~/.hermes/skills/daily-backtest && cp hermes/SKILL.md ~/.hermes/skills/daily-backtest/`
2. Hermes에서 cron 작업 생성 (스킬 `daily-backtest` 첨부, 매일 07:00 KST, 작업 디렉터리 = 이 repo).
   cron 세션은 대화 기억이 없으므로 프롬프트에 repo 경로를 명시: `"<repo 경로>에서 daily-backtest 스킬 절차를 수행"`.
   문법: https://hermes-agent.nousresearch.com/docs/user-guide/features/cron
3. 스케줄러 실행 중인지 확인 후, 먼저 수동 1회 실행해 커밋·푸시·배포까지 확인.
