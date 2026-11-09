# sh-quant

매일 새 전략 하나를 백테스트하고 기록한다. Hermes Agent가 자동으로 돌리고, Vercel 단일 페이지(`index.html`)가 `results/`를 보여준다.

## 로컬
```sh
cargo test                                                        # DSL·엔진 테스트
cargo run --release -- run strategies/2026-11-09_sma_cross.toml   # 백테스트 + 기록
cargo run --release -- news                                       # 헤드라인 수집
python3 -m http.server 8787                                       # http://localhost:8787
```

## 구조
- `src/` Rust 엔진. 에이전트 수정 금지.
  - `expr.rs` 전략 DSL (미래 참조 연산자 없음)
  - `backtest.rs` 고정 규칙: t+1 체결, 비용(US 0.05% / KR 0.25%), 동일가중, IS ~2022 / OOS 2023~
  - `data.rs` 유니버스(US/KR 각 12종목), Yahoo 일봉(배당·분할 조정) → `data/cache/`
  - `news.rs` 헤드라인을 `data/news/`에 매일 축적
- `strategies/<date>_<slug>.toml` 하루 1개. 형식·함수 목록은 `hermes/SKILL.md`.
- `results/` CLI가 쓴다. `index.json`은 요약, `<id>.json`은 주간 에퀴티 커브.
- `backlog.md` 사람이 넣는 아이디어 큐. 비면 에이전트가 자율 생성.

## Vercel
`vercel.json`이 `index.html`과 `results/`만 `public/`으로 복사해 배포. Rust는 빌드하지 않는다.

## Hermes 자동화 (Hermes가 도는 맥)
1. Rust 설치: `brew install rust` (또는 rustup)
2. 스킬 링크: `mkdir -p ~/.hermes/skills/daily-backtest && ln -sf <repo>/hermes/SKILL.md ~/.hermes/skills/daily-backtest/SKILL.md`
3. cron 작업: 스킬 `daily-backtest`, 매일 07:00 KST, 프롬프트에 repo 경로 명시.
   문법: https://hermes-agent.nousresearch.com/docs/user-guide/features/cron
