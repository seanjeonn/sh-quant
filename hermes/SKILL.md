---
name: daily-backtest
description: 매일 가설·기본형·파라미터 탐색·평가까지 전략 연구 한 세트를 완주한다.
version: 0.2.0
author: seanjeonn, Hermes Agent
platforms: [linux, macos]
metadata:
  hermes:
    tags: [backtest, research, investment, sh-quant]
---

# 일일 전략 연구 세트

목표는 Asia/Seoul 날짜 기준 **연구 세트 1개 완주**다. 파일 하나나 실행 한 번이 아니라 가설 → 사전 계획 → 기본형 → 복수 변형/최적화 → 후보 선택 → 평가 → 결론을 완료한다. 성과가 나쁜 가설도 근거 있는 기각으로 완료할 수 있다.

## When to Use

- sh-quant에서 오늘의 전략을 자율 선정하고 파라미터 탐색을 포함한 연구 한 세트를 수행할 때.
- 중단된 당일 세트를 재개하거나 완료 여부를 확인할 때.
- 엔진/데이터/대시보드 개발은 이 스킬의 연구 모드가 아니다. 별도 승인된 이슈·개발 브랜치에서 수행한다.

## Prerequisites

1. 저장소 루트에서 `read_file`로 `AGENTS.md`, `docs/github-workflow.md`, **`docs/daily-research-set.md` 전체**를 읽는다. 후자가 세트의 산출물·완료 기준을 정의한다.
2. `terminal`로 Git 상태·활성 브랜치·원격 PR/이슈를 확인한다. dirty worktree, 다른 작업과 충돌, 승인되지 않은 작업이면 중단한다.
3. Rust와 Cargo가 필요하다. `terminal(command="cargo test --locked")`가 통과해야 한다. 새 외부 데이터/유료 서비스/실거래는 별도 승인이 필요하다.

## Quick Reference

저장소 루트에서 `terminal`로 호출한다. 아래 `<...>`는 실제 ID/경로로 치환한다.

```text
cargo run --release --locked -q -- news
cargo run --release --locked -q -- run strategies/<run-id>.toml
cargo run --release --locked -q -- fail strategies/<run-id>.toml "<원인>"
cargo run --release --locked -q -- lesson <run-id> "<실제 결과에 근거한 교훈>"
```

현재 `sweep`, `research`, `--is-only`, `--holdout` 명령은 없다. 이미 구현된 것처럼 호출하거나 완료를 보고하지 않는다.

## Procedure

1. **시작·중복 방지.** KST 날짜와 `research/<date>_*`의 원격 PR/로컬 상태를 확인한다. 완료 세트가 있으면 그날 새 세트를 만들지 않는다. 진행/차단 세트는 기록된 상태에서 재개한다. 동시 실행을 금지하고 전용 브랜치를 사용한다. 강제 reset/rebase/push로 다른 작업을 덮어쓰지 않는다.
2. **가설 선정.** 과거 보고서의 기각/실패·교훈과 `backlog.md`를 읽는다. 미완료 큐의 첫 실행 가능한 가설을 우선하며, 다른 가설을 고르면 이유를 기록한다. 큐가 비면 중복되지 않는 가설을 자율 생성한다. 과거 OOS 결과를 참고했다면 노출 이력도 적고 새 실험을 독립적인 미관측 검증이라고 부르지 않는다. 출력: 가설과 선정 이유.
3. **데이터 준비·추적·사전 계획.** 먼저 필요한 일봉 캐시를 확보·검증하고 파일 해시·대상·기간·수집 기준시각·snapshot 위치를 manifest에 확정한다. 현재 data-only 준비 명령은 없으므로 이 조건을 만족할 수 없으면 `data_setup`으로 차단하고 별도 준비 작업을 선행한다. 중복을 검색한 뒤 feature 양식으로 오늘 연구의 추적 이슈를 만든다. `hermes/templates/plan.json`을 복사해 `research/<set-id>/plan.json`의 모든 TODO/null을 실제 값으로 채운다. `write_file`/`patch`를 사용한다. baseline, 최소 2개 변형, 탐색 범위, IS 선택/동점 기준, 평가·채택/보류/기각 기준, 실행 수·시간 상한, 종료 조건, 확정된 데이터/엔진 provenance를 **첫 전략 실행 전에 커밋하고 작업 브랜치에 push**한다. 선택 기준은 OOS를 사용하지 않는다. API 토큰/원본 계좌정보를 기록하지 않는다.
4. **실행 직전 고정 상태 재확인.** 계획에 확정한 데이터 manifest와 실제 입력 파일·종목 목록·엔진 revision을 대조한다. 현재 자동 데이터 로딩은 `src/data.rs`를 확인해 캐시와 실제 로드 성공 종목을 대조한다. 세트 중 데이터/코드가 바뀌면 비교를 계속하지 말고 차단 사유로 남긴다. 뉴스는 선택 사항이며, 뉴스 전략의 필수 입력 실패는 차단이다. 일반 전략의 뉴스 실패는 경고로 기록한다.
5. **기본형·복수 변형.** `strategies/<set-id>__baseline.toml`, `__v001.toml`, `__v002.toml` 등 서로 다른 새 ID를 쓴다. 같은 세트 태그 `set:<set-id>`로 연결하며 `parents`는 실제 앙상블 참조에만 사용한다. 실행마다 명령·시각·종료코드·파라미터·결과 경로·데이터/엔진 지문을 `attempts.jsonl`에 append한다. 로그도 세트 디렉터리에 보존한다. 이미 실행된 전략/결과는 덮어쓰지 않는다. 구문/실행 실패는 새 시도 ID로 최대 3회 수리하고 전체 예산에 포함한다. CLI `fail` 기록도 현재 세트의 새 ID만 허용한다.
6. **선택 고정.** baseline과 최소 2개 서로 다른 변형이 정상 실행된 뒤, 사전에 정한 **IS 지표만**으로 선택한다. `hermes/templates/selection.json`을 채워 `selection.json`으로 저장하고 커밋·push한다. 모든 시도의 IS/OOS는 보존하되 OOS로 순위/파라미터를 바꾸지 않는다. 현재 CLI는 이미 OOS를 노출하므로 정직하게 `holdout_status: exposed`로 기록한다.
7. **평가·결론.** 선택을 고정한 뒤 후보의 기존 실행 결과를 평가한다. 같은 ID로 재실행/덮어쓰지 않는다. baseline·Buy&Hold와 CAGR/MDD/Sharpe 등 실제 존재하는 지표를 비교하고 민감도·표본/데이터 한계를 적는다. 미리 정한 기준으로 accept/defer/reject를 결정한다. 모든 결과에 실제 교훈을 남긴다. 실행/예산/데이터 실패는 `blocked`이며 결론은 null이다. OOS에 따른 후속 아이디어는 다음 세트의 새 계획으로 넘긴다.
8. **보고·후속 작업.** `hermes/templates/report.md`를 바탕으로 `report.md`를 작성한다. 전체 시도와 선택 근거, OOS 노출·한계, 다음 가설, 버그·부족 기능의 기존/신규 이슈를 연결한다. 기준을 모두 충족한 세트만 completed로 표시하고 해당 backlog 항목을 체크한다. 주간 개선 검토에서는 이슈와 진행 PR을 확인해 승인된 과제를 별도 개발 브랜치에서 처리한다. proposal은 자동 승인되지 않는다.
9. **검증·게시.** 아래 Verification을 통과한 뒤 허용 파일만 명시적으로 stage하고 작업 브랜치에 commit/push한다. 연구 이슈를 연결한 PR을 만들고 원격에서 본문·head SHA·변경 파일을 다시 확인한다. 기존 진행 세트라면 같은 PR을 갱신한다. main 병합/자동병합·배포·릴리스는 하지 않는다.

## 전략 형식과 DSL

```toml
name = "EMA 교차 기본형"
hypothesis = "검증할 한 문장"
tags = ["trend", "single", "set:<set-id>"]
parents = []
source = "backlog" # 또는 "agent"
signal = "ema(close, 20) > ema(close, 60)"
```

`signal`은 당일 종가까지의 포지션(0~1)이며 엔진이 다음 봉에 적용한다. 참/거짓은 1/0, 숫자는 0~1로 제한된다.

- 시리즈: `open high low close volume`
- 연산: `+ - * /`, `< > <= >= == !=`, `and or not`, 괄호, 숫자
- 정수 n≥1: `sma(x,n)`, `ema(x,n)`, `max(x,n)`, `min(x,n)`, `rsi(x,n)`, `lag(x,n)`, `pct(x,n)`; `std(x,n)`은 n≥2.
- 상태/조합: `latch(진입,청산)`, `hold(조건,n)`, `clip(x,lo,hi)`, `ref("<기존 전략 id>")`.
- `ref()`는 계획 시점에 고정된 기존 전략만 참조한다. 연구 세트 ID는 별도 디렉터리/태그로 연결하며 앙상블 계보를 오염시키지 않는다.

## Pitfalls

- 연구 중 `src/`, `Cargo.*`, `index.html`, 기존 전략·결과 수정 금지. 엔진이 부족하면 이슈로 전환한다. 개발 모드의 승인된 개선까지 금지하는 규칙은 아니다.
- `results/index.json`은 CLI가 새 실행을 추가하는 공유 파일이다. 기존 엔트리를 삭제/변조하지 않는다. `lesson`은 현재 세트가 새로 만든 엔트리만 수정한다.
- 현재 CLI의 OOS는 탐색 중 노출된다. IS만 선택에 쓰더라도 독립 holdout을 구현한 것이 아니다. IS-only 스윕은 기존 #16에서 추적한다.
- 보고서/템플릿/문서 테스트는 실행기·완료 판정기를 구현하지 않는다. `research/` 보고서는 현재 Vercel 대시보드에 표시되지 않는다.
- 반복실행 자동화·주간 개발 검토는 실제 스케줄러 등록 후에만 동작한다. 크론이 설정됐다고 추정하지 않는다.

## Verification

- plan은 첫 실행 전 고정되었고 선택은 최종 해석 전 커밋되었는가? 엔진·데이터가 동일하며 모든 시도/실패와 종료코드가 남았는가?
- baseline + 최소 2개 서로 다른 변형이 성공했으며, IS 선택 근거와 exposed OOS의 한계가 명시됐는가? 충족 못 하면 blocked다.
- 완료 보고서에 실제 지표, accept/defer/reject, 교훈, 다음 실험, 후속 이슈가 있는가? blocked에는 원인·재개 조건·관련 이슈와 null 결론을 쓴다.
- `terminal(command="python3 -m unittest discover -s tests -p 'test_*.py'")`, `terminal(command="cargo test --locked")`, `terminal(command="git diff --check")`가 통과하는가? 문서 테스트는 실제 세트 완료를 증명하지 않는다.
- stage된 파일과 원격 PR이 허용 범위에만 있는가? 실행·저장·게시를 실제 증거 없이 완료라고 보고하지 않았는가?
