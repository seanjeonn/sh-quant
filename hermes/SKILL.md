---
name: daily-backtest
description: sh-quant 일일 루프 — 새 전략 1개 작성, 백테스트, 교훈 기록, 커밋/푸시
---

# 일일 백테스트 루프

repo: sh-quant 저장소 루트에서 실행. 명령은 `cargo run --release -q -- <command>` (아래에서는 `Q`로 표기).

## 규칙 (위반 금지)
- **쓰기 허용**: `strategies/<YYYY-MM-DD>_<slug>.toml` 새 파일, `backlog.md` 체크 표시, `Q`가 만든 `results/`·`data/news/`.
- **수정 금지**: `src/`, `Cargo.*`, `index.html`, 기존 전략 파일, 기존 결과. 엔진이나 DSL이 부족하면 고치지 말고 lesson에 "필요한 함수: ..."로 적는다.
- 하루 전략 1개. 날짜는 오늘(Asia/Seoul).

## 전략 형식 (TOML)
```toml
name = "EMA 20/60 크로스"
hypothesis = "검증할 한 문장"
tags = ["trend", "single"]
parents = []          # 앙상블이면 사용한 전략 id
source = "backlog"    # 또는 "agent"
signal = "ema(close, 20) > ema(close, 60)"
```
`signal`은 당일 종가까지의 데이터로 정한 포지션(0~1). 엔진이 다음 날 적용한다. 참/거짓은 1/0, 숫자는 0~1로 잘린다.

- 시리즈: `open high low close volume`
- 연산: `+ - * /`, `< > <= >= == !=`, `and or not`, 괄호, 숫자
- 함수 (n은 1 이상 정수 리터럴):
  - `sma(x, n)` `ema(x, n)` `std(x, n)`(n≥2) `max(x, n)` `min(x, n)` — 최근 n봉
  - `rsi(x, n)` — Wilder RSI
  - `lag(x, n)` — n봉 전 값, `pct(x, n)` — n봉 수익률
  - `latch(진입, 청산)` — 진입 조건부터 청산 조건까지 1 유지
  - `hold(조건, n)` — 조건 발생 봉부터 n봉 동안 1
  - `clip(x, lo, hi)`
  - `ref("<전략 id>")` — 다른 전략의 최종 신호 (앙상블)
- 예시:
  - RSI 평균회귀: `latch(rsi(close, 14) < 30, rsi(close, 14) > 70)`
  - 돈치안: `latch(close > lag(max(high, 55), 1), close < lag(min(low, 20), 1))`
  - 변동성 타기팅: `clip(0.15 / (std(pct(close, 1), 20) * 15.87), 0, 1)`
  - 앙상블 투표: `(ref("2026-11-09_sma_cross") + ref("2026-11-10_rsi") + ref("2026-11-11_donchian")) / 3 >= 0.5`

## 절차
1. `git pull --rebase` 후 `Q news` (뉴스 축적, 실패해도 계속)
2. 전략 고르기
   - `backlog.md`에 `- [ ]` 항목이 있으면 맨 위 것을 구현하고 `- [x]`로 바꾼다. `source = "backlog"`.
   - 없으면 `results/index.json`을 읽고 가설을 직접 만든다. `source = "agent"`.
     - 참고: 미국/한국 각각 OOS Sharpe 상위 5개, 최근 7개(실패 포함)의 `hypothesis`·`lesson`.
     - 단계: 단일 기법이 15개 미만이면 단일 기법(`tags`에 `single`). 이후 상위 전략을 `ref()`로 조합하는 앙상블(`ensemble`, `parents`에 id 기록) 비중을 늘린다.
     - 이미 해본 것과 파라미터만 살짝 다른 전략은 피한다.
3. `strategies/<date>_<slug>.toml` 작성
4. `Q run strategies/<file>.toml`
   - 에러 메시지를 보고 최대 3번 수정. 그래도 실패면 `Q fail strategies/<file>.toml "<원인 한 줄>"`.
5. 출력된 IS/OOS 지표를 Buy&Hold(`bh_cagr`)와 비교해 교훈 한 줄 기록:
   `Q lesson <id> "<무엇이 통했/안 통했고 다음엔 무엇을 시도할지>"`
   - IS가 OOS보다 훨씬 좋으면 과최적화 의심이라고 적는다.
6. `git add strategies backlog.md results data/news && git commit -m "strategy: <id>" && git push`
   - push 충돌 시 `git pull --rebase` 후 다시 push. 그래도 안 되면 중단하고 보고.
7. 결과를 3줄로 보고: 전략명, 미국/한국 OOS Sharpe vs B&H, 교훈.
