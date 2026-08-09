#!/usr/bin/env python3
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/manage-upstreams.py"


def load_policy_module():
    spec = importlib.util.spec_from_file_location("manage_upstreams", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError(f"module을 불러올 수 없음: {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UpstreamPolicyTest(unittest.TestCase):
    def test_kicad_policy_selects_latest_stable_release(self) -> None:
        policy = load_policy_module()
        self.assertEqual(
            policy.latest_stable_kicad_tag(
                ["9.0.9", "9.99.0", "10.0.5", "10.99.0", "11.0.0", "nightly"]
            ),
            "11.0.0",
        )

    def test_kicad_policy_rejects_development_only_input(self) -> None:
        policy = load_policy_module()
        with self.assertRaises(ValueError):
            policy.latest_stable_kicad_tag(["10.99.0", "nightly"])

    def test_konnect_policy_selects_latest_semver_tag(self) -> None:
        policy = load_policy_module()
        self.assertEqual(
            policy.latest_konnect_tag(["v0.2.1", "v0.2.2", "preview", "v0.10.0"]),
            "v0.10.0",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
