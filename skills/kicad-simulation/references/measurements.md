# 측정 정의와 판정

이 문서는 측정 정의·엔진별 문법·판정 규칙·이론값 유도와 배치 모드 함정을 소유한다. 엔진 설치는 engines로 넘긴다.

## 측정 kind

| kind | 인자 | ngspice 문법 | LTspice 문법 | 뜻 |
|---|---|---|---|---|
| `FIND` | signal, at | `FIND v(out) AT=1m` | `FIND v(out) AT 1m` | 시각의 값 |
| `MAX` `MIN` `AVG` `RMS` `PP` `INTEG` | signal, from, to | `MAX v(out) FROM=2m TO=3m` | `MAX v(out) FROM 2m TO 3m` | 구간 통계·적분 |
| `WHEN` | signal, val, edge | `WHEN v(g)=2 RISE=1` | 동일 | 교차 시각 |
| `TRIG_TARG` | signal, trig_val, targ_val, edge | `TRIG v(out) VAL=0.5 RISE=1 TARG v(out) VAL=4.5 RISE=1` | 동일 | 두 교차 시각 차 |
| `AC_FIND_DB` | signal, at(Hz) | `FIND vdb(out) AT=10` | `FIND V(out) AT 10` → `(dB,°)` 파싱 | 주파수의 dB |
| `AC_WHEN_DB` | signal, val(dB), edge | `WHEN vdb(out)=16.99 FALL=1` | `WHEN mag(V(out))=<선형> FALL=1` | dB 교차 주파수 |
| `DERIVED` | formula | 계산 | 계산 | 다른 측정의 산술식 |

`DERIVED`의 식은 측정 이름·숫자·사칙연산·`abs sqrt log log10 exp min max`만 허용한다.

## 판정 규칙

- `err_rel = |측정 − 이론| / |이론|`, `tol_rel` 기본 0.02. 절대 기준이 맞는 양(dB, 작은 전압)은 `tol_abs`.
- 엔진 간 교차: 같은 넷리스트를 두 엔진으로 돌려 `|a − b| / |이론| ≤ 0.01`.
- 이론값은 모델 방정식에서 해석적으로 유도하고 유도를 보고에 남긴다. 예: RC τ=RC, v(τ)=V(1−e⁻¹), 10→90% 상승 = τ·ln 9. level 1 MOSFET 선형영역 Id = KP·(W/L)·((Vgs−Vt)Vds − Vds²/2)를 부하선과 연립. Shockley Vf = n·Vt·ln(I/Is+1), Vt = kT/q(27 °C = 25.865 mV). 단극 OP AMP 폐루프 이득 A/(1+βA), 대역폭 fp(1+βA).
- 측정 정의가 이론값과 같은 물리량인지(시각이 τ인지, 구간이 정상상태인지, 적분 구간이 충분한지) 적대적으로 다시 본다. 사양 예제: `projects/sim-validation-20261022/spec/spec.json`과 `theory.py`.

## 배치 모드 함정

- ngspice `-b`에서 `.meas ac … vdb(out)`만 있으면 저장 벡터를 정하지 못해 "no data saved … analysis not run"이 난다. `.save all`을 함께 둔다(`run_spice_simulation`은 AC 측정이 있으면 자동 추가).
- `ngspice -b -o run.log`를 쓰면 `.meas` 결과는 stdout이 아니라 로그 파일에 `name = value`로 기록된다.
- `.control run … .endc`를 넣으면 `.meas` 결과가 두 번 출력될 수 있다. 값은 같다.
- `.tran`과 `.ac`를 한 파일에 두면 측정이 섞인다. 해석별로 넷리스트를 분리한다(`run_spice_simulation`은 한 호출에 한 해석).
- 호환 모드(`ngbehavior`)는 넷리스트 파싱 전에 적용돼야 하므로 작업 디렉터리 `.spiceinit`로 준다. 홈 `~/.spiceinit`은 만들지 않는다.
- ngspice는 `gnd`를 접지로 받지만 LTspice는 `0`만 접지다.
- LTspice 24 로그는 평문 ASCII(CRLF)다. UTF-16으로 변환하면 깨진다.

## 검증 회로 5종 요약(2026-10-22, 네 경로 모두 2% 이내)

| 회로 | 판정 항목 | 이론값 |
|---|---|---|
| RC 스텝(1k, 1µ, 5 V) | v(τ)=3.1606 V, v(3τ)=4.7511 V, 10→90%=2.1972 ms | 지수 응답 |
| MOSFET level 1 게이트(Rg 100, Cg 10n, Vt 2, KP 0.5) | v_g(τ)=6.3212 V, t_Vth=223.1 ns, Vds_on=29.98 mV, Id_on=119.7 mA | RC·부하선 연립 |
| 단극 OP AMP 비반전(R1 1k, R2 9k) | 1 kHz 피크 0.99919 V, 10 Hz 19.9957 dB, f−3dB 39.96 kHz | A/(1+βA) |
| 반파 정류(Is 1e-14, n 1, RL 1k) | 피크 9.2872 V, Vf 0.7128 V | Shockley 반복해 |
| 프리차지(48 V, 47 Ω, 4700 µF) | I_pk 1.0213 A, P_pk 49.02 W, v(τ)=30.34 V, t95 661.8 ms, E_R 5.414 J | τ=RC, ½CV² |

재현: `make sim-verify`(시스템 ngspice), `python3 scripts/sim-validation-run.py --engine kicad-bundled`.
