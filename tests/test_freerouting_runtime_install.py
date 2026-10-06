#!/usr/bin/env python3
"""Freerouting 격리 runtime installer의 공급망·경로 실패 폐쇄 테스트."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/install-freerouting-runtime.py"
LOCK = ROOT / "config/freerouting.lock.json"


def load_subject():
    spec = importlib.util.spec_from_file_location("install_freerouting_runtime", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"installer를 불러올 수 없습니다: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FreeroutingRuntimeInstallTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.subject = load_subject()

    def test_lock_pins_approved_official_assets_and_names_digest_limit(self) -> None:
        lock = self.subject.load_lock(LOCK)
        self.assertEqual(lock["freerouting"]["version"], "2.5.0")
        self.assertEqual(
            lock["freerouting"]["sha256"],
            "f6f51bb02245e8e717f9359bd260cc9c5c0b1bc0acc8b7cb2cd5b8ffeb5de3c7",
        )
        self.assertEqual(lock["freerouting"]["size"], 64599107)
        self.assertEqual(lock["jre"]["package"], "openjdk-25-jre-headless")
        self.assertEqual(lock["jre"]["version"], "25.0.4.1+1-1~deb13u1")
        self.assertFalse(lock["freerouting"]["digest_is_signature"])
        self.assertIn("최신 예외 승인함", lock["approval"]["user_authorization"])

    def test_target_must_stay_below_project_artifacts_and_reject_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            root = Path(directory)
            (root / ".artifacts").mkdir()
            allowed = root / ".artifacts/services/freerouting-runtime"
            self.assertEqual(self.subject.validate_target(root, allowed), allowed.resolve())
            with self.assertRaises(self.subject.InstallerError):
                self.subject.validate_target(root, Path(outside) / "runtime")

            escape = root / ".artifacts/escape"
            escape.symlink_to(outside, target_is_directory=True)
            with self.assertRaises(self.subject.InstallerError):
                self.subject.validate_target(root, escape / "runtime")

    def test_blob_verification_rejects_size_and_hash_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.bin"
            path.write_bytes(b"trusted")
            spec = {
                "size": 7,
                "sha256": hashlib.sha256(b"trusted").hexdigest(),
            }
            self.subject.verify_blob(path, spec, "fixture")
            path.write_bytes(b"tampered")
            with self.assertRaises(self.subject.InstallerError):
                self.subject.verify_blob(path, spec, "fixture")
            path.write_bytes(b"trusted!")
            with self.assertRaises(self.subject.InstallerError):
                self.subject.verify_blob(path, spec, "fixture")

    def test_install_manifest_must_match_the_exact_lock_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "INSTALL-MANIFEST.json"
            path.write_text(json.dumps({"lock_sha256": "wrong"}), encoding="utf-8")
            with self.assertRaises(self.subject.InstallerError):
                self.subject.verify_install_manifest(path, "a" * 64)
            path.write_text(json.dumps({"lock_sha256": "a" * 64}), encoding="utf-8")
            self.subject.verify_install_manifest(path, "a" * 64)

    def test_download_urls_are_https_and_no_system_install_command_is_used(self) -> None:
        lock = self.subject.load_lock(LOCK)
        self.assertTrue(lock["freerouting"]["url"].startswith("https://"))
        self.assertTrue(lock["jre"]["url"].startswith("https://"))
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("apt install", source)
        self.assertNotIn("update-alternatives", source)
        self.assertNotIn("sudo", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
