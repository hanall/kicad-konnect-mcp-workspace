# C1 인계 증거 보존

보존 시각: 2026-10-12T06:28:53.521175+09:00

## 결론과 수량

원 exact 선별262개를 **실파일 archive260개 + alias metadata2개**로 구분해 보존했다. 원 origin relative path와 파일 bytes/SHA/size를 유지하며, symlink를 실제 tar member 또는 임의 regular 파일로 변환하지 않았다. alias 원문 target은 모두 `../../skills/kicad-schematic-quality`, 각 UTF-8 bytes36/SHA `b3833c2f0867515ca2c4ad5096312e58b7ab3953e878462439144531dbd920dd`이며 manifest에 `archived=false`, `metadata_only=true`로 기록했다.

```text
source_selection | tar_regular_members | alias_metadata | regular_payload_bytes
-----------------+---------------------+----------------+----------------------
262              | 260                 | 2              | 3034966
```

archive: `c1-evidence.tar.gz` (885455bytes)
archive SHA-256: `d8c36e0c338b3246283255d109a669ef0d183a5393a982bbc8db9512345138a8`
원 allowlist SHA-256: `5642fe497f79aeb575fdf56cfd4be58003f00f56de8640f09201f61003a0eff3`

이 디렉터리에서 새로 보존한 파일은 tar.gz/manifest.json/README.md 3개뿐이다. archive의 260파일을 작업트리나 docs에 펼치지 않았다. source 수정·stage·commit·push는 수행하지 않았다. 각 archived 파일과 alias 메타정보는 `c1-evidence.manifest.json`의 exact records를 따른다. archive 내부의 옛 선별 안내에는 개별 destination 제안이 남지만, 현재 실제 승인 보존 방식은 이3파일 bundle이다.

## 패키지·모델·CAD·변이 실행 차이

```text
id      | actual_model      | package | scope
--------+-------------------+---------+----------------------------------
C1-W    | claude-opus-5-5   | b274    | original_isolated_CAD_author
C1-G    | gpt-6-astra       | b274    | GUI_save_close_reopen
C1-I    | gpt-6.1-sol       | b274    | independent_read_only_review
C1-V    | gpt-6-astra       | c77     | existing_CAD_native_revalidation
C1-COLD | NONE              | c77     | NOT_RUN
```

b274 package SHA: `b274e7d851c129bb62402d1d71f18b43a772d29326ba612ce4cd2954233f4fbf`
c77 package SHA: `c77ca8ed6783532aaad86496f868f9d22af376c5756c9464c35938bdaf3ce3ca`

원 C1은 Claude 실제 CLI 모델 `claude-opus-5-5`가 b274로 작성했고, Root GUI 왕복 및 별도 독립 검토를 거쳤다. Root 모델은 turn_context 등록값, 독립 모델은 spawn 등록값으로 결속했다. 전체 모델 CLI/Root rollout은 넣지 않고 최소 모델 영수증만 보존했다.

초기 CAD SHA: `25503f5d765522f8191a92996779fdbf9a092da848adfbe52e8eb7f1da910b70`.
GUI 이후/current CAD SHA: `e6c1430b85bf357815b15eabce639948911566ddf489c416673a73e600170672`.
registry SHA: `c1669c3beba5f2e0b491f2d82ddcc6d7c248f63168f13390a186db40b72ebc25`.
semantic SHA: `39d1677c2d18ace6b273adbb56d72178f6723cc38837ef76284fb5324cd77382`.

초기 원 source bytes는 `gui-evidence/before/`에, 이후 source는 `isolation/case/project/`에 서로 구분돼 있다. live source를 과거 버전으로 복원하지 않았다. b274 초기 native / b274 root-post-gui native / c77 root-type-fixed fresh native의 package·source·argv·원rc는 별도 영수증이다. **c77는 같은 기존 C1 저장본을 새 수집기/검증기로 재검증한 것일 뿐 c77 cold 모델 작성 성공이 아니다.**

원 b274 boolean `schema_version=true` 변이는 caller copy SHA를 맞췄는데도 rc0/PASS survivor가 났다. 원 결함 result/report/변이 registry를 보존했다. 후행 c77는 기존 인과변이12+boolean1을 모두 거부했고 추가 타입 probe4도 거부했다. 정상/GREEN2·92 단위 gate는 별도 rc0 증거다. 이 정상 PASS와 expected mutation FAIL을 혼합해 전체 오류0로 표현하지 않는다.

원 정규 전체 gate FAIL make2/cargo101/`mock listen: AddressInUse`와 후속 source 무수정 기본 `make test` PASS make0을 둘 다 보존했다. 후속 Rust2513통과/0실패/50무시·Python175통과는 정규 기본 실행1회 결과이며 원 fixture 예약 공백을 수정한 것이 아니다. source-audit T01~T16은 별도 작업자의 범위이므로 이 bundle의 C1 완료에 흡수하지 않는다.

## 안전·정규화·readback

archive member는 exact source_relative_to_artifact_root와 같은 상대 path이며 absolute path, `..`, backslash, 중복 path, symlink, hardlink, 디바이스·특수파일을 거부했다. USTAR/사전순 member, uid/gid0, owner/group 이름 빈 값, mtime0, mode0644 또는0755로 정규화했다. gzip mtime0·filename 빈 값·압축레벨9다. memory build와 실제 보존 후 gzip/tar readback 모두에서 member260개·regular형식·SHA/size/정규화 metadata를 전수 확인했다. 파일을 실제로 extract하지 않았다.

선택한 파일 bytes·PDF 텍스트의 이메일/API key/Bearer/PEM, JSON 인증 실값, ELF·금지 확장자/경로를 검사했고 발견 후보0이었다. 원 credential/auth/계정DB/keyring/token, 고객 원문, native binary/AppImage/368MB Codex bundle/compiled cache는 포함하지 않았다. PNG5개는 이전에 직접 판독한 KiCad 캡처다. 선택된 raw test 로그는 bounded 원 fullFAIL/fullPASS를 유지하기 위한 것이며 1.68MB CLI 전체는 제외했다. 제한 패턴 스캔이 모든 형태의 은닉 정보 부재를 보장한다는 뜻은 아니다.

원 global/배터리 v0.2 본문8개와 글로벌 스킬8개의 baseline bytes SHA를 대상으로 selected-file exact clone이 없는지 대조했다. 보존한 b274/c77 snapshot은 대상 레포가 새로 만든 프로젝트독립 standard v0.1 candidate이며 원 global v0.2 본문을 그대로 복제한 archive가 아니다. 외부 원본문이나 원 바이너리 bytes는 다시 읽거나 복사하지 않았다.

## archive 내부 스크립트는 원 환경 증거

**archive 내부 원 스크립트는 원 host·runtime·절대경로의 실행 증거이며 재배치한 폴더에서 즉시 실행 가능한 설치본/명령이 아니다.** 기존 요청·변이 helper를 그대로 실행하면 원 evidence 출력 경로를 가리키거나 기존 결과를 덮어쓸 수 있다. 자동 실행·alias 재생성·원 project 복원은 하지 않는다.

새 host/root에서 검증하려면 caller가 별도 권위를 확정하고 KiCad/Konnect build·schema·library·계획·registry·새 source와 fresh native provenance를 결속해야 한다. native XML `design/source` 절대경로를 무시하거나 runtime hash를 임의 재봉인해 과거 PASS를 새 실행으로 꾸미지 않는다. 재현 명령 템플릿은 archive의 `c1-handover-selection/reproduction-commands.json`에 있으나 이 보존 단계에서 실행하지 않았다. archive를 열어볼 때도 새 빈 격리 폴더와 data-only 안전 정책을 쓰며 운영 프로젝트에 직접 풀지 않는다.

## 남은 제한

Title/Date/Rev 공백, R/C의 GUI/PDF pin번호 비표시, footprint4개 미할당을 유지한다. exact 핀/망/실선은 native XML/layout 증거로 대조했으며 ERC 기본 비활성4종도 공개돼 있다. c77 native PDF를 이 보존 단계에서 새 독립 시각 검토한 것은 아니다. GUI와 caller 환경 보충 증거를 native process 환경/AppImage 내부 직접 관측으로 올리지 않는다. PCB·동적·정격·제조·통전·인증·실물 안전 완료가 아니다.

Root의 후속 전체 evidence manifest가 이3파일을 별도 SHA로 색인할 예정이다. 이 README/manifest는 그 상위 manifest를 대신하지 않는다.
