# 제조사 SPICE 모델 도입

이 문서는 제조사 SPICE 모델의 도입·검증·보고 절차를 소유한다. 필드 문법은 kicad-sim-fields로 넘긴다.

핵심 질문은 "핵심 부품의 모델을 ngspice에서 쓸 수 있는가"다. 공급망 지침은 모델 파일에도 적용한다.

## 절차

1. **출처 확인**: 제조사 공식 제품 페이지의 "Design & development / Simulation models"에서만 받는다. 포럼·미러 사본은 쓰지 않는다. 받은 파일은 새 빈 디렉터리에 두고 SHA-256을 기록한다. 압축 파일은 격리 디렉터리에서 풀고 스크립트를 실행하지 않는다.
2. **형식 확인**: `file`과 `head`로 텍스트 SPICE(`.lib`, `.cir`, `.sub`, `.mod`)인지 본다. `$ENCRYPTED`, `.prot`/`.unprot` 사이 난독화, 바이너리면 **암호화 모델**이며 ngspice·LTspice·Qucs-S에서 쓸 수 없다. 이때는 제조사가 지정한 시뮬레이터(Windows 전용인 경우 이 호스트에서 불가)뿐이므로 사용자에게 보고하고 대체 모델(행동 모델, 데이터시트 기반 자작 서브서킷)을 제안한다.
3. **문법 계열**: 헤더·주석으로 PSpice/HSPICE/LTspice 문법인지 본다. ngspice에서는 `ngbehavior`를 `ltpsa`(LTspice+PSpice), `psa`, `lta`, `hsa` 중 하나로 지정한다. `run_spice_simulation`의 `ngbehavior` 인자가 작업 디렉터리 `.spiceinit`로 적용한다.
4. **서브서킷 핀 순서**: `.subckt NAME p1 p2 …` 줄의 순서를 데이터시트 핀 기능과 대조해 `Sim.Pins`(`1=p1 2=p2 …`)를 만든다. 심볼 핀 번호와 모델 단자 순서가 다르면 반드시 매핑한다. 순서를 추측하지 않는다.
5. **모델 지정**: `set_simulation_model`로 `device=SUBCKT`, `library=<절대경로>`, `name=<subckt>`, `pins=<매핑>`. `export_spice_netlist`에서 `missing_includes=[]`, `unassigned_models=[]`를 확인한다.
6. **제조사 예제 재현**: 제조사 데이터시트·앱노트의 전형 회로 하나를 먼저 돌려 그래프 수치(이득, 기동 시간, 리플)를 재현한다. 재현되지 않으면 모델·문법·핀 문제를 먼저 푼다.
7. **변수 스윕**: 입력전압·부하·부품 편차를 바꿔 반복 실행하고 결과를 표로 남긴다. 각 실행의 작업 디렉터리·로그·넷리스트 SHA를 보고에 적는다.

## 엔진별 호환 메모

- ngspice 공식 문서: "일반적으로 PSPICE, HSPICE, (많은) LTSPICE 모델이 ngspice와 호환"되며 "상용 공급사가 암호화한 모델은 쓸 수 없다". TI 모델은 PSpice `.lib`를 `set ngbehavior=ltpsa`로 쓰는 예가 공식 문서에 있다.
- KiCad 편집기 시뮬레이터는 호환 모드를 설정 대화상자에서 고른다. kicad-cli 넷리스트에는 호환 모드가 들어가지 않으므로 MCP·CLI 실행 시 `ngbehavior`를 따로 준다.
- LTspice 문법 전용 소자(예: `VDMOS` 확장, 행동 소자 일부)는 ngspice에서 `lta`로도 안 될 수 있다. 그때는 `ltspice` 엔진으로 교차 실행한다.
- Qucs-S는 ngspice 호환 모드 설정을 `Simulation → Simulators Settings`에서 둔다.

## 보고 양식

| 항목 | 값 |
|---|---|
| 부품 | 제조사·품명·패키지 |
| 모델 파일 | 경로, SHA-256, 게시 버전·날짜 |
| 형식 | 텍스트/암호화, 문법 계열, ngbehavior |
| 핀 매핑 | `Sim.Pins` |
| 재현한 제조사 예제 | 회로·그래프·일치 여부 |
| 제한 | 모델이 표현하지 않는 특성(열, 기생, 포화 등) |
