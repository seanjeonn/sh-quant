# Investops bounded supervision / scheduling — #33

## 상태를 구분한다

- **configured:** 고정 revision, profile/private config, entry script, 예산·일정·보고 대상이 검증된 상태.
- **tested:** actual native synthetic canary/기존 실제 증거 감사, supervisor 제한된 실제 Hermes CLI, cron nonce 전달/read-back 등이 각각 검증된 상태.
- **scheduled:** 등록된 job의 enabled/paused, timezone, next_run_at, script, delivery target을 실제 읽어 확인한 상태.
- **running:** host gateway/ticker 또는 특정 worker PID/receipt를 실제 확인한 현재 상태. 일정이 있다는 사실만으로 worker가 지금 실행 중이거나 매일 성공했다고 보고하지 않는다.

이 문서는 운영 규약이며 활성 job 또는 미래 성과의 증거가 아니다. #30/PR#32는 이미 별도로 검증된 core runner다. #33은 제한된 supervisor/예약/전달을 연결한다. main 병합·자동병합·배포·릴리스·계좌/주문 API·실거래·유료 구입은 승인 범위에 포함되지 않는다.

## 기본 운영 정책 (KST)

- 매일 **14:30**: `daily`. 미국 시간외 종료/지연 이후, 완료 일봉만 사용하고 당일 국내 진행 봉은 제외한다.
- **15분 간격의 오후 continuation**: `continue`. pending 연구가 없으면 stdout이 비고 모델도 호출하지 않는다. 이미 성공한 trial은 재실행하지 않는다.
- 매일 **17:00**: `deadline`. 미완료를 blocked/알림으로 남기고 예산을 늘리지 않는다.
- 일요일 **13:30**: `weekly`. 승인 이슈/PR/교훈의 triage 및 필요 issue/proposal 기록만 수행한다. 제안을 자동 승인하거나 임의 구현하지 않는다.
- 보고 대상은 사용자가 요청한 현재 투자개발 Discord thread다. raw model stdout이 아니라 검증된 receipt/registry의 **allowlist 메타데이터**만 전송한다. 원시 시세·수익률 수치·곡선·키·상세 로컬 경로를 채팅에 게시하지 않는다.
- 휴장일도 첫 실행 가능한 가설을 검토할 수 있으나, 최신 완료 스냅샷 재사용과 과거 OOS 재노출을 명시한다. 실제 거래일 완전성/총수익률을 보장하지 않는다. stale/결측/품질/인증 오류는 blocked다.

## 예산과 제한

- 일일 agent launch 최대4회; 각각 `--max-turns 80 --run-budget 1800`.
- 일일 supervisor 전체 wall budget **120분**. 중단/재시작/체크포인트 대기 시간을 숨기거나 리셋하지 않는다.
- 주간 검토 `--max-turns 40 --run-budget 900`.
- canary `--max-turns 8 --run-budget 120`이며 읽기 전용 probe다.
- deterministic 데이터 준비는 하루1회, 최대600 HTTP attempts /20분, 최소0.25초 간격 및 Retry-After 존중. 이 예산과 private token 공유를 에이전트가 별도로 우회하지 않는다. 실패 snapshot은 보존하고 같은 날 무한 재수집하지 않는다.
- 각 연구는 schema2의 max12 trials/120분/max3 repairs 안에서만 수행한다. supervisor의 시간 한도가 더 먼저 오면 stopped/blocked로 남긴다.
- 설정의 모델/provider를 별도 pin하지 않고 활성 사용자 설정을 따른다. `--yolo`, `--ignore-rules`, 다른 profile 수정은 사용하지 않는다. 현재 Hermes cron script timeout 기본3600초와 LLM run budget은 별개다. 데이터 준비20분+agent30분으로 한 script invocation을 기본 timeout 안에 제한한다.

## 파일·신뢰 경계

- 저장소: `tools/automation_supervisor.py`, 테스트, 이 문서, `hermes/templates/automation_entry.py`.
- 활성 profile만: `$HERMES_HOME/private/automation/config.json`, private registry/day ledger/logs/receipts 및 `$HERMES_HOME/scripts/investops-<mode>.py`.
- entry는 `profiles/investops` 위치, HERMES_HOME 일치, private 파일/디렉터리 권한700/600, 알려진 파일명(mode allowlist), 지정된 checkout과 supervisor SHA-256을 확인한 뒤 Python exec를 한다. arbitrary shell command를 config에서 실행하지 않는다.
- supervisor는 자신과 core source/binary/revision 지문, 날짜·예산·활성 canary receipt를 재검증한다. 원래 dirty worktree는 사용하지 않고 날짜별 연구 전용 worktree를 고정 core revision에서 만든다.
- profile skill `sh-quant-automation`은 새로운 실행 세션에 한정된 workflow/승인 경계를 제공한다. 다른 profile의 skills/config/cron/memory는 수정하지 않는다.
- 안정된 kernel lock은 자식에게 상속해 parent 강제종료 직후 다른 worker가 중복 진입하지 못하게 한다. supervisor→Hermes→runner의 중첩 helper는 같은 절대 expiry/cancellation scope를 따른다. private plan의 `supervisor_scope`는 당일 `active-scope.json` 포인터를 가리킨다. 개별 invocation은 불변 scope 파일/해시와 취소 marker를 사용한다. 외부 helper만 scope를 revoke하며, 개별 native trial 성공이 부모 lease를 취소해서는 안 된다. 일반 trial의 새 세션 생성도 이 계약에 포함된다. 악성 프로세스/동일 사용자에 대한 sandbox 보장은 아니다.
- private 모델 stdout/stderr/명령/receipt는 권한 제한 파일로 보존하며, 유효한 결과 없는 모델 성공 응답을 연구 완료로 간주하지 않는다. prompt는 행동 규약이지 hostile tool-use sandbox가 아니다.

## 실행 흐름

1. canary 외 mode는 config activation과 해당 정책/SHA에 맞는 canary receipt를 요구한다. 불일치/변경이면 차단한다.
2. 기존 당일 등록 세트도 registry `verify`와 감독기가 공급한 manifest 경로/해시, binary 경로/해시, engine revision, 지정 worktree, private plan 경로, supervisor scope를 독립 대조한다. 원격 게시까지 확인된 완료만 skip한다. 명시된 기존 EMA는 별도 `audit_legacy_ema` 읽기 전용 경계로 확인하며 오늘의 EMA를 다시 실행하지 않는다.
3. daily는 날짜 ledger를 먼저 기록하고 deterministic 준비를1회 수행한다. 24종목 manifest/hash가 검증돼야 다음으로 간다. 실패/부분 snapshot을 새 이름으로 몰래 반복하지 않는다.
4. 날짜별 작업공간에서 bounded agent가 과거 교훈/backlog를 확인하고 issue → 실제 plan → runner init → 공개 descriptor commit/push/checkpoint → trials → 선택 descriptor commit/push/checkpoint → 평가/구체 교훈/다음 가설/보고/PR를 수행한다.
5. supervisor는 CLI exit code/텍스트가 아니라 실제 registry `verify`와 최종 게시 증거로 completed/결론을 결정한다. runner만 완료되면 `publication_pending`으로 구분하며 같은 세트의 continuation에서 게시만 재개한다. 에이전트는 `--mode publication`의 검증된 공개용 descriptor를 그대로 커밋/push하고 private `publication.json`에 commit/branch/report hash/PR identity를 기록한다. supervisor가 실제 원격 최종 blob과 **PR head/base/files**를 독립 조회하기 전 전체 세트 완료를 알리지 않는다. PR은 OPEN이어야 한다. 통합 후 닫히거나 병합된 PR은 base를 제외한 위 검사를 모두 통과하고 게시 head가 원격 main에 포함됨을 compare로 확인한 경우에만 인정한다(#41, #45). base는 OPEN PR에서만 현재 core 브랜치와 대조한다. descriptor에는 수치 성과/시세/로컬 경로를 넣지 않는다. 이 read/render helper는 부모의 worker lock 아래에서 호출할 수 있지만 새 worker/API 수집/전략 실행을 시작하지 않는다. raw model stdout은 전달하지 않는다.
6. deadline/횟수/시간 초과는 blocked다. 데이터/모델 실패도 무제한 반복하지 않는다. 해제는 원인 확인과 명시적 운영 조치가 필요하다.
7. weekly는 private receipt의 `managed_issue_urls` 및 같은 URL 집합의 `managed_issue_body_sha256`을 검사하고, 관리 저장소 각 issue의 실제 identity/body를 독립 조회해 해시를 대조한 뒤 확인 건수만 전달한다. URL 형식이나 agent 주장만으로 검증 완료라고 하지 않으며, 조회 확인을 실제 수정/조치 완료로 부풀리지 않는다. 반복 invocation은 같은 주에 재작업하지 않는다.

## 시작 경합·진단·복구 경계 — #48 / #44

- `continue`는 신뢰된 당일 ledger가 없으면 **worker lock을 열기 전** 조용히 종료하며, lock 획득 후에도 같은 조건을 재검사한다. 날짜 디렉터리/ledger 경로의 symlink·권한 오류는 idle로 숨기지 않는다. 시작 시각 전 tick도 새 날짜/registry/수집을 만들지 않는다.
- 당일 worker가 실제 kernel lock을 소유하면 `continue`는 오류 알림 대신 빈 stdout과 private `lock_busy` 진단을 남긴다. `daily`만 최대 **1초** 짧게 재획득을 기다린다. live owner/상속된 worker를 죽이거나 lock 파일을 교체·해제하지 않으며, SIGKILL 뒤 자식의 동일 open-file-description exclusivity도 유지한다.
- `deadline`은 당일 ledger가 없을 때 17:00 전에는 조용히 종료하지만, 17:00 이후에는 **`연구 차단 YYYY-MM-DD`**와 `missing_day_deadline` 진단을 남긴다. 성공/완료/가짜 day ledger를 생성하지 않는다.
- 진단은 검증된 private root의 `diagnostics/<random>.json`에 독점 생성/fsync하는 불변 0600 파일이다(디렉터리0700). 필드는 `schema_version`, allowlist `mode`(파싱 실패는 `unknown`), KST `date`, allowlist `stage/outcome/reason`, epoch `timestamp`뿐이다. `started`는 실행 진입 증거일 뿐 완료 증거가 아니며, 최종 outcome과 구분한다. `lock_busy`, `config_validation`, `pin_validation`, `canary_validation`을 구분하며 예외 문자열·명령 인자·로컬 경로·raw stdout/stderr·시세·인증정보를 넣지 않는다.
- 생성자 실패도 stage별로 기록한다. config가 검증되기 전 sink는 **활성 `HERMES_HOME`의 `profiles/investops/private/automation`**만 허용하며, invalid config의 profile/private_root로 우회하지 않는다. 이 경로가 없거나 신뢰/권한/쓰기 검증에 실패하면 작업은 fail-closed다. 다른 profile에 fallback 파일을 쓰지 않는다. 정상 실행도 durable 시작 진단을 쓰기 전에 worker 작업을 시작하지 않는다.

### 보수적 manual-only 복구 (같은 날 CLI retry 미지원)

이 수정은 재시도 프레임워크/자동 continuation 초기화를 추가하지 않는다. **유효한 config의 `daily`가 시작 시각 이후 ledger 생성 전에 실패하면**, 처음 기록한 시도 시작 epoch·정책 해시와 `manual_only`를 profile 고정 `private/automation/failed-starts/YYYY-MM-DD.json`에 불변 보존한다. config의 private_root를 옮기거나 정책을 바꿔도 이 anchor를 바꾸지 않는다. invalid profile/config 생성자 실패에는 정책 marker를 쓰지 않고 안전한 진단만 남긴다.

**marker가 있고 ledger가 없으면 같은 날 모든 후속 `daily` 시작을 차단한다.** 15:00 전의 명시적 CLI 호출도 재시도로 허용하지 않으며, 15:00 이후/23:00 re-pin도 예외가 아니다. marker 삭제·이름 변경·새 root로 우회하거나 ledger/수집 카운터를 재생성하는 복구 절차는 제공하지 않는다. 운영자는 원인을 검토하고 blocked incident를 별도 메타데이터로 기록하며, 새 정책/source pin과 실제 canary를 검증한 뒤 **다음 날** 정상 시작을 평가한다. invalid config로 marker가 없었던 실패/과거 generic 실패도 안전한 재시도 가능의 증거가 아니므로 운영자가 먼저 기존 기록·프로세스·부분 디렉터리·registry를 검토해야 한다.

기존 유효한 ledger가 있으면 원래의 pending/publication/completed/blocked 검증·재개 규칙과 최초 started_epoch·launch/수집 카운터·벽시계 예산을 그대로 따른다. partial day directory/수집 흔적은 보존하며 새 ledger로 초기화하지 않는다. 실패 marker도 없고 기존 흔적도 없는 **첫** catch-up `daily`에는 기존 시작/17:00 deadline 정책이 적용되지만 재시도 허가는 아니다. 이 구현에는 1회 operator retry 플래그·15:00 retry cutoff 확장·wall-budget epoch 이식 기능이 없으며, 더 느슨한 재시작을 승인하지 않는다.

### 과거 사고에 대한 증거 수준

2026-11-12 14:30의 daily generic 오류와 동시 continuation의 빈 출력/ledger 부재는, idle guard보다 먼저 global nonblocking flock을 잡던 순서 및 실제 kernel 합성 재현과 일치한다. 따라서 시작 lock race는 **강하게 지지되는 원인**이나, 과거 오류는 generic 진단뿐이므로 그 사고의 유일 원인으로 확정하지 않는다. 이 수정의 합성 검증은 실제 시장/모델 실행이나 오늘의 연구 완료를 뜻하지 않는다.

## Canary와 활성화 순서

1. supervisor config activation=false, job은 **paused**로 생성한다. 반복 예약을 먼저 켜지 않는다.
2. canary는 기존 synthetic registry의 verify/attempt_count를 전후 대조하고, 제한된 실제 Hermes CLI를 읽기 전용으로 호출한다. 모델이 nonce를 정확히 반환하고 실제 검증이 통과해야 private canary receipt를 쓴다. 새 시세/API/전략 trial은 수행하지 않는다. 운영 re-pin에서는 선택적 `canary_generation`(안전한 8–100자 식별자)을 명시해 `canaries/<generation>/receipt.json`과 새 invocation 로그를 분리한다. 생략 시 기존 legacy 경로를 유지한다. 이전 config/receipt/log를 덮어쓰거나 이동하지 않으며, 실패 generation은 자동 재시도/이름 변경으로 숨기지 않는다. 새 generation은 버전 전환을 승인한 운영자가 선택하고 정책 해시에 포함한다.
3. cron의 `run`을1회 실행한다. 실제 출력 marker의 nonce, run ledger/status와 Discord 메시지를 읽어 같은 실행의 전달 성공을 확인한다. 도구 호출 성공만으로 전달 성공을 주장하지 않는다.
4. 코드/설정/정책이 canary와 일치하는지 다시 확인한 뒤 activation을 바꾸고 반복 job을 resume한다. 이후 timezone/next_run_at/script/delivery/enabled 상태를 read-back한다.
5. 초기 실제 daily 연구는 다음 KST 일자의 예약 시점부터다. 지금의 synthetic/transport 검증으로 미래의 매일 성공을 보장하지 않는다.

## 검증 / 미완료 범위

`python3 -B -m unittest discover -s tests -p 'test_*.py'`, `cargo test --locked`, `git diff --check`를 실행하고 결과를 보존한다. 실제 CLI/cron/Discord 검증은 단위 테스트와 별도로 기록한다. 활성화가 끝나기 전까지 이 문서 자체는 configured/tested/scheduled/running 완료 주장이 아니다.

#28 달력/기업행위/집계 공개 범위, #16 IS-only sweep, #24 기본 Yahoo 경로의 원본 품질 문제, #13 생존편향은 별도 이슈다. #20의 더 넓은 정책/runner 범위는 아직 자동 완성된 것으로 취급하지 않는다. PC 절전·호스트 종료·공인 IP 변경·인증/네트워크 장애가 생기면 운영을 보장할 수 없으며 blocked/전달실패를 숨기지 않는다.
