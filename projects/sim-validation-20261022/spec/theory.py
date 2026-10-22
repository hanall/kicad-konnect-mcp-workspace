#!/usr/bin/env python3
"""검증 회로 5종의 이론값을 계산하고 spec.json을 생성한다.

각 회로는 엔진 중립 SPICE 본체(netlist_body)와 KiCad Sim 필드, 측정 항목을 갖는다.
이론값은 모델 방정식(SPICE level 1 MOS, Shockley 다이오드, 단극 OP AMP)에서
해석적으로 유도한다. 허용 오차는 그릴링 가정 5: 이론값 대비 2%, 세 경로 상호 1%.
"""
import json
import math
import sys
from pathlib import Path

K_B = 1.380649e-23
Q_E = 1.602176634e-19
T_NOM = 300.15  # SPICE 기본 27 °C
V_T = K_B * T_NOM / Q_E


def circuit_01_rc_step():
    r, c, v = 1e3, 1e-6, 5.0
    tau = r * c
    return {
        "id": "01-rc-step",
        "title": "RC 과도응답 (시정수)",
        "purpose": "엔진의 과도해석 기본 정확성. tau=RC, 10-90% 상승시간=tau*ln(9)",
        "analysis": {"type": "tran", "tstep": "1u", "tstop": "5m"},
        "netlist_body": [
            "* 01 RC step response",
            "V1 in 0 PULSE(0 5 0 1n 1n 10m 20m)",
            "R1 in out 1k",
            "C1 out 0 1u",
        ],
        "kicad": {
            "components": [
                {"ref": "V1", "lib_id": "Simulation_SPICE:VPULSE", "sim_params": "y1=0 y2=5 td=0 tr=1n tf=1n tw=10m per=20m"},
                {"ref": "R1", "lib_id": "Device:R", "value": "1k"},
                {"ref": "C1", "lib_id": "Device:C", "value": "1u"},
            ],
            "nets": {"in": ["V1.1", "R1.1"], "out": ["R1.2", "C1.1"], "GND": ["V1.2", "C1.2"]},
            "directives": [".tran 1u 5m"],
        },
        "measurements": [
            {"name": "v_at_tau", "kind": "FIND", "signal": "v(out)", "at": "1m",
             "theory": v * (1 - math.exp(-1)), "unit": "V", "tol_rel": 0.02},
            {"name": "v_at_3tau", "kind": "FIND", "signal": "v(out)", "at": "3m",
             "theory": v * (1 - math.exp(-3)), "unit": "V", "tol_rel": 0.02},
            {"name": "t_rise_10_90", "kind": "TRIG_TARG", "signal": "v(out)",
             "trig_val": 0.5, "targ_val": 4.5, "edge": "RISE=1",
             "theory": tau * math.log(9), "unit": "s", "tol_rel": 0.02},
        ],
        "theory_notes": {"tau_s": tau},
    }


def circuit_02_mosfet_gate():
    rg, cg, vg = 100.0, 10e-9, 10.0
    vto, kp, vdd, rl = 2.0, 0.5, 12.0, 100.0
    tau = rg * cg
    t_vth = tau * math.log(vg / (vg - vto))
    # level 1 선형영역: Id = KP*W/L*((Vgs-Vt)*Vds - Vds^2/2), W/L=1, 부하선 Id=(VDD-Vds)/RL
    # => (kp/2) Vds^2 - (kp*(vg-vto) + 1/rl) Vds + vdd/rl = 0
    a = kp / 2
    b = -(kp * (vg - vto) + 1 / rl)
    c = vdd / rl
    vds_on = (-b - math.sqrt(b * b - 4 * a * c)) / (2 * a)
    assert vds_on < vg - vto, "선형영역 가정 위반"
    id_on = (vdd - vds_on) / rl
    return {
        "id": "02-mosfet-gate",
        "title": "MOSFET 게이트 구동 스위칭 (level 1)",
        "purpose": "게이트 RC 충전, Vth 도달 시각, ON 상태 Vds/Id의 level 1 모델 해석해 비교",
        "analysis": {"type": "tran", "tstep": "1n", "tstop": "20u"},
        "netlist_body": [
            "* 02 MOSFET gate drive switching",
            "VDD vdd 0 DC 12",
            "VG gsrc 0 PULSE(0 10 0 1n 1n 50u 100u)",
            "RG gsrc g 100",
            "CG g 0 10n",
            "RL vdd d 100",
            "M1 d g 0 0 NM1 W=100u L=100u",
            ".model NM1 NMOS(LEVEL=1 VTO=2 KP=0.5 LAMBDA=0 TOX=1e-7 CGSO=0 CGDO=0 CBD=0 CBS=0)",
        ],
        "kicad": {
            "components": [
                {"ref": "V1", "lib_id": "Simulation_SPICE:VDC", "sim_params": "dc=12"},
                {"ref": "V2", "lib_id": "Simulation_SPICE:VPULSE", "sim_params": "y1=0 y2=10 td=0 tr=1n tf=1n tw=50u per=100u"},
                {"ref": "R1", "lib_id": "Device:R", "value": "100", "role": "RG"},
                {"ref": "C1", "lib_id": "Device:C", "value": "10n", "role": "CG"},
                {"ref": "R2", "lib_id": "Device:R", "value": "100", "role": "RL"},
                {"ref": "M1", "lib_id": "Simulation_SPICE:NMOS", "sim_type": "MOS1",
                 "sim_params": "vto=2 kp=0.5 lambda=0 tox=1e-7 cgso=0 cgdo=0 cbd=0 cbs=0 w=100u l=100u"},
            ],
            "nets": {"vdd": ["V1.1", "R2.1"], "gsrc": ["V2.1", "R1.1"], "g": ["R1.2", "C1.1", "M1.2"],
                     "d": ["R2.2", "M1.1"], "GND": ["V1.2", "V2.2", "C1.2", "M1.3"]},
            "directives": [".tran 1n 20u"],
            "note": "NMOS 심볼 기본 Sim.Type=VDMOS를 MOS1로 바꾼다. kicad-cli 넷리스트에서 LEVEL=1 모델이 나오는지 확인한다.",
        },
        "measurements": [
            {"name": "vgs_at_tau", "kind": "FIND", "signal": "v(g)", "at": "1u",
             "theory": vg * (1 - math.exp(-1)), "unit": "V", "tol_rel": 0.02},
            {"name": "t_vth", "kind": "WHEN", "signal": "v(g)", "val": vto, "edge": "RISE=1",
             "theory": t_vth, "unit": "s", "tol_rel": 0.02},
            {"name": "vds_on", "kind": "FIND", "signal": "v(d)", "at": "15u",
             "theory": vds_on, "unit": "V", "tol_rel": 0.02},
            {"name": "id_on_derived", "kind": "DERIVED", "formula": "(12 - vds_on)/100",
             "theory": id_on, "unit": "A", "tol_rel": 0.02},
        ],
        "theory_notes": {"tau_gate_s": tau, "vds_on_V": vds_on, "id_on_A": id_on},
    }


def circuit_03_opamp_noninv():
    gain, pole, rout, voff = 20e3, 20.0, 10.0, 0.0
    r1, r2 = 1e3, 9e3
    vin_pk, f_in = 0.1, 1e3
    # kicad_builtin_opamp 내부: G=100u, R1=GAIN/100u, C1=1/(6.28*R1*POLE)
    r_int = gain / 100e-6
    c_int = 1 / (6.28 * r_int * pole)
    fp = 1 / (2 * math.pi * r_int * c_int)
    rload = r1 + r2
    a0 = gain * rload / (rload + rout)  # Rout와 피드백 네트워크 분압
    beta = r1 / (r1 + r2)
    gcl0 = a0 / (1 + beta * a0)
    fcl = fp * (1 + beta * a0)
    mag_1k = gcl0 / math.sqrt(1 + (f_in / fcl) ** 2)
    return {
        "id": "03-opamp-noninv",
        "title": "OP AMP 비반전 증폭기 (KiCad 내장 단극 모델)",
        "purpose": "서브서킷 모델 호환성과 AC/TRAN 해석. 이득 10, 폐루프 대역폭 fp*(1+A*beta)",
        "analysis": {"type": "tran", "tstep": "1u", "tstop": "3m", "ac": "dec 100 1 10meg"},
        "netlist_body": [
            "* 03 non-inverting op amp, KiCad built-in single-pole model",
            "VCC vcc 0 DC 15",
            "VEE vee 0 DC -15",
            "VIN in 0 DC 0 SIN(0 0.1 1k) AC 1",
            "X1 in inn vcc vee out kicad_builtin_opamp POLE=20 GAIN=20k VOFF=0 ROUT=10",
            "R1 inn 0 1k",
            "R2 out inn 9k",
            ".subckt kicad_builtin_opamp in+ in- vcc vee out params: POLE=20 GAIN=20k VOFF=10m ROUT=10",
            "  Voff in+ inoff dc {VOFF}",
            "  G10 0 int inoff in- 100u",
            "  R1 int 0 {GAIN/100u}",
            "  C1 int 0 {1/(6.28*(GAIN/100u)*POLE)}",
            "  Eout 2 0 int 0 1",
            "  Rout 2 out {ROUT}",
            "  Elow lee 0 vee 0 1",
            "  Ehigh lcc 0 vcc 0 1",
            "  Dlow lee int Dlimit",
            "  Dhigh int lcc Dlimit",
            "  .model Dlimit D N=0.01",
            ".ends",
        ],
        "kicad": {
            "components": [
                {"ref": "V1", "lib_id": "Simulation_SPICE:VDC", "sim_params": "dc=15", "role": "VCC"},
                {"ref": "V2", "lib_id": "Simulation_SPICE:VDC", "sim_params": "dc=15", "role": "VEE (+핀을 GND, -핀을 vee에 연결해 -15V)"},
                {"ref": "V3", "lib_id": "Simulation_SPICE:VSIN", "sim_params": "dc=0 ampl=0.1 f=1k ac=1"},
                {"ref": "U1", "lib_id": "Simulation_SPICE:OPAMP", "sim_params": "POLE=20 GAIN=20k VOFF=0 ROUT=10"},
                {"ref": "R1", "lib_id": "Device:R", "value": "1k"},
                {"ref": "R2", "lib_id": "Device:R", "value": "9k"},
            ],
            "nets": {"in": ["V3.1", "U1.1"], "inn": ["U1.2", "R1.1", "R2.2"], "out": ["U1.5", "R2.1"],
                     "vcc": ["V1.1", "U1.3"], "vee": ["V2.2", "U1.4"],
                     "GND": ["V1.2", "V2.1", "V3.2", "R1.2"]},
            "directives": [".tran 1u 3m", ".ac dec 100 1 10meg"],
            "note": "OPAMP 심볼은 Sim.Library=${KICAD9_SYMBOL_DIR}/Simulation_SPICE.sp, Sim.Name=kicad_builtin_opamp 기본값을 그대로 쓴다. kicad-cli 넷리스트에 .include 경로가 절대경로로 풀리는지 확인한다.",
        },
        "measurements": [
            {"name": "vout_pk_1k", "kind": "MAX", "signal": "v(out)", "from": "2m", "to": "3m",
             "theory": vin_pk * mag_1k, "unit": "V", "tol_rel": 0.02},
            {"name": "gain_db_10hz", "kind": "AC_FIND_DB", "signal": "vdb(out)", "at": "10",
             "theory": 20 * math.log10(gcl0), "unit": "dB", "tol_abs": 0.17,
             "note": "0.17 dB는 선형 2%에 해당. AC 해석을 지원하는 경로(ngspice CLI, KiCad)에서만"},
            {"name": "f_3db", "kind": "AC_WHEN_DB", "signal": "vdb(out)",
             "val": 20 * math.log10(gcl0) - 3, "edge": "FALL=1",
             "theory": fcl, "unit": "Hz", "tol_rel": 0.02,
             "note": "AC 해석을 지원하는 경로에서만"},
        ],
        "theory_notes": {"fp_Hz": fp, "a0_eff": a0, "gcl0": gcl0, "fcl_Hz": fcl, "mag_1k": mag_1k},
    }


def circuit_04_diode_rectifier():
    is_, n, rl, vpk = 1e-14, 1.0, 1e3, 10.0
    # 피크에서 I = (Vpk - Vf)/RL, Vf = n*Vt*ln(I/Is + 1) 반복
    vf = 0.7
    for _ in range(100):
        i = (vpk - vf) / rl
        vf_new = n * V_T * math.log(i / is_ + 1)
        if abs(vf_new - vf) < 1e-12:
            vf = vf_new
            break
        vf = vf_new
    vout_pk = vpk - vf
    return {
        "id": "04-diode-rectifier",
        "title": "다이오드 반파 정류 (Shockley 모델)",
        "purpose": "비선형 소자 모델 일치. 피크 출력 = Vpk - Vf, Vf는 지수식 해",
        "analysis": {"type": "tran", "tstep": "1u", "tstop": "2m"},
        "netlist_body": [
            "* 04 half-wave rectifier",
            "V1 in 0 SIN(0 10 1k)",
            "D1 in out DVAL",
            "RL out 0 1k",
            ".model DVAL D(IS=1e-14 N=1 RS=0 CJO=0)",
        ],
        "kicad": {
            "components": [
                {"ref": "V1", "lib_id": "Simulation_SPICE:VSIN", "sim_params": "dc=0 ampl=10 f=1k"},
                {"ref": "D1", "lib_id": "Simulation_SPICE:D", "sim_params": "is=1e-14 n=1 rs=0 cjo=0"},
                {"ref": "R1", "lib_id": "Device:R", "value": "1k"},
            ],
            "nets": {"in": ["V1.1", "D1.2"], "out": ["D1.1", "R1.1"], "GND": ["V1.2", "R1.2"]},
            "directives": [".tran 1u 2m"],
            "note": "Simulation_SPICE:D 핀은 1=K 2=A. 기본 Sim.Params(rs=50m cjo=10p)를 덮어쓴다.",
        },
        "measurements": [
            {"name": "vout_pk", "kind": "MAX", "signal": "v(out)", "from": "0", "to": "2m",
             "theory": vout_pk, "unit": "V", "tol_rel": 0.02},
            {"name": "vf_pk_derived", "kind": "DERIVED", "formula": "10 - vout_pk",
             "theory": vf, "unit": "V", "tol_rel": 0.02},
        ],
        "theory_notes": {"V_T": V_T, "vf_V": vf},
    }


def circuit_05_precharge():
    r, c, v = 47.0, 4700e-6, 48.0
    tau = r * c
    t_end = 3.0
    return {
        "id": "05-precharge",
        "title": "프리차지 RC 돌입전류와 저항 순간전력",
        "purpose": "돌입 전류 피크, 저항 피크 전력, 충전 시간, 저항 소산 에너지(=1/2 C V^2)",
        "analysis": {"type": "tran", "tstep": "100u", "tstop": "3"},
        "netlist_body": [
            "* 05 precharge inrush",
            "V1 in 0 PULSE(0 48 0 1u 1u 10 20)",
            "RPRE in bus 47",
            "CBUS bus 0 4700u",
            "B1 p 0 V=i(V1)*i(V1)*47",
            "B2 ia 0 V=-i(V1)",
        ],
        "kicad": {
            "components": [
                {"ref": "V1", "lib_id": "Simulation_SPICE:VPULSE", "sim_params": "y1=0 y2=48 td=0 tr=1u tf=1u tw=10 per=20"},
                {"ref": "R1", "lib_id": "Device:R", "value": "47"},
                {"ref": "C1", "lib_id": "Device:C", "value": "4700u"},
                {"ref": "B1", "lib_id": "Simulation_SPICE:BSOURCE", "sim_params": "type=\"B\" model=\"v=i(V1)*i(V1)*47\""},
                {"ref": "B2", "lib_id": "Simulation_SPICE:BSOURCE", "sim_params": "type=\"B\" model=\"v=-i(V1)\""},
            ],
            "nets": {"in": ["V1.1", "R1.1"], "bus": ["R1.2", "C1.1"], "p": ["B1.1"], "ia": ["B2.1"],
                     "GND": ["V1.2", "C1.2", "B1.2", "B2.2"]},
            "directives": [".tran 100u 3"],
            "note": "B 소스는 측정 보조. KiCad 넷리스트에서 전압원 이름이 V1로 유지되는지 확인한다.",
        },
        "measurements": [
            {"name": "i_pk", "kind": "MAX", "signal": "v(ia)", "from": "0", "to": "3",
             "theory": v / r, "unit": "A", "tol_rel": 0.02},
            {"name": "p_pk", "kind": "MAX", "signal": "v(p)", "from": "0", "to": "3",
             "theory": v * v / r, "unit": "W", "tol_rel": 0.02},
            {"name": "v_bus_at_tau", "kind": "FIND", "signal": "v(bus)", "at": f"{tau:.6g}",
             "theory": v * (1 - math.exp(-1)), "unit": "V", "tol_rel": 0.02},
            {"name": "t_95", "kind": "WHEN", "signal": "v(bus)", "val": 0.95 * v, "edge": "RISE=1",
             "theory": tau * math.log(20), "unit": "s", "tol_rel": 0.02},
            {"name": "e_r", "kind": "INTEG", "signal": "v(p)", "from": "0", "to": "3",
             "theory": 0.5 * c * v * v * (1 - math.exp(-2 * t_end / tau)), "unit": "J", "tol_rel": 0.02},
        ],
        "theory_notes": {"tau_s": tau},
    }


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("spec.json")
    spec = {
        "schema_version": 1,
        "generated_by": "projects/sim-validation-20261022/spec/theory.py",
        "temperature_C": 27,
        "tolerances": {"theory_rel": 0.02, "cross_tool_rel": 0.01},
        "engines": {
            "kicad_gui": "KiCad 10.0.6 AppImage 내장 ngspice 45.2",
            "ngspice_cli": "Debian 13 ngspice 44.2+ds-1 배치(-b)",
            "qucs_s": "Qucs-S 26.1.1 AppImage + 시스템 ngspice 44.2",
            "ltspice_wine": "LTspice 24.0.12 (Wine 10.0)",
        },
        "circuits": [
            circuit_01_rc_step(),
            circuit_02_mosfet_gate(),
            circuit_03_opamp_noninv(),
            circuit_04_diode_rectifier(),
            circuit_05_precharge(),
        ],
    }
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for c in spec["circuits"]:
        print(f"[{c['id']}] {c['title']}")
        for m in c["measurements"]:
            print(f"    {m['name']:>16s} = {m['theory']:.6g} {m['unit']}")
    print(f"spec written: {out}")


if __name__ == "__main__":
    main()
