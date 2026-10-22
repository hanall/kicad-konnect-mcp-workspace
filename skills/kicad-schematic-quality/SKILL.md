---
name: kicad-schematic-quality
description: KiCad 회로도의 신규 설계, 가독성 재작성, 승인된 전기 변경, 읽기 전용 품질 검토를 요구·전기·시각·증거 관문으로 분리한다. 단순 파일 질의, PCB 배치·배선, 제조 발주에는 적용하지 않는다.
---

# KiCad 회로도 품질

> 판본: v0.1 candidate. 이 판본의 모델·도구·과제 지원은 패키지 밖에서 생성한 **동일 패키지 SHA의 실행 receipt**로만 판단한다. 이 문서만으로 지원이나 성공을 주장하지 않는다.

## 먼저 권위와 입력을 확정한다

프로젝트의 지침·요구·승인·설계 계약이 이 스킬보다 우선하며, 더 강한 안전 제한은 그대로 유지한다. 다음 입력을 실제 경로와 값으로 받아야 한다.

- 작업 모드, 대상·비대상, 납품 범위
- `workspace-root`, `project-dir`, 루트 회로도와 쓰기 허용 파일
- 요구·제조사 원문·핀 자료와 그 원문 bytes SHA-256
- 선택한 profile과 프로젝트별 수치
- 단일 CAD 작성자, 검토자, 현재 잠금과 작성 채널
- launcher, config, server cwd, 기대 version·commit
- 검토자가 사전 고정한 registry·semantic 계약과 새 evidence 경로
- 현재 프로젝트가 허용한 GUI 또는 MCP 권한

필수 입력이 없으면 질문하거나 `미확인`으로 남긴다. 값 `0`, 빈 목록, 관례값, 이전 프로젝트 값을 합성하지 않는다. 이 패키지는 GUI 편집, commit, push, 제조, 통전 권한을 부여하지 않는다.

## 모드를 하나 고른다

| 모드 | 기준 | 허용 결과 |
|---|---|---|
| `design` | 요구·원문·실제 핀으로 새 계약 작성 | 검토된 계약 범위의 신규 회로 |
| `rewrite` | 시작 CAD의 부품·물리 핀·망·값·footprint 전단사 | 표현 재구성, 무승인 전기 변경 0 |
| `change` | 승인 출처와 전후 기대값 | 승인된 차이만 존재 |
| `review` | 현재 저장본·요구·증거 | 관측·근거·제안만 보고, CAD 쓰기·저장 0 |

모드가 섞이면 전기 변경을 별도 승인 항목으로 분리한다. `rewrite`에서 발견한 전기 오류를 몰래 고치지 않는다. `review`에서는 좋은 수정안을 찾아도 저장하거나 자동 수정하지 않는다.

## 항상 지킬 안전 규칙

1. `.kicad_sch`, `.kicad_pro`, `.kicad_sym`, `.kicad_pcb`, library table을 텍스트·스크립트로 생성·수정하지 않는다.
2. 현재 프로젝트가 승인한 정식 CAD 채널만 사용한다. GUI와 MCP를 동시에 쓰지 않고, 살아 있는 lock을 삭제·우회하지 않는다.
3. saved file과 live editor 상태를 별도 원본으로 취급한다. 한쪽 실패를 다른 쪽으로 조용히 대체하지 않는다.
4. 실제 runtime의 도구 이름·schema·version·commit을 확인한다. 고정 도구 수나 오래된 예제를 권위로 쓰지 않는다.
5. 심볼의 모든 unit과 물리 pin number/type/endpoint를 완전하게 확인한다. 조회 성공이어도 pin inventory가 비거나 unit·상속 정보가 빠지면 다른 API·library source·배치본 readback으로 닫기 전에는 `미확인`이다. 일반 부품표나 도형만 보고 극성·핀을 추측하지 않는다.
6. 계획·allowlist·원문 SHA가 고정되기 전에 CAD를 쓰지 않는다. 첫 쓰기 뒤 만든 계획을 사전 계획으로 소급하지 않는다.
7. 읽기 전용 결과, 부분 PASS, ERC 0, PDF 구조 PASS를 제조·통전·정격·동적 성능·실물 안전 승인으로 승격하지 않는다.

## 필요한 문서만 읽는다

- 모든 모드의 범위·계획·재개: [공통 흐름](references/common-workflow.md)
- 핀·망·전원·반환 계약을 설계하거나 대조할 때: [전기 규칙](references/electrical-rules.md)
- 배치·가독성·전페이지 판독이 범위일 때: [시각 규칙](references/visual-rules.md)
- 검증 또는 완료 판정을 할 때: [검증과 증거](references/verification.md)
- MCP·GUI·CLI를 실제로 사용할 때: [도구 호환성](references/tool-compatibility.md)
- 기존 `konnect`, `kicad-schematic`, `kicad-review` 지침과 함께 쓸 때: [기존 스킬 교정](references/legacy-skill-overrides.md)
- 일반 회로는 [general profile](profiles/general.md), 전력변환 회로만 [SMPS profile](profiles/smps.md)

모든 reference와 profile을 습관적으로 읽지 않는다. 일상적인 작은 승인 변경에는 해당 페이지 계획·영향 전기 계약·필요 검증만 적용하며, 과제와 무관한 대규모 평가나 다중 모델 실행을 강제하지 않는다.

## 최소 흐름

```text
authority/input -> mode -> baseline -> plans before write
                -> current capability -> single-writer authoring
                -> readback -> save/reopen -> native evidence
                -> electrical + visual + provenance verdicts
```

`design`, `rewrite`, `change`는 [공통 계획](assets/common-plan.md), 루트 포함 각 회로도의 [페이지 계획](assets/page-plan.md), `plan-index.json`을 첫 CAD 쓰기 전에 완성한다. [예제](assets/plan-index.example.json)는 복사 후 실제 경로·모드·allowlist·읽기 전용 라이브러리로 바꾼다. 각 계획은 구체 본문과 원문 SHA를 가져야 한다.

`review`는 기존 계획이 있으면 읽고, 없으면 미수신으로 기록한다. 검토를 위해 사후 작성 계획을 꾸미지 않는다. 결과는 [검토 기록](assets/review-record.md)에 deterministic 결과와 사람의 시각 판독을 분리해 남긴다.

## 상태 보고

`계획 완료`, `작성 중`, `정적 계약 통과`, `시각 자체 검토`, `독립 읽기 검토 통과`, `제한 범위 회로도 인계`를 구분한다. 각 문구에는 대상 SHA, 검사 범위, 빠진 관문, 경고·비활성 규칙·예외, 다음 결정 주체를 붙인다.

현재 판본은 **candidate**다. 실행하지 않은 모델·OS·도구·회로 유형은 `미실행` 또는 `미지원`으로 남기며, 과거 판본 receipt를 이름만 바꾸어 승계하지 않는다.
