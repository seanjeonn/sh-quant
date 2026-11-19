# 봉인 forward holdout 설계 — #74

상태: **설계 확정(2026-11-19).** 5절 값은 사용자가 제안값으로 확정했다. 구현은 별도 feature 이슈와 engineering 브랜치에서 한다. 운영 활성화(S 확정 시점)는 별도 승인이다.

## 1. 문제

- IS/OOS 경계는 `src/backtest.rs`의 `is_end() = 2022-12-31` 하나다. 모든 세트가 2023-01-01 이후 같은 OOS를 평가한다.
- 2026-11-10~19 사이 9개 세트, 약 28개 후보가 같은 OOS를 관측했다. 각 세트의 lessons/next_experiment가 OOS 관찰을 근거로 다음 가설을 고르므로, 연구 흐름 전체로는 OOS가 선택에 쓰인다(데이터 스누핑).
- 일일 refresh가 매일 새 봉을 snapshot에 넣기 때문에 **새로 생기는 데이터도 다음 날 세트가 곧바로 소비한다.** 현재 구조에서는 미관측 데이터가 하나도 남지 않는다.
- 그 결과 accept가 나와도 독립 검증이라 부를 수 없다(`holdout_status: exposed`).

## 2. 기존 데이터로는 해결되지 않는 이유

- 2026-11-13 이전의 모든 구간은 이미 IS 또는 OOS로 관측됐다. 그 안에서 "봉인 구간"을 새로 떼어도 오염된 구간이다.
- walk-forward는 한 세트 안의 선택 과적합을 줄이지만, 같은 역사를 여러 세트가 반복 관측하는 문제는 그대로다.
- **진짜 미관측 데이터는 앞으로 생길 봉뿐이다.** 그러므로 설계의 핵심은 "봉인 시점 S 이후 데이터를 연구가 보지 못하게 막고, 엄격한 조건에서만 한 번 연다"이다.

## 3. 제안: 봉인 forward holdout

### 3.1 봉인 (sealing)

- 봉인 시점 `S`(날짜)를 정책 버전에 고정한다. 연구 세트는 `date < S`인 봉만 받는다.
- 엔진은 이미 manifest의 `cutoff_exclusive`를 강제한다(`src/frozen.rs`, `d < cutoff`). **봉인에 엔진 변경은 필요 없다.**
- 단, `tools/prepare_toss.py`는 마지막 봉이 cutoff 7일 이내여야 통과하므로 과거 cutoff로 새로 수집할 수 없다. 대신 supervisor가 검증된 최신 snapshot에서 `date < S`만 남긴 **파생 봉인 뷰**(새 manifest, `cutoff_exclusive = S`, 원본 manifest SHA-256 기록)를 만들어 연구에 공급한다. 원본 snapshot과 일일 refresh는 그대로 유지한다.
- IS/OOS 경계(2022-12-31)는 바꾸지 않는다. 기존 세트와 비교 가능하다.

### 3.2 개봉 (opening)

- 개봉 대상: 기존 `sharpe_excess_mdd_v1`으로 **accept**를 받은 선택 후보만. defer/reject는 열지 않는다(holdout 소모 방지).
- 시점: 해당 세트가 completed된 뒤, `S` 이후 누적 봉이 두 시장 모두 `L` 이상일 때. 부족하면 `holdout_pending`을 반환하고 아무것도 기록하지 않는다.
- 개봉은 일일 runner 상태가 아니라 별도 도구 `tools/holdout.py open`이 한다. completed 세트는 불변이므로 runner 해시 체인에 몇 달 뒤의 단계를 덧붙이지 않는다. 도구는 `Runner.verify()`로 세트를 재검증한 뒤 private ledger에 `open`을 먼저 기록하고 엔진을 실행한다. 그래서 결과를 본 뒤 중단돼도 다시 열 수 없다.
- 계산: 엔진에 holdout 구간 지표를 추가한다. `run`에 `--holdout-start S`를 주면 기존 IS/OOS는 `date < S`로만 계산하고, `date >= S` 구간 지표를 `holdout` split으로 따로 낸다. 신호 워밍업은 전체 이력을 쓰고 기존 truncation 재검증이 lookahead를 막는다. **엔진 변경은 이것 하나다.**
- 판정: 새 정책 `holdout_forward_v1`. 시장별 holdout Sharpe > 0 그리고 평균 holdout excess CAGR ≥ 0이면 `accept`, 아니면 `defer`. 개봉 결과로 후보·파라미터를 바꾸지 않는다.
- 개봉은 후보당 1회. 결과 수치는 private, 공개 기록에는 pass/fail과 private 증거 SHA-256만 남긴다.

### 3.3 오염 차단과 epoch

- 개봉 결과의 수치와 해석은 lessons/next_experiment에 **넣지 않는다**(다음 가설 선택으로 흘러가는 경로 차단). 공개 ledger에는 개봉 횟수와 pass/fail만 기록한다.
- 같은 holdout을 여러 후보가 열수록 다시 다중검정이 된다. epoch당 최대 개봉 횟수 `K`를 두고, 소진되면 새 epoch `S' = 그날`로 롤오버한다. 이전 holdout은 exposed로 강등한다.
- holdout 개봉 이력은 `tools/research_ledger.py`에 epoch별로 집계한다.

### 3.4 다중검정 회계 (#12 흡수)

- epoch마다 누적 후보 시도 수 N을 ledger에서 계산해 private 보고서에 함께 기록한다.
- 1단계는 기록만 한다. deflated Sharpe 등으로 판정 기준 자체를 바꾸는 것은 데이터가 쌓인 뒤 별도 정책 버전으로 다룬다.

## 4. 변경 범위 (구현 시)

| 영역 | 변경 | 단계 |
|---|---|---|
| `src/backtest.rs`, `src/main.rs` | `run ... --holdout-start S`, `holdout` split | A (#109) |
| `tools/research_contract.py` | sealed plan(`holdout_status: sealed`, `holdout_start`, `machine_policy.holdout = holdout_forward_v1`), `evaluate_holdout` | A |
| `tools/research_set.py` | sealed plan은 manifest `cutoff_exclusive <= S` 강제, 산출물에 holdout_status 전파 | A |
| `tools/holdout.py` | `seal`(봉인 뷰 파생), `open`(1회 개봉, private ledger) | A |
| `tools/research_ledger.py` | epoch별 sealed 세트 수·시도 수·개봉 결과 | A |
| `tools/automation_supervisor.py`, 프롬프트, 템플릿 | 봉인 뷰 공급, sealed plan 작성, publication에 `holdout_start` | B (운영 활성화와 함께) |

봉인 뷰와 private ledger는 개봉 시점까지 보존해야 한다. runner가 세트를 재검증할 때 원래 입력 manifest를 다시 읽기 때문이다.

기존 v1 세트·publication은 재라벨하지 않는다. 새 정책 버전 활성화는 #82와 같은 운영 repin·canary 절차를 따른다.

## 5. 확정값 (2026-11-19)

1. **봉인 시점 `S`:** 새 정책을 운영에 활성화하는 날. 그 전 데이터는 전부 exposed로 남는다.
2. **최소 holdout 길이 `L`:** 126 거래일(약 6개월), 두 시장 각각 S 이후 봉 수 기준.
3. **epoch당 개봉 한도 `K`:** 3.
4. **개봉 대상:** accept만.

## 6. 한계

- 첫 개봉은 `S`로부터 최소 `L` 뒤에나 가능하다. 그 전까지 accept는 "holdout 대기"로만 보고한다.
- 연구 데이터가 `S`에서 멈추므로 최근 시장 변화는 epoch 롤오버 전까지 연구에 반영되지 않는다.
- 6개월 holdout은 짧다. 통과가 장기 유효성을 보장하지 않는다. 생존편향(#13)·데이터 의미(#28) 한계는 그대로다.
