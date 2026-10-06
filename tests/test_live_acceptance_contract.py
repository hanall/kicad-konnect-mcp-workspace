import importlib.util
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("live_acceptance", ROOT / "scripts/mcp-live-acceptance.py")
acceptance = importlib.util.module_from_spec(spec)
spec.loader.exec_module(acceptance)


class LiveAcceptanceContractTest(unittest.TestCase):
    def test_all_drc_categories_are_counted(self):
        report = {
            "violations": [{"severity": "warning"}],
            "unconnected_items": [{"severity": "error"}],
            "schematic_parity": [{"severity": "warning"}],
        }
        self.assertEqual(acceptance.summarize_drc_report(report), {
            "error": 1, "warning": 2, "total": 3,
            "categories": {"violations": 1, "unconnected_items": 1, "schematic_parity": 1},
        })

    def test_missing_drc_category_is_not_a_pass(self):
        with self.assertRaises(AssertionError):
            acceptance.summarize_drc_report({"violations": []})

    def test_malformed_drc_category_and_severity_are_rejected(self):
        base = {"violations": [], "unconnected_items": [], "schematic_parity": []}
        for bad in (None, {}, "", [{"severity": None}]):
            with self.subTest(bad=bad), self.assertRaises(AssertionError):
                acceptance.summarize_drc_report({**base, "violations": bad})

    def test_burst_notification_before_response_does_not_timeout(self):
        source = """
import json,sys
for line in sys.stdin:
    request=json.loads(line)
    for i in range(5):
        print(json.dumps({'jsonrpc':'2.0','method':'notifications/tools/list_changed'}))
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':{'confirmed':True}}),flush=True)
"""
        client = acceptance.McpClient(1, command=[sys.executable, "-u", "-c", source])
        try:
            self.assertTrue(client.request("tools/list", {})["result"]["confirmed"])
            self.assertTrue(client.request("tools/list", {})["result"]["confirmed"])
        finally:
            client.close()

    def test_response_is_retained_when_server_exits_after_writing_it(self):
        source = """
import json,sys
r=json.loads(sys.stdin.readline())
print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':{'confirmed':True}}),flush=True)
"""
        client = acceptance.McpClient(1, command=[sys.executable, "-u", "-c", source])
        try:
            self.assertTrue(client.request("tools/list", {})["result"]["confirmed"])
        finally:
            client.close()
