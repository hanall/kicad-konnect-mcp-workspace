# X1 인계 증거 보존

보존 시각: 2026-10-12T06:49:32.999778+09:00
상태: **합성 X1 범위의 actual cold 작성·GUI 왕복·native 정적·독립 검토·실입력변이 증거 보존**. 제조·정격·동적·실물 안전 완료가 아니다.

## 수량과 해시

```text
source_records | tar_regular_members | alias_metadata | duplicate_media_metadata
---------------+---------------------+----------------+-------------------------
410            | 384                 | 2              | 24
```

archive regular payload: 2,862,978bytes.
archive 압축 크기: 842,610bytes.
archive SHA-256: `5a48aa895d105d3eb5fa72424e9781f926aade5dad2f7f8498ef423410d91413`.
선별 JSON SHA-256: `8c094cf1d5c61dd18327876c899fe487c952839ff7f5504ef8b55376ddc51668`.

원 sourceD 상대 path를 tar member 이름으로 그대로 유지했다. alias2개는 target `../../skills/kicad-schematic-quality`, 각36bytes/SHA `b3833c2f0867515ca2c4ad5096312e58b7ab3953e878462439144531dbd920dd`의 metadata_only로 보존하고 실제 symlink나 임의 regular 대체물은 tar에 넣지 않았다. 동일 media24개는 원 path/SHA/size와 archive의 byte-exact canonical member 참조를 manifest에 기록했다. 이중 정상 변이 PDF21사본과 PNG3개를 중복 보존하지 않았다.

유일한 인과 변이 `09-pdf-damaged/schematic.pdf`는 GUI후 원 PDF의 정확한 반길이 truncation이며 원 손상 bytes20305를 보존했다. 이를 유효 PDF나 새 native PASS로 합성하지 않는다. manifest의 중복 참조는 모든 원파일을 실제로 펼쳤다는 뜻이 아니므로 내부 원 `SHA256SUMS`를 불완전 추출 디렉터리에 무조건 실행하지 않는다.

이 디렉터리의 새 파일은 `x1-evidence.tar.gz`, `x1-evidence.manifest.json`, `x1-evidence.README.md` 3개다. 원 자료·원 CAD·계획·oracle·package는 수정하지 않았고 stage/commit/push와 모델/계정/GUI/MCP 실행도 하지 않았다.

## 실제 모델과 현재 package

```text
actor          | model        | cli      | package | execution
---------------+--------------+----------+---------+-------------------------
X1_author      | gpt-6-astra  | 0.162.1  | c77     | actual_cold_authoring
Root_GUI       | Root_receipt | KiCad10  | c77     | save_close_reopen
independent    | separate     | read-only| c77     | blind_stage1_plus_checks
```

package SHA: `c77ca8ed6783532aaad86496f868f9d22af376c5756c9464c35938bdaf3ce3ca`.
registry SHA: `b67c028146ddb06e1c3f5e5510fbfd275d6ab3925d2e5a772bac7ac528e55980`.
semantic SHA: `3c5adc5d5f80e30b07697a7c8721c0457acb9c2adbb59a90959ad2f985d15f6b`.

모델 관측은 `x1-managed/model-observation.public.json`의 닫힌 source=cli prefix 3개 turn_context/완료 turn 관측이다. 실제 등록 모델은 gpt-6-astra/high이며 내부 provider routing이나 가중치를 별도 검증한 것은 아니다. 작성자 자체보고의 모델 미확인은 이 public 부모 관측으로 보완했다. raw rollout/전체 모델 로그/계정 probe 상세를 다시 열거나 배포하지 않았다.

C1의 원 b274 실제 작성과 기존 CAD를 c77로 재검증한 사실을 X1 cold 성공으로 이름만 바꾼 것이 아니다. **X1은 별도 합성 과제·별도 oracle/계획·current c77 package·별도 실제 CLI 작성 receipt**다. 원 b274 결함과 C1 역사 기록은 C1 bundle에 그대로 남아 있다. 한 과제의 성공을 모든 모델·회로·OS 지원으로 확대하지 않는다. 이 X1 bundle에는 package17파일 identity만 포함하고 원 sourcev0.2나 중복 package 본문/바이너리를 복제하지 않았다.

## 작성 전 계획과 GUI 전후

GUI전 작성 최종 schematic SHA: `b48ec758ed384e0ab21fc944a046c372e05d1007247d8d6568246d52ed4a5d33`.
GUI후/current schematic SHA: `fec0092cb81f57ca5e9d700a40978fd12503d161ab4079e5dd5120f9e63b522e`.
GUI후/current project SHA: `f9656afbb2b56bdbe1ad54769c6174b56133df4b8a0449e0e511dde7aec6b590`.

```text
pre_CAD_seal -> c77_X1_cold_author -> b48_native22
            -> actual_GUI_save_close_reopen -> fec_root_post_gui_native
            -> blind_stage1_seal -> independent43checks + authorized_verifier_rc0
            -> actual_input20rejects + controls_GREEN2
```

원 `PRE-CAD-SEAL`은 2026-10-11T21:09:45.654367+00:00, Root closeout의 firstCAD mutation 관측은 2026-10-12T06:10:41.471967+09:00이며 계획 SHA는 변하지 않았다. 첫 create의 필수 MCP journal과 stage별 source앞뒤 영수증/요청/readback을 선별해 그대로 보존했다. 독립 검토자의 verdict는 first-mutation 원 chronology를 별도 재구성하지 않았음을 공개하며 이를 후행 보존으로 소급 완료시키지 않는다.

GUI 왕복은 전용 DISPLAY:188/port6170/16GiB에서 실제 정식 저장·닫기·재열기 후 같은 저장본으로 닫은 Root receipt다. b48와 fec 및 전후 .pro를 실제 source 사본으로 구분했다. viewer 현재 상태나 actual native 자식 환경을 이 보존자가 새로 직접 관측한 것은 아니다.

## 원 실패와 후속 정상은 따로 보존

- 원 API arg 누락·unit 미포함 INCOMPLETE·무변화 mutation 거부는 `preserved-failures.json`과 해당 stage 원 rc/응답에 남긴다. 시도 전체가 최초 무실패였다고 쓰지 않는다.
- `21-native-final`의 native-netlist 원 rc1은 임시 AppImage 추출폴더의 `AppRun not found` 환경 실패다. 원 collection-failure/log와 extraction-recovery receipt를 보존하고 source 변경 없이 `22-native-final`에서 새 native PASS를 받은 사실과 구분한다. 원 실패를 회로 RED라고 과장하지 않는다.
- 독립 verifier 첫 rc2는 허용 report path가 project-root 밖인 경계거부다. 별도 명시 승인 이후 새 project안 report는 rc0이다. 원 rc2를 지우지 않고 회로 FAIL로도 바꾸지 않는다.

## 독립 판독·43대조·17 bbox 차이

독립 정본은 작성자 설명이나 candidate evidence를 보기 전 `BLIND-OBSERVATION`을 봉인한 1단계의 실제 GUI/PDF 전체·회로확대 읽기다. 2단계에서 `roundtrip.json`의 `visual_root/title_block`에 노출된 내용과 Root 설명은 보충 단계이며 최초 답안을 소급 보완한 것으로 합치지 않는다.

독립43대조는 blocking failure0, 전기 XML semantic/layout geometry와 동일옵션 PDF ink raster는 일치했다. 그러나 PDF text-layer bbox는 **52단어 중17단어의 수직 font metric 차이**가 exact 불일치다. 전후 XML/PDF bytes도 달라졌으므로 모든 출력조건 pixel 동일이나 CAD field 원 bytes 좌표 전후 직접 비교 완료로 확대하지 않는다. 원 검사 JSON·불일치 관측·렌더 명령/해시·blind seal/최종 verdict를 함께 보존했다.

이 보존자가 본 GUI5개는 개인정보 노출 확인을 위한 화면 판독이며 독립 reviewer의 새 holdout 검토를 대신하지 않는다. 이 단계는 새 verifier/native/모델 변이를 실행하지 않았다.

## 실입력20거부 + GREEN2, footprint NOT READY

```text
check                     | count | expected_result
--------------------------+-------+----------------
causal_native_mutations   | 12    | rc1_FAIL
original_bool_replay      | 1     | rc1_FAIL
strict_type_probes        | 4     | rc1_FAIL
forbidden_scope_claims    | 3     | rc1_FAIL
normal_control_GREEN2     | 2     | rc0_PASS
```

survivor0·원 CAD/registry/semantic/native source/report 전후SHA 불변. scope3개는 금지 승격을 거부하는 검사이지 PCB 거리·정격·제조 알고리즘을 실제 검증한 것이 아니다.

준비 script d99 SHA: `d99c8186cdc230169bf121da17fc4cab6d271de9fbe179c8fc2b48545534f6a5`.
실행 script bd60 SHA: `bd60cead796c443f00b89d9f24ff99de83b32a93c3f8b98724bbe95b4ab7a81a`.

실제 review input을 directory가 아니라 단일 `dispatch-records.json`으로 수용하도록 GO 이전에 argument 경로 처리만 수정했고, 원 준비본/기존 manifest/차이/AST inventory/실행결속 receipt를 보존했다. causal·expectation·판정식을 완화해서 GREEN을 만든 것으로 바꾸지 않는다. 이 보존 단계에서 suite를 추가 실행하지 않았다.

`run_design_review`는 footprint 미할당5개를 error로 보고하고 verdict **NOT READY**다. 실행 failed/diagnostic0와 BOM error5를 섞어 시스템 오류0/제조 준비완료라고 말하지 않는다. native ERC 오류0/경고0/개별제외0 및 기본 비활성4종은 별도다. decoupling `pcb_distance_checked=false`, power rail0 findings는 정격 검사가 아니다. Title/Date/Rev 공백·R/C 핀번호 GUI/PDF 기본숨김도 유지한다.

## caller 환경·privacy·압축 readback

native/review caller environment의 HOME/XDG/APPIMAGE/launcher/cwd/실행 argv와 GUI 설정 before8파일 SHA/after변경0 및 새 cvpcb1개 metadata만 보존했다. native-home/backend-home의 실제 파일, private config/requirements/before.json, runtime/work/tmp/native-runtime/run-managed, 원 인증/토큰/계정DB/probe 상세/원 binary/고객 원문은 포함하지 않았다. 환경 JSON은 caller 구성과 상속 경로 증거이며 native 자식 `/proc` 환경 직접관측이 아니다.

선택한 텍스트/중첩JSON의 민감 실값·email/APIkey/Bearer/PEM와 정상 PDF text를 검사했고 flag0이다. 의도된 damaged PDF는 검증된 안전 원 PDF의 정확한 prefix임을 확인했다. PNG는 합성 KiCad 화면이며 GUI5개를 직접 privacy 판독했다. 이는 제한된 패턴/판독 범위이며 모든 은닉 정보 부재의 수학적 보증이 아니다. 원 global/배터리 v0.2 본문 baseline SHA와 exact clone0을 확인했다.

USTAR 사전순, uid/gid0·owner명빈값·mtime0·mode0644/0755·gzipmtime0/filename빈값으로 정규화했다. absolute/traversal/backslash/중복 path·symlink/hardlink/특수파일/ELF를 거부하고 regular384개를 압축 전후 SHA/size/metadata 전수 readback했다. 실제 파일을 펼치지 않았다. public 최종 문서2개는 아직 작성중인 별도 범위라 포함하지 않는다.

## 원 스크립트는 실행 증거이지 재배치 설치본 아님

**archive 내부 스크립트/요청/argv는 원 환경 증거이며 새 폴더로 옮겼다고 즉시 실행할 설치본이 아니다.** 원 absolute `design/source`, package/library/runtime 경로, 없어진 private runner/HOME, alias와 중복 media의 metadata-only 상태를 무시하면 재현이 아니다. 자동 실행·alias 생성·원 evidence 덮어쓰기·runtime input hash 임의 재봉인을 하지 않는다. 별도 승인된 새 격리 root에서 정식 tool/version/schema/source/계획/oracle와 fresh native provenance를 결속해야 한다.

PCB·동적·정격·실물 안전·제조·통전·인증 완료가 아니며 c77/SHA/과제 범위 변경 후 이 결과를 자동 승계하지 않는다. Root의 상위 최종 evidence manifest가 이3파일을 별도 색인할 예정이다.
