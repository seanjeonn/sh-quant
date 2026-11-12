# 일일 전략 연구 보고서 — TODO set-id

- 상태: TODO planned / running / completed / blocked
- 결론: TODO accept / defer / reject; blocked이면 null
- KST 기준일 / 실제 시작·종료 시각: TODO
- 추적 이슈 / 브랜치 / PR / plan·selection 커밋: TODO
- 엔진 revision / 데이터 manifest·snapshot / OOS 노출: TODO

## 가설과 선정 이유

TODO 이전 세트의 교훈과 연결하고 이번에 새로 검증할 것을 쓴다.

## 사전 계획과 실행 범위

TODO baseline, 변형 범위, IS-only 선택/동점 규칙, 사전 평가/종료 기준, 예산과 실제 사용량. 변경·중단 이력도 쓴다.

## 전체 시도 비교

다음은 빈 양식이며 실제 수치를 채우기 전에는 결과가 아니다. 시장별 행을 만들고 실패 시도도 빠뜨리지 않는다. 수익률/MDD의 단위를 명시한다.

| run ID / 역할 | 파라미터 | 시장 | IS 지표 | OOS 지표 | B&H CAGR | 상태 / 로그 |
|---|---|---|---|---|---|---|
| TODO | TODO | TODO | TODO | TODO | TODO | TODO |

## 선택 근거와 최종 평가

TODO selection.json과 일치하는 IS 선택 근거, baseline/benchmark 대비 결과, 파라미터 민감도. OOS를 보고 후보를 바꾸지 않았는지 명시한다.

## 결론·한계·교훈

TODO accept/defer/reject와 사전 기준의 근거. OOS는 exposed이며 미관측 holdout이 아님을 명시한다. 데이터 누락/표본/생존편향/과최적화 등 실제 확인된 한계와 미확인 사항을 구분한다.

## 다음 실험과 후속 개발

TODO 다음 가설·시도 이유·관련 이슈. 새 과제는 AGENTS.md의 양식으로 이슈를 남기거나 기존 이슈에 연결한다.

## 차단·재개 조건

TODO 해당 없으면 없음. blocked이면 원인, 미완료 단계, 부분 결과, 관련 이슈, 재개 조건을 적고 결론은 null로 남긴다.

## 완료 확인

- [ ] 실행 전 계획과 엔진/데이터 고정 증거
- [ ] 성공한 baseline + 서로 다른 변형 최소 2개
- [ ] 모든 시도/실패/종료코드 보존, 예정 시도 또는 사전 종료 조건 충족
- [ ] IS-only 선택 고정, 최종 평가와 OOS 노출/한계 고지
- [ ] 근거 있는 결론·교훈·다음 실험·필요한 후속 이슈
- [ ] 허용 파일만 변경, 원격 PR read-back; main 반영 여부 별도 명시

체크리스트는 자동 완료 판정기가 아니다. 하나라도 미충족이면 completed로 보고하지 않는다.
