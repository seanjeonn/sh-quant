# sh-quant

매일 **전략 연구 한 세트**를 완주한다. Hermes Agent가 이전 교훈을 검토해 가설을 정하고, 실험 설계 → 기본형 → 복수 변형·파라미터 최적화 → 후보 선택 → 최종 평가·결론까지 수행한다. 파일 하나나 백테스트 한 번을 하루 완료로 세지 않는다.

투자 프로그램의 개발·유지보수도 지속한다. 연구 중 발견한 문제는 `AGENTS.md`에 따라 이슈로 추적하고, 승인된 개선은 별도의 개발 작업으로 처리한다. 연구 루프가 최우선이며 연구를 막는 정확성·데이터 문제를 먼저 해결한다.

## 로컬

```sh
cargo test --locked
python3 -m unittest discover -s tests -p 'test_*.py'   # 문서/템플릿 계약 검사
cargo run --release --locked -- run strategies/2026-11-09_sma_cross.toml
cargo run --release --locked -- news
python3 -m http.server 8787
```

위 `run`은 기존 CLI 사용 예시다. **이미 기록된 ID로 다시 실행하면 결과를 덮어쓸 수 있으므로 연구에서는 실행하지 않는다.** 연구 실행에는 새 고유 ID를 사용한다. HTTP 서버는 로컬 확인용이며 자동 배포가 아니다.

## 토스 일봉 / 비공개 frozen 실행

토스 데이터는 [별도 데이터 규약](docs/toss-data.md)을 먼저 읽는다. `tools/prepare_toss.py`로 저장소 밖의 신규 private snapshot을 준비하고 `run ... --data-manifest <absolute-manifest> --output-dir <absolute-private-results>`로 실행한다. 기존 `run`의 Yahoo 경로와 수익률 계산은 유지한다. 토스 원본/CSV/수치 로그/곡선을 공개 `results/`나 대시보드에 게시하지 않는다. 토스 조정가격 수익률은 Yahoo 배당재투자 총수익률과 동일하지 않다.

## 하루 연구 세트

자세한 규칙은 [연구 세트 규약](docs/daily-research-set.md), 실행 절차는 [Hermes 스킬](hermes/SKILL.md)을 읽는다.

- KST 기준 하루 가설 1개를 선정하고, 실행 전 계획·데이터/엔진 provenance·유한한 탐색 예산을 고정한다.
- baseline + 최소 2개 서로 다른 변형을 실행하고, 전체 성공/실패를 보존한다.
- 후보는 사전 정의한 IS 기준으로 선택하고, 최종 비교·민감도·한계·다음 실험을 기록한다.
- 채택(`accept`), 보류(`defer`), 기각(`reject`) 모두 근거가 있으면 정상 완료다. 실행·데이터·예산 부족은 `blocked`이며 완료로 세지 않는다.
- 현재 CLI는 모든 실행에서 IS/OOS를 함께 노출한다. OOS를 최적화에 쓰지 않고 `holdout_status: exposed`로 고지한다. 독립 holdout이 구현됐다고 주장하지 않는다.

## 구조

- `src/`: Rust 엔진. **연구 모드에서 수정 금지**. 승인된 엔진 개선은 이슈·별도 개발 브랜치·테스트·리뷰로 수행한다.
  - `expr.rs`: 미래 참조 연산자가 없는 전략 DSL.
  - `backtest.rs`: 다음 봉 포지션 적용, 비용(US 0.05% / KR 0.25%), 동일가중, 고정 IS/OOS 분할. 정확한 경계는 해당 revision 코드로 확인한다.
  - `data.rs`: US/KR 유니버스 각 12종목, Yahoo 일봉 → `data/cache/`. 갱신 실패·종목 누락·stale 데이터 가능성을 확인한다.
  - `news.rs`: 헤드라인을 `data/news/`에 축적.
- `strategies/<set-id>__baseline.toml`, `__v001.toml` 등: 세트별 기본형·변형. 기존 전략은 보존한다.
- `research/<set-id>/`: 사전 계획·데이터 manifest·전체 시도 로그·선택 근거·종합 보고서. 빈 양식은 `hermes/templates/`.
- `results/`: CLI가 생성하는 개별 실행 결과와 공유 `index.json`. 기존 결과는 보존한다.
- `backlog.md`: 사람이 추가하는 연구 가설 큐. 실행 가능한 항목을 우선하고, 비면 과거 교훈을 바탕으로 자율 생성한다. 세트 완료 후에만 체크한다.
- GitHub Issues: 버그·승인된 개발·개선 제안. proposal은 자동 승인된 개발 과제가 아니다.

## Vercel

`vercel.json`은 `index.html`과 `results/`만 `public/`으로 복사하며 Rust는 빌드하지 않는다. 현재 화면은 **개별 실행 결과**를 보여주고 연구 세트 보고서/완료 상태는 아직 표시하지 않는다. main 병합·배포는 별도 승인이 필요하다.

## Hermes 연결과 자동화 상태

1. Rust/Cargo와 GitHub 접근을 준비한다.
2. 대상 프로필의 스킬 폴더에 `daily-backtest/SKILL.md`를 이 저장소의 `hermes/SKILL.md`로 연결한다. 프로필마다 `$HERMES_HOME`을 확인하고 HQ와 투자 프로필의 설정/메모리를 섞지 않는다.
3. 작업 디렉터리는 저장소 루트로 설정해 `AGENTS.md`가 로드되게 한다. 실행 환경은 `TZ=Asia/Seoul`로 통일한다.
4. 규칙·데이터 고정·수동 1세트 검증 후 별도 작업으로 매일 연구/주간 개선의 스케줄과 실행 예산을 설정한다. 과거의 07:00 예시는 활성 일정이 아니다.

**#26은 토스 data-only 준비와 frozen 입력/private 결과만 연결한다. 연구 실행기·IS-only 스윕·완료 판정기·cron은 구현하거나 등록하지 않는다.** 수동 연구 프로토콜을 따르고 필수 데이터 준비/고정을 만족할 수 없으면 blocked로 기록한다. 더 넓은 실행·검증 도구는 #20, 예약 자동화는 #21, IS-only 스윕은 #16에서 추적한다. GitHub 작업 범위는 [워크플로](docs/github-workflow.md)를 따른다.
