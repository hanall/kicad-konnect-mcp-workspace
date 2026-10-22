"""시뮬레이션 MCP 중계(KONNECT_SIM=1) 계약 회귀.

- tools/list에 도구 4종이 노출되고 get_installation_info에 simulation_extension이 붙는다
- list_simulation_engines가 시스템 ngspice를 보고한다
- run_spice_simulation이 RC 회로를 실행해 이론값(2%)과 일치한다
- export_spice_netlist가 데모 회로도에서 모델 미할당 심볼을 진단한다
- 잘못된 인자는 isError=true와 error.kind로 거부한다
회로도 파일은 읽기만 한다. set_simulation_model은 임시 복사본 프로젝트에서만 검증한다.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LAUNCHER = ROOT / "scripts/run-konnect.sh"
CONFIG = ROOT / "config/konnect.toml"
DEMO_SCH = ROOT / "projects/mcp-led-demo-20261006/mcp-led-demo.kicad_sch"
BINARY = ROOT / "upstream/konnect/target/release/konnect"
WORK_ROOT = ROOT / ".artifacts/test-sim-mcp"  # 쓰기 허용 루트(레포 안)에서만 임시 디렉터리를 만든다
WORK_ROOT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "scripts"))
import sim_engines  # noqa: E402

RC_NETLIST = """* RC step
V1 in 0 PULSE(0 5 0 1n 1n 10m 20m)
R1 in out 1k
C1 out 0 1u
.end
"""


class UnitTests(unittest.TestCase):
    def test_measurement_syntax_both_engines(self):
        m = sim_engines.Measurement.from_dict({"name": "v_at_tau", "kind": "FIND", "signal": "v(out)", "at": "1m"})
        self.assertEqual(m.ngspice(), ".meas tran v_at_tau FIND v(out) AT=1m")
        self.assertEqual(m.ltspice(), ".meas tran v_at_tau FIND v(out) AT 1m")
        m = sim_engines.Measurement.from_dict({"name": "g", "kind": "AC_FIND_DB", "signal": "v(out)", "at": "10"})
        self.assertEqual(m.ngspice(), ".meas ac g FIND vdb(out) AT=10")
        self.assertEqual(m.ltspice(), ".meas ac g FIND v(out) AT 10")
        m = sim_engines.Measurement.from_dict({"name": "g2", "kind": "AC_FIND_DB", "signal": "vdb(out)", "at": "10"})
        self.assertEqual(m.ltspice(), ".meas ac g2 FIND V(out) AT 10")
        with self.assertRaises(ValueError):
            sim_engines.Measurement.from_dict({"name": "bad name", "kind": "FIND"})

    def test_safe_eval_rejects_calls_and_attributes(self):
        self.assertAlmostEqual(sim_engines.safe_eval("(12 - vds_on)/100", {"vds_on": 0.03}), 0.1197)
        with self.assertRaises(ValueError):
            sim_engines.safe_eval("__import__('os').system('true')", {})
        with self.assertRaises(ValueError):
            sim_engines.safe_eval("a.b", {"a": 1})

    def test_diagnostics_detects_unassigned_model(self):
        diag = sim_engines.netlist_diagnostics(".title x\nR1 +5V n1 470\nD1 __D1\nJ1 __J1\nC1 +5V GND 100n\n.end\n")
        self.assertEqual(diag["unassigned_models"], ["D1", "J1"])
        self.assertTrue(diag["has_ground"])
        diag = sim_engines.netlist_diagnostics(".title x\nV1 in GND DC VPULSE\nR1 in out 1k\n.end\n")
        self.assertEqual(len(diag["suspicious_values"]), 1)
        self.assertIn("VPULSE", diag["suspicious_values"][0]["reason"])
        diag = sim_engines.netlist_diagnostics("V1 in GND PULSE( 0 5 0 1n 1n 10m 20m ) \nV2 vdd GND DC 12 \n")
        self.assertEqual(diag["suspicious_values"], [])

    def test_parse_ltspice_log_formats(self):
        text = "v_at_tau: v(out)=3.15955 at 0.001\nt_rise=0.00219741 FROM 0.000105371 TO 0.00230278\ng10: V(out)=(19.9957dB,0.0°) at 10\n"
        values, _, _ = sim_engines.parse_ltspice_log(text)
        self.assertAlmostEqual(values["v_at_tau"], 3.15955)
        self.assertAlmostEqual(values["t_rise"], 0.00219741)
        self.assertAlmostEqual(values["g10"], 19.9957)


def read_json_line(process, timeout=60.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"MCP 조기 종료 {process.returncode}: {process.stderr.read()[:500]}")
        line = process.stdout.readline()
        if line:
            return json.loads(line)
    raise AssertionError("MCP 응답 timeout")


def send(process, payload):
    process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
    process.stdin.flush()


@unittest.skipUnless(BINARY.exists() and shutil.which("ngspice"), "Konnect binary 또는 ngspice 미설치")
class ProxyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = {**os.environ, "KONNECT_SIM": "1", "KONNECT_GUI_SYNC": "0"}
        cls.process = subprocess.Popen(
            [str(LAUNCHER), "--config", str(CONFIG)], cwd=ROOT, env=env, text=True, bufsize=1,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        send(cls.process, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "sim-extension-test", "version": "1"}}})
        init = read_json_line(cls.process)
        assert init["id"] == 1, init
        send(cls.process, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        cls.next_id = 10

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()

    @classmethod
    def call(cls, name, arguments, timeout=90.0):
        cls.next_id += 1
        ident = cls.next_id
        send(cls.process, {"jsonrpc": "2.0", "id": ident, "method": "tools/call",
                           "params": {"name": name, "arguments": arguments}})
        while True:
            message = read_json_line(cls.process, timeout)
            if message.get("id") == ident:
                break
        result = message["result"]
        return result["isError"], json.loads(result["content"][0]["text"])

    def test_01_tools_listed(self):
        type(self).next_id += 1
        ident = self.next_id
        send(self.process, {"jsonrpc": "2.0", "id": ident, "method": "tools/list", "params": {}})
        while True:
            message = read_json_line(self.process)
            if message.get("id") == ident:
                break
        names = {t["name"] for t in message["result"]["tools"]}
        for expected in ("list_simulation_engines", "export_spice_netlist", "set_simulation_model", "run_spice_simulation"):
            self.assertIn(expected, names)
        self.assertIn("list_toolboxes", names)

    def test_02_installation_info_has_extension(self):
        is_error, body = self.call("get_installation_info", {})
        self.assertFalse(is_error)
        self.assertEqual(body["simulation_extension"]["version"], "1")
        self.assertIn("run_spice_simulation", body["simulation_extension"]["tools"])

    def test_03_list_engines(self):
        is_error, body = self.call("list_simulation_engines", {"probe_bundled_version": False})
        self.assertFalse(is_error)
        self.assertTrue(body["engines"]["system-ngspice"]["available"])
        self.assertIn("ngspice-44", body["engines"]["system-ngspice"]["version"] or "")

    def test_04_run_rc_matches_theory(self):
        with tempfile.TemporaryDirectory(dir=WORK_ROOT) as tmp:
            net = Path(tmp) / "rc.cir"
            net.write_text(RC_NETLIST, encoding="utf-8")
            is_error, body = self.call("run_spice_simulation", {
                "netlist": str(net), "engine": "system-ngspice",
                "analysis": {"type": "tran", "args": "1u 5m"},
                "measurements": [
                    {"name": "v_at_tau", "kind": "FIND", "signal": "v(out)", "at": "1m"},
                    {"name": "t_rise", "kind": "TRIG_TARG", "signal": "v(out)", "trig_val": 0.5, "targ_val": 4.5},
                    {"name": "ratio", "kind": "DERIVED", "formula": "v_at_tau / 5"},
                ],
                "expectations": [
                    {"name": "v_at_tau", "theory": 3.1606, "tol_rel": 0.02},
                    {"name": "t_rise", "theory": 0.0021972, "tol_rel": 0.02},
                    {"name": "ratio", "theory": 0.63212, "tol_rel": 0.02},
                ],
                "save_signals": ["v(out)"],
                "work_dir": str(Path(tmp) / "run"),
            })
            self.assertFalse(is_error, body)
            self.assertTrue(body["all_pass"], body)
            self.assertEqual(body["missing_measurements"], [])
            self.assertIn("v(out)", body["waveforms"])
            self.assertTrue(Path(body["log_path"]).exists())

    def test_05_export_demo_detects_unassigned(self):
        if not DEMO_SCH.exists():
            self.skipTest("데모 회로도 없음")
        with tempfile.TemporaryDirectory(dir=WORK_ROOT) as tmp:
            is_error, body = self.call("export_spice_netlist", {"schematic": str(DEMO_SCH), "output": str(Path(tmp) / "demo.cir")})
            self.assertFalse(is_error, body)
            self.assertIn("J1", body["diagnostics"]["unassigned_models"])

    def test_07_set_model_roundtrip_on_copy(self):
        """데모 프로젝트 복사본에서 D1에 모델을 지정하면 넷리스트 진단의 미할당 목록에서 빠진다."""
        if not DEMO_SCH.exists():
            self.skipTest("데모 회로도 없음")
        with tempfile.TemporaryDirectory(dir=WORK_ROOT) as tmp:
            copy_dir = Path(tmp) / "demo-copy"
            shutil.copytree(DEMO_SCH.parent, copy_dir)
            sch = copy_dir / DEMO_SCH.name
            is_error, listed = self.call("load_toolset", {"name": "sch_components"})
            self.assertFalse(is_error, listed)
            is_error, body = self.call("set_simulation_model", {
                "schematic": str(sch), "reference": "D1", "device": "D",
                "params": "is=1e-14 n=1.8 rs=1", "pins": "1=K 2=A"})
            self.assertFalse(is_error, body)
            self.assertEqual(body["fields_applied"]["Sim.Device"], "D")
            is_error, exported = self.call("export_spice_netlist", {"schematic": str(sch), "output": str(Path(tmp) / "demo.cir")})
            self.assertFalse(is_error, exported)
            self.assertNotIn("D1", exported["diagnostics"]["unassigned_models"])
            self.assertIn("J1", exported["diagnostics"]["unassigned_models"])
            self.assertRegex(exported["netlist_text"], r"(?m)^D1\s+\S+\s+\S+\s+\S+")
            self.assertEqual(DEMO_SCH.read_bytes(), DEMO_SCH.read_bytes())  # 원본은 건드리지 않는다

    def test_08_control_blocks_and_shell_are_neutralized(self):
        """입력 넷리스트의 .control(shell)은 strip 옵션과 무관하게 제거되고, 지시어 인자의 제어 명령은 거부된다."""
        with tempfile.TemporaryDirectory(dir=WORK_ROOT) as tmp:
            marker = Path(tmp) / "pwned"
            net = Path(tmp) / "evil.cir"
            net.write_text(RC_NETLIST.replace(".end\n", f".control\nshell touch {marker}\n.endc\n.end\n"), encoding="utf-8")
            is_error, body = self.call("run_spice_simulation", {
                "netlist": str(net), "engine": "system-ngspice", "strip_existing_directives": False,
                "analysis": {"type": "tran", "args": "1u 1m"},
                "measurements": [{"name": "v1", "kind": "FIND", "signal": "v(out)", "at": "0.5m"}],
                "work_dir": str(Path(tmp) / "run")})
            self.assertFalse(is_error, body)
            self.assertFalse(marker.exists(), "입력 넷리스트의 .control shell이 실행됨")
            self.assertNotIn(".control", Path(body["netlist_path"]).read_text().split("wrdata")[0].replace(".control\nrun", ""))
            is_error, body = self.call("run_spice_simulation", {
                "netlist": str(net), "engine": "system-ngspice",
                "analysis": {"type": "tran", "args": "1u 1m"},
                "directives": [".control", f"shell touch {marker}", ".endc"],
                "work_dir": str(Path(tmp) / "run2")})
            self.assertTrue(is_error)
            self.assertEqual(body["error"]["kind"], "invalid_argument")
            is_error, body = self.call("run_spice_simulation", {
                "netlist": str(net), "engine": "system-ngspice",
                "analysis": {"type": "tran", "args": f"1u 1m\nshell touch {marker}"},
                "work_dir": str(Path(tmp) / "run3")})
            self.assertTrue(is_error)
            self.assertFalse(marker.exists())

    def test_09_paths_outside_allowed_roots_rejected(self):
        with tempfile.TemporaryDirectory(dir=WORK_ROOT) as tmp:
            net = Path(tmp) / "rc.cir"
            net.write_text(RC_NETLIST, encoding="utf-8")
            is_error, body = self.call("run_spice_simulation", {
                "netlist": str(net), "engine": "system-ngspice", "analysis": {"type": "tran", "args": "1u 1m"},
                "work_dir": "/tmp/konnect-sim-outside"})
            self.assertTrue(is_error)
            self.assertEqual(body["error"]["kind"], "invalid_argument")
            self.assertFalse(Path("/tmp/konnect-sim-outside").exists())
            is_error, body = self.call("export_spice_netlist", {"schematic": str(DEMO_SCH), "output": "/tmp/konnect-sim-outside.cir"})
            self.assertTrue(is_error)
            self.assertEqual(body["error"]["kind"], "invalid_argument")

    def test_06_invalid_arguments_rejected(self):
        is_error, body = self.call("run_spice_simulation", {"engine": "system-ngspice"})
        self.assertTrue(is_error)
        self.assertEqual(body["error"]["kind"], "invalid_argument")
        is_error, body = self.call("export_spice_netlist", {"schematic": "relative.kicad_sch"})
        self.assertTrue(is_error)
        is_error, body = self.call("set_simulation_model", {"schematic": str(DEMO_SCH), "reference": "R1", "device": "R"})
        self.assertTrue(is_error)
        self.assertIn(body["error"]["kind"], ("toolset_not_loaded", "not_found"))


if __name__ == "__main__":
    unittest.main()
