# 표준 회로도 품질 근거 선별 보존

## 결론과 경계

package17파일 identity `c77ca8ed6783532aaad86496f868f9d22af376c5756c9464c35938bdaf3ce3ca`에 결속한 표준 MCP 모의변이37/37, public 문서안전 회귀15개, 실제 T05 읽기전용 극성 판정, 최신 정규 gate를 선별 보존했다. 원 artifact는 수정하지 않았다. 설치 binary·global 구식 스킬 본문·rawschema전체·원 모델 raw로그·runtime/credential/auth·토큰·고객/계정·전체 rollout·CURRENT는 포함하지 않는다.

| 근거 | 결과 | 한계 |
|---|---|---|
| MCP 모의변이 |37/37 검출, 원RED/GREEN2 보존|FakeTransport/가짜 STDIO. 실제 CAD/MCP 작성 성공 아님|
| 현재 표준 테스트 |107=기존 core92+문서안전15, rc0|최종 root raw로그가 정본. mcp-dev stage92 증거는 역사 범위|
| 최신 전체 root |Python190, Rust2513/실패0/ignored50, make rc0|원 full FAIL 존속, upstream port 경합 미수정|
| T05 실제 모델 |claude-opus-5, apiKeySource=none, case-a REJECT / case-b 극성 sub-gate ACCEPT|둘 다 g0_authoring_allowed=false. 둘 다 JSON code fence 형식 편차: 의미PASS/형식정확PASS 아님|
| 실제 C1/X1 |별도 c1-evidence archive|여기에 중복 포함하지 않음. actual와 모의37을 합산하지 않음|

## 파일과 무결성

- `standard-evidence.tar.gz`: regular 136파일, 원 D상대 경로 보존, USTAR, uid/gid/mtime0, mode0644, gzip filename빈값/mtime0.
- archive SHA256 `d691bdcc6a291e748921aed4608ea4a60313b68092290478830e7cd5a7bfd1f4`, size 849256byte.
- `standard-evidence.manifest.json`: 각 원본의 path/size/SHA, 원manifest 대조, 안전검사, alias metadata를 기록한다.
- alias는 `.agents/.claude` 링크의 target 문자열만 metadata로 기록했다. archive symlink/hardlink/special member0.
- tar 역판독 size/SHA, 원본 재판독 size/SHA, 쓰인 archive bytes 전체 readback을 확인했다. email/token/PEM/ELF 후보 검사0. 알려지지 않은 모든 secret의 보편 부재를 보장하는 표현은 사용하지 않는다.

## 역사 snapshot과 외부 참조

`docs-safety-test/final-manifest.json`과 receipt의 당시 사용자 가이드/HTML SHA는 현재 마감 writer 문서와 다르다. 부모 승인대로 원bytes를 보존하고 차이를 manifest에 공개했다. 현재 문서/HTML은 포함하지 않는다. 현재 public test source SHA는 대조 일치이고 최신107/190은 `final-*` raw로그 및 final-gate-summary.json으로 별도 결속한다. 마감문서에 대한 코드블록·링크·안전회귀의 최종 검증은 부모가 담당하며 이 archive가 선행 성공을 소급하지 않는다.

`polarity-g0/input-manifest.json`은 봉인 inputs 및 package17파일 SHA를 가진다. manifest의 전체 원files를 원위치에서 readback했고 현재 정본 package17파일도 대조했다. package본문과 설치 LED/binary는 복제하지 않으므로 excluded 원manifest 참조는 외부 원자료 pointer다. T05 최소 model receipt는 `upstream-flake-probe/standard-handover-selection/model-receipts/` 아래 명시된 허용필드만 투영했으며 원normalized/model receipt SHA를 함께 기록했다. 원 normalized 판정은 그대로 포함하지만 raw 모델로그·auth본문·runtime/명령 mount 기록은 제외했다.

source-audit README/audit.json의 fresh schema/global source/실행 경로 참조는 provenance pointer다. rawschema전체나 구식 global본문을 이 archive가 재배포하거나 완전한 원자료 묶음으로 제공하지 않는다. mcp-dev manifest가 SHA로 참조한 integration-audit proof4개는 제한된 모의 evidence만 포함했다.

C1/X1 실증 및 옛 원fullFAIL/후속175PASS의 원로그는 별도 `c1-evidence.tar.gz` 쪽에서 보존한다. 이 archive는 최신190/107을 중심으로 하며 전체gate PASS가 포트 TOCTOU 취약성 수정, 모든 회로/모델 지원, 제조/통전/실물 안전 승인이라는 뜻은 아니다.

## helper와 재현 범위

mcp-dev run_mutations.py 및 mutant .py는 당시 실행의 원 evidence다. source/helpers 내부의 절대경로를 손으로 rebasing하지 않았다. **artifact helper는 원실행 증거이지 재배치 실행의 재현 보장0**이다. 이 보존 작업에서는 helper/test/full make/model/MCP/GUI를 추가 실행하지 않았다. archive 검증은 stdlib 정적 판독/해시/USTAR 역판독만 사용했다.

소스: `.artifacts/20261012-040121-standard-quality`. 원 WIP·upstream·기존 c1 archive·원FAIL·원receipt 변경0, 새 dependency/설치/commit0.
