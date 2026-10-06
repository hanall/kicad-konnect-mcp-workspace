#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
VERIFIER = ROOT / "scripts/verify-kicad-libraries.py"
INSTALLER = ROOT / "scripts/install-kicad-appimage.sh"
KICAD_10_0_6_LIBRARY_MANIFEST_SHA256 = (
    "89fa035615628d35b71276799e3318b85a889581a5c64b57c2937ad95c9cde23"
)


class KiCadLibraryIntegrityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="kicad-library-integrity-")
        self.addCleanup(self.temp_dir.cleanup)
        self.temp = Path(self.temp_dir.name)
        self.library_root = self.temp / "share/kicad"
        for name in ("symbols", "footprints", "3dmodels"):
            (self.library_root / name).mkdir(parents=True)
        (self.library_root / "symbols/Device.kicad_sym").write_text(
            "(kicad_symbol_lib (version 20231120))\n", encoding="utf-8"
        )
        (self.library_root / "footprints/Resistor.pretty").mkdir()
        (self.library_root / "footprints/Resistor.pretty/R_0402.kicad_mod").write_text(
            "(footprint \"R_0402\")\n", encoding="utf-8"
        )
        (self.library_root / "3dmodels/Resistor.3dshapes").mkdir()
        (self.library_root / "3dmodels/Resistor.3dshapes/R_0402.step").write_bytes(
            b"ISO-10303-21;\nEND-ISO-10303-21;\n"
        )
        self.manifest = self.temp / "KICAD-LIBRARIES.json"

    def run_verifier(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VERIFIER), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def create_manifest(self) -> str:
        result = self.run_verifier(
            "create",
            "--root",
            str(self.library_root),
            "--output",
            str(self.manifest),
            "--version",
            "10.0.6",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return hashlib.sha256(self.manifest.read_bytes()).hexdigest()

    def test_create_then_verify_accepts_the_exact_tree(self) -> None:
        manifest_sha256 = self.create_manifest()

        result = self.run_verifier(
            "verify",
            "--root",
            str(self.library_root),
            "--manifest",
            str(self.manifest),
            "--manifest-sha256",
            manifest_sha256,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("files=3", result.stdout)
        self.assertIn("KiCad 라이브러리 무결성 검증 통과", result.stdout)

    def test_verify_reports_missing_changed_and_extra_paths(self) -> None:
        manifest_sha256 = self.create_manifest()
        (self.library_root / "symbols/Device.kicad_sym").unlink()
        (self.library_root / "footprints/Resistor.pretty/R_0402.kicad_mod").write_text(
            "tampered\n", encoding="utf-8"
        )
        (self.library_root / "symbols/Injected.kicad_sym").write_text(
            "unexpected\n", encoding="utf-8"
        )

        result = self.run_verifier(
            "verify",
            "--root",
            str(self.library_root),
            "--manifest",
            str(self.manifest),
            "--manifest-sha256",
            manifest_sha256,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("missing: symbols/Device.kicad_sym", result.stderr)
        self.assertIn(
            "changed: footprints/Resistor.pretty/R_0402.kicad_mod", result.stderr
        )
        self.assertIn("extra: symbols/Injected.kicad_sym", result.stderr)

    def test_changed_tree_and_rebuilt_manifest_cannot_bypass_the_anchor(self) -> None:
        trusted_manifest_sha256 = self.create_manifest()
        symbol = self.library_root / "symbols/Device.kicad_sym"
        symbol.write_text("tampered together with manifest\n", encoding="utf-8")

        rebuilt = self.run_verifier(
            "create",
            "--root",
            str(self.library_root),
            "--output",
            str(self.manifest),
            "--version",
            "10.0.6",
        )
        self.assertEqual(rebuilt.returncode, 0, rebuilt.stdout + rebuilt.stderr)
        rebuilt_manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(rebuilt_manifest["version"], "10.0.6")
        self.assertNotEqual(
            hashlib.sha256(self.manifest.read_bytes()).hexdigest(),
            trusted_manifest_sha256,
        )

        result = self.run_verifier(
            "verify",
            "--root",
            str(self.library_root),
            "--manifest",
            str(self.manifest),
            "--manifest-sha256",
            trusted_manifest_sha256,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("manifest SHA-256 불일치", result.stderr)

    def test_internal_symlink_is_bound_and_escape_is_rejected(self) -> None:
        link = self.library_root / "symbols/DeviceAlias.kicad_sym"
        link.symlink_to("Device.kicad_sym")
        manifest_sha256 = self.create_manifest()

        exact = self.run_verifier(
            "verify",
            "--root",
            str(self.library_root),
            "--manifest",
            str(self.manifest),
            "--manifest-sha256",
            manifest_sha256,
        )
        self.assertEqual(exact.returncode, 0, exact.stdout + exact.stderr)

        outside = self.temp / "outside.kicad_sym"
        outside.write_text("outside\n", encoding="utf-8")
        link.unlink()
        link.symlink_to(outside)
        escaped = self.run_verifier(
            "verify",
            "--root",
            str(self.library_root),
            "--manifest",
            str(self.manifest),
            "--manifest-sha256",
            manifest_sha256,
        )

        self.assertNotEqual(escaped.returncode, 0, escaped.stdout + escaped.stderr)
        self.assertIn("symlink 경로 이탈", escaped.stderr)

    def test_manifest_entries_are_canonical_and_path_sorted(self) -> None:
        self.create_manifest()
        raw = self.manifest.read_bytes()
        payload = json.loads(raw)
        paths = [entry["path"] for entry in payload["entries"]]

        self.assertEqual(paths, sorted(paths))
        self.assertEqual(len(paths), len(set(paths)))
        canonical = (
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        self.assertEqual(raw, canonical)

    def test_installer_pins_and_enforces_the_signed_image_library_manifest(self) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertIn(
            f'LIBRARY_MANIFEST_SHA256="{KICAD_10_0_6_LIBRARY_MANIFEST_SHA256}"',
            installer,
        )
        self.assertIn(
            'LIBRARY_MANIFEST="${INSTALL_DIR}/KICAD-LIBRARIES.json"', installer
        )
        self.assertIn('scripts/verify-kicad-libraries.py" verify', installer)
        self.assertIn('--manifest-sha256 "$LIBRARY_MANIFEST_SHA256"', installer)
        self.assertIn('scripts/verify-kicad-libraries.py" create', installer)
        self.assertIn(
            'verify_file "$LIBRARY_MANIFEST_SHA256" "$library_manifest_stage"',
            installer,
        )
        self.assertIn('sudo mv "$library_new" "$library_root"', installer)
        self.assertNotIn('LIBRARY_MANIFEST_SHA256="$(sha256sum', installer)

    def test_verify_refuses_noncanonical_manifest_with_matching_hash(self) -> None:
        self.create_manifest()
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        payload["entries"][0], payload["entries"][1] = (
            payload["entries"][1],
            payload["entries"][0],
        )
        self.manifest.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        modified_sha256 = hashlib.sha256(self.manifest.read_bytes()).hexdigest()

        result = self.run_verifier(
            "verify",
            "--root",
            str(self.library_root),
            "--manifest",
            str(self.manifest),
            "--manifest-sha256",
            modified_sha256,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("manifest entries가 path 순서가 아닙니다", result.stderr)

    def test_verify_reports_extra_path_at_library_root(self) -> None:
        manifest_sha256 = self.create_manifest()
        (self.library_root / "unexpected-root-file").write_text(
            "unexpected\n", encoding="utf-8"
        )

        result = self.run_verifier(
            "verify",
            "--root",
            str(self.library_root),
            "--manifest",
            str(self.manifest),
            "--manifest-sha256",
            manifest_sha256,
        )

        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("extra: unexpected-root-file", result.stderr)

    def test_installer_verifies_new_root_owned_tree_before_swap(self) -> None:
        installer = INSTALLER.read_text(encoding="utf-8")

        self.assertIn('sudo chown -hR root:root "$library_new"', installer)
        self.assertIn('--root "$library_new"', installer)
        verify_new_index = installer.index('--root "$library_new"')
        swap_index = installer.index('sudo mv "$library_new" "$library_root"')
        self.assertLess(verify_new_index, swap_index)
        self.assertIn('sudo rm -rf -- "$library_old"', installer)


if __name__ == "__main__":
    unittest.main()
