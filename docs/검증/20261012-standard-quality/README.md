# 표준 회로도 품질 스킬 검증 근거 색인

이 폴더는 개발 호스트의 `.artifacts/`와 분리해 일반 Git으로 보존할 수 있는 검증 근거다. 설치할 정본은 [스킬 패키지](../../../skills/kicad-schematic-quality/SKILL.md)이며, 아래 압축 파일의 과거 코드나 변이 코드를 설치하지 않는다.

- [사용·설치·안전 원복과 지원 범위](../../agents/20261012-040121_standard-quality-user-guide.md)
- [자기완결 검증 보고서](../../보고서/20261012-040121_standard-quality.html)
- [최종 요구 대조 감사](final-audit.md)

## 근거 묶음

| 묶음 | 보존 범위 | 실파일과 메타데이터 | 정본 |
|---|---|---|---|
| 공통 | 세 기존 스킬 감사, MCP 모의 변이 37개, 문서 회귀 15개, T05, 최신 로컬 gate | 실파일 136개 | [압축](standard-evidence.tar.gz) · [manifest](standard-evidence.manifest.json) · [설명](standard-evidence.README.md) |
| C1 | b274 실제 작성·GUI 왕복, c77 기존 CAD 재검증, 원 boolean survivor와 교정, 원 전체 FAIL과 후속 PASS | 실파일 260개, alias 메타데이터 2개 | [압축](c1-evidence.tar.gz) · [manifest](c1-evidence.manifest.json) · [설명](c1-evidence.README.md) |
| X1 | c77 실제 작성, GUI 저장·재열기, fresh native, 독립 판독, 실입력 변이 20개·GREEN2 | 실파일 384개, alias 메타데이터 2개, 중복 media 참조 24개 | [압축](x1-evidence.tar.gz) · [manifest](x1-evidence.manifest.json) · [설명](x1-evidence.README.md) |

세 묶음은 실제 심볼·과제·버전·package SHA에 한정한 증거다. 현재 패키지 identity는 `c77ca8ed6783532aaad86496f868f9d22af376c5756c9464c35938bdaf3ce3ca`다. 일반 Git 파일이며 Git LFS나 GitHub Actions를 도입하지 않았다. 이번 작업에서는 commit·push를 수행하지 않았다.

## 검증·재현 경계

각 manifest에는 원 경로, SHA-256, 크기와 제외·중복 보존 방식이 있다. 압축은 regular file만 담고 경로 이탈·실행 파일 magic·민감값 후보를 검사했다. 실제 alias를 압축에 넣지 않았으며, 중복 media는 같은 bytes를 가진 member 참조로 보존한다.

레포 루트에서 `sha256sum -c docs/검증/20261012-standard-quality/SHA256SUMS`로 공개 근거의 bytes를 재확인한다. 압축 해제는 기존 프로젝트가 아닌 새 빈 디렉터리에만 한다. archive 안의 helper는 당시 환경의 원 실행 증거이며, 다른 위치에서 즉시 재실행할 수 있는 설치 프로그램이 아니다. 새로운 프로젝트 검증은 사용자 가이드의 명시적 CLI 입력과 새 native 증거를 사용한다.

가이드의 `.artifacts/` 링크는 개발 호스트의 상세 조회용이다. 다른 checkout에서는 이 폴더의 manifest와 압축 내부 논리 경로로 같은 근거를 찾는다. 자격증명·개인 계정 식별정보·전체 모델 rollout·runtime binary·원 고객 자료는 이 보존 묶음에 포함하지 않는다.

## 해석 시 지킬 제한

- 최신 로컬 gate는 Python 190 통과, Rust 2513 통과·실패0·ignored50이다. 표준 gate 107개는 Python 190개에 포함되므로 합산하지 않는다.
- T05는 극성 의미 판정만 수용했다. 두 응답의 JSON code fence 형식 편차와 `format_instruction_exact_pass=false`를 보존한다.
- C1의 c77 결과는 기존 저장본 재검증이며 c77 Claude cold 작성 결과가 아니다. X1은 current c77의 Codex 실제 작성이다.
- X1 GUI 전후 PDF의 17단어 text bbox 차이를 숨기지 않는다. 동일 옵션의 ink raster와 XML·layout semantic 대조는 일치했지만 CAD 원 field bytes까지 동일하다고 주장하지 않는다.
- `PWR_FLAG` 자동 삽입은 현재 guard에서 미지원이다. 제조용 footprint·PCB·정격·동적 성능·통전·실물 안전·인증은 검증하지 않았다.
- 원 upstream test의 포트 경합 FAIL과 이후 기본 gate PASS를 모두 남겼다. 포트 fixture 취약성을 수정한 것은 아니다.
