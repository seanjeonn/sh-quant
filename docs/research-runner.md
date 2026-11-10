# 연구 상태 실행기와 무인 운영 경계 — #30

## 목적 / 현재 배포 경계

#30은 #20 중 최소 머신 검증 가능한 plan → 제한된 trial → IS 선택 → 평가 → 완료 검증을 연결한다. `tools/prepare_toss.py`의 실제 수집과 frozen/private 엔진을 재사용하며 임의 가설 생성기·전체 sweep·스케줄러를 하나의 엔진으로 합치지 않는다. 기존 실제 EMA 세트(#23/PR#29)는 재실행하지 않고 읽기 전용 증거 검증 대상으로 사용한다. 오늘 다른 시장 연구를 추가로 완료한 것처럼 보고하지 않는다.

**예약 등록과 실제 운영은 별도 검증**이다. 이 문서와 runner 코드만으로 #21의 예약이 설정/활성화됐거나 매일 연구가 실행 중이라고 주장하지 않는다. main 병합·자동병합·배포/릴리스·실거래/계좌 API·유료 소스는 별도 승인 대상이다. 검증된 working revision을 전용 worktree에 고정해 main 병합 없이도 canary를 할 수 있으나, 그 사실과 PR 의존성을 명시해야 한다.

## 책임 분리

- `tools/research_contract.py`: finite plan/budget/provenance 계약, exact Decimal IS 순위 및 고정 평가정책. 임의 English prose나 Python expression을 실행하지 않는다.
- `tools/research_set.py`: private registry, KST 날짜별 단일 set, OS 잠금, 단계별 상태/이벤트/프로세스와 증거 검증. 검증된 binary를 allowlisted 인자로만 실행한다.
- `src/frozen.rs`: 결과 저장 커밋 지점/고유 ID/경로 검증. stable kernel lock을 사용해 SIGKILL 뒤 파일 존재만으로 영구 차단되지 않도록 한다. `.pending`/orphan 결과를 지우거나 덮어써서 회복하지 않는다.
- 다음 #21 연결: 과거 보고서/backlog에서 가설과 한정 후보를 제안하는 에이전트 → 데이터 준비 → plan 생성/commit/push → checkpoint → 제한된 worker step → 선택 commit/push/checkpoint → 평가/보고/PR → 안전한 Discord 요약. 에이전트가 checkpoint나 완료 검증을 생략할 수 없어야 한다.

## 머신 정책과 고정 상태

신규 plan schema2는 `machine_policy.selection=mean_is_sharpe_v1`와 `machine_policy.evaluation=sharpe_excess_mdd_v1`만 허용한다. 새로운 선택/채택 정책은 별도 엔지니어링 테스트와 버전 경계가 필요하다. max_attempts<=12, max_wall_minutes<=120, max_repairs<=3 안에서 실제 시작/중단/실패 모두 기록한다. 휴면·재시작 시간을 숨겨 예산을 늘리지 않는다.

baseline과 최소2개 의미 있는 변형, 모든 사전등록 후보, US/KR 동일가중 IS Sharpe 평균 최대 → IS CAGR → IS MDD → baseline 우선 → ID순의 Decimal 결정이 필요하다. OOS를 보며 후보·동점기준을 바꾸지 않는다. accept/reject/defer는 고정된 평가정책의 결과이며 데이터/실행/증거 실패는 `blocked`, 결론 null이다. `exposed` OOS를 untouched holdout으로 표시하지 않는다.

등록 시 실제 engine revision/Cargo.lock/binary/manifest/24종목 입력 해시와 private plan 원문을 고정한다. 이후 실행에서 code/data/plan drift를 발견하면 중단한다. private 경로는 Git checkout 밖700/600으로 제한하고, traversal·symlink/hardlink·추가/누락 종목·결과 덮어쓰기를 거부한다. 토스 원본/시세/수치/곡선을 공개 descriptor, stdout, Discord, Vercel에 넣지 않는다. 공개 기록에는 허용 메타데이터와 private 원문의 SHA-256만 둔다.

## Checkpoint 순서

1. `init`: 같은 KST 날짜의 완료/진행 세트가 있는지 확인하고 새 plan을 동결하거나 같은 ID의 상태를 재사용한다. 완료 세트가 있으면 다른 ID 생성/재실행 금지.
2. `descriptor ... --kind plan`: 공개 가능한 plan 지문을 생성한다. 지정된 연구 파일만 commit/push한다.
3. `checkpoint ... --kind plan`: **정확한 commit:path blob**과 remote branch 상태를 읽어 descriptor 일치를 확인한다. 이것이 없으면 trial을 시작하지 않는다.
4. `step`: 성공한 trial을 건너뛰고 한정된 다음 작업만 수행한다. 모든 후보 성공 후 IS 선택 지문을 만든다.
5. selection descriptor를 commit/push한 뒤 `checkpoint ... --kind selection`을 통과해야 평가로 진행한다. 선택 관측 후 다른 기준으로 지문을 다시 만드는 것을 금지한다.
6. 평가/보고/교훈의 실제 파일과 result/hash/시도 로그/정책 재계산이 모두 일치해야 `completed`다. 상태 문자열만 completed로 바꿔도 verify는 실패해야 한다.

정확한 CLI 인자는 구현의 `--help`를 확인한다. 이 문서는 실행되기 전 예시를 성공 증거로 바꾸지 않는다. Git checkpoint는 읽기만 수행하며 임의 main push/merge를 하지 않는다.

## 중단·복구 테스트 계약

- worker 단일 쓰기는 kernel-managed lock으로 보호한다. PID 숫자만 보고 임의 프로세스를 죽이거나 모르는 lock을 삭제하지 않는다.
- subprocess는 통제된 process group에서 실행하며 timeout 시 전체 자식 정리를 확인한다. parent SIGKILL 뒤 살아 있는 자식이 있으면 새 worker가 같은 실험을 겹쳐 실행하지 못해야 한다.
- 결과 커밋 직후 end-event 전 중단이면 실제 index/detail/hash로 성공을 재확인하고 재실행하지 않는다. partial/ambiguous 결과는 보존하고 차단하거나 명시된 새 repair ID/별도 결과 디렉터리로만 재시도한다.
- 동일 run ID·성공 결과·원시 로그는 불변이다. 중단도 시도/시간 예산에 포함한다.
- forced-stop/restart/concurrency/corruption/time-budget/false-completion tests가 실제로 실패를 잡는지 RED/GREEN으로 검증한다.
- 실제 Rust binary를 쓰는 end-to-end canary에는 **clearly synthetic** fixture만 사용하고 테스트 경로/상태를 시장 연구 완료 기록과 분리한다. 이 테스트 수치를 백테스트 성과로 보고하지 않는다. 기존 시장 데이터는 읽기 전용 legacy audit로 대조한다.

## Hermes runtime 확인과 다음 단계 (#21)

2026-11-10 확인한 공식 cron 문서와 설치 소스는 script timeout 기본3600초를 명시한다. 이것은 LLM inactivity/iteration 제한과 별개이며, 전체 연구에 일률적인3분 제한이 있다는 과거 설명을 사용하지 않는다. 현재 investops agent.max_turns는500이므로 무인 실행에 이 기본값을 무제한처럼 의존하지 않는다.

`hermes chat --help`에서 실제 확인한 `--max-turns N`과 `--run-budget SECONDS`를 통해 planner/supervisor one-shot을 별도로 제한할 수 있다. 모델/provider를 임의 pin하지 않고 사용자 main 설정을 따른다. cron script 환경에서 자격증명이 자동 상속된다고 가정하지 않으며 profile 경로에서 안전하게 읽는다. `--yolo`, `--ignore-rules`, 다른 프로필 설정 편집은 사용하지 않는다.

예약은 #30의 end-to-end/강제종료복구/증거 검증과 독립 리뷰 이후에 연결한다. #21에서 일일 KST 시작/마감, 휴장일 정책, 주간 backlog 검토, API/turn/time 예산, 보고 채널을 명시하고 paused canary부터 등록한다. 실제1회 호출·산출물·전달 read-back이 통과해야 recurring을 활성화한다. 성공/실패를 구분하고 원시 데이터/집계 수치 공개는 #28의 확인 전 계속 제한한다. PC sleep/재부팅/공인 IP변경/403/토큰충돌은 숨기지 않고 차단·알림으로 처리한다.

## 검증 명령

```text
cargo test --locked
python3 -m unittest discover -s tests -p 'test_*.py'
git diff --check
```

위 tests, 기존 실제 세트 legacy audit, 실제 binary synthetic canary, 예약 delivery canary는 서로 다른 검증이다. 하나를 다른 성공으로 대신 보고하지 않는다. 나머지 #16 IS-only sweep, #28 달력/기업행위/공개정책, #21 예약은 각 이슈에서 범위를 유지한다.
