"""회로 시뮬레이터 설치·검증 계약 회귀.

- 사양 spec.json이 theory.py 재실행 결과와 일치하는지(이론값 변조 방지)
- 잠금 파일(config/qucs-s.lock.json, config/ltspice.lock.json)의 필수 필드와 SHA256 형식
- 설치된 환경에서는 설치 스크립트 --verify-only와 ngspice 회귀가 통과하는지(미설치면 skip)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = ROOT / "projects/sim-validation-20261022/spec"
SPEC = SPEC_DIR / "spec.json"
THEORY = SPEC_DIR / "theory.py"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
CIRCUIT_IDS = ["01-rc-step", "02-mosfet-gate", "03-opamp-noninv", "04-diode-rectifier", "05-precharge"]


class SpecContractTests(unittest.TestCase):
    def test_spec_matches_theory_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "spec.json"
            subprocess.run([sys.executable, "-I", str(THEORY), str(out)], check=True,
                           capture_output=True, text=True)
            regenerated = json.loads(out.read_text(encoding="utf-8"))
        committed = json.loads(SPEC.read_text(encoding="utf-8"))
        self.assertEqual(regenerated, committed)

    def test_spec_shape(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        self.assertEqual([c["id"] for c in spec["circuits"]], CIRCUIT_IDS)
        self.assertEqual(spec["tolerances"], {"theory_rel": 0.02, "cross_tool_rel": 0.01})
        for circuit in spec["circuits"]:
            self.assertTrue(circuit["netlist_body"])
            self.assertTrue(circuit["measurements"])
            for m in circuit["measurements"]:
                self.assertIn("theory", m)
                self.assertTrue(("tol_rel" in m) or ("tol_abs" in m), m["name"])
                self.assertNotEqual(m["theory"], 0.0)


class LockFileTests(unittest.TestCase):
    def test_qucs_lock(self):
        lock = json.loads((ROOT / "config/qucs-s.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["version"], "26.1.1")
        appimage = lock["assets"]["Qucs-S-26.1.1-linux-x86_64.AppImage"]
        self.assertRegex(appimage["sha256"], SHA256)
        self.assertFalse(lock["engine"]["ngspice"]["bundled"])
        self.assertEqual(lock["approval"]["status"], "approved")
        self.assertEqual(lock["age_gate"]["status"], "pass")

    def test_ltspice_lock(self):
        lock = json.loads((ROOT / "config/ltspice.lock.json").read_text(encoding="utf-8"))
        self.assertEqual(lock["version"], "24.0.12.0")
        self.assertRegex(lock["assets"]["LTspice64.msi"]["sha256"], SHA256)
        self.assertEqual(lock["runtime"]["layer"], "Wine")
        self.assertEqual(lock["approval"]["status"], "approved")
        self.assertIn("exception", lock["approval"])

    def test_install_scripts_pin_same_hashes_as_locks(self):
        qucs = json.loads((ROOT / "config/qucs-s.lock.json").read_text(encoding="utf-8"))
        script = (ROOT / "scripts/install-qucs-s-appimage.sh").read_text(encoding="utf-8")
        self.assertIn(qucs["assets"]["Qucs-S-26.1.1-linux-x86_64.AppImage"]["sha256"], script)
        self.assertIn(qucs["assets"]["hashes.sha256"]["sha256"], script)
        lt = json.loads((ROOT / "config/ltspice.lock.json").read_text(encoding="utf-8"))
        script = (ROOT / "scripts/install-ltspice-wine.sh").read_text(encoding="utf-8")
        self.assertIn(lt["assets"]["LTspice64.msi"]["sha256"], script)


@unittest.skipUnless(shutil.which("ngspice"), "ngspice 미설치")
class NgspiceRegressionTests(unittest.TestCase):
    def test_all_circuits_match_theory(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = Path(tmp) / "result.json"
            proc = subprocess.run(
                [sys.executable, "-I", str(ROOT / "scripts/sim-validation-run.py"),
                 "--out", tmp, "--json", str(result)],
                capture_output=True, text=True, timeout=900,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            report = json.loads(result.read_text(encoding="utf-8"))
        self.assertTrue(report["all_pass"])
        self.assertEqual([c["id"] for c in report["circuits"]], CIRCUIT_IDS)


@unittest.skipUnless(Path("/opt/qucs-s/26.1.1/INSTALL-MANIFEST.json").exists(), "Qucs-S 미설치")
class QucsRuntimeTests(unittest.TestCase):
    def test_verify_only(self):
        proc = subprocess.run([str(ROOT / "scripts/install-qucs-s-appimage.sh"), "--verify-only"],
                              capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


@unittest.skipUnless(
    shutil.which("wine") and (Path.home() / ".local/share/wineprefixes/ltspice/INSTALL-MANIFEST.json").exists(),
    "LTspice(Wine) 미설치",
)
class LtspiceRuntimeTests(unittest.TestCase):
    def test_verify_only(self):
        proc = subprocess.run([str(ROOT / "scripts/install-ltspice-wine.sh"), "--verify-only"],
                              capture_output=True, text=True, timeout=300)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
