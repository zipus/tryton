# This file is part of Tryton.  The COPYRIGHT file at the top level of
# this repository contains the full copyright notices and license terms.

import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MODULE_PATH = ROOT / "trytond" / "trytond" / "tools" / "mcp.py"

# ``trytond.trytond`` depends on ``lxml`` which might not be installed in the
# execution environment.  Stub the minimal API that the package expects so that
# we can import the MCP bridge module without pulling optional dependencies.
if "lxml" not in sys.modules:  # pragma: no cover - defensive guard
    etree_stub = types.SimpleNamespace(
        XMLParser=lambda **kwargs: None,
        set_default_parser=lambda parser: None,
    )
    objectify_stub = types.SimpleNamespace(
        makeparser=lambda **kwargs: None,
        set_default_parser=lambda parser: None,
    )
    lxml_stub = types.SimpleNamespace(etree=etree_stub, objectify=objectify_stub)
    sys.modules.setdefault("lxml", lxml_stub)
    sys.modules.setdefault("lxml.etree", etree_stub)
    sys.modules.setdefault("lxml.objectify", objectify_stub)

SPEC = importlib.util.spec_from_file_location("trytond_mcp", MODULE_PATH)
mcp = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules.setdefault(SPEC.name, mcp)
SPEC.loader.exec_module(mcp)  # type: ignore[union-attr]


class FakeJSONClient:
    def __init__(self):
        self.calls = []

    def login(self, database, username, password, *, language=None):
        self.calls.append(
            ("login", database, username, password, language)
        )
        return {
            "user_id": 7,
            "session": "SESSION",
            "authorization": mcp._session_auth_header(username, 7, "SESSION"),
        }

    def logout(self, database, authorization):
        self.calls.append(("logout", database, authorization))
        return {"status": "ok"}

    def call(self, database, method, params=None, *, authorization=None, request_id=None):
        self.calls.append(
            ("call", database, method, list(params or []), authorization, request_id)
        )
        if method == "common.server.version":
            return "7.7"
        return {"ok": True}


class FakeXMLClient:
    def __init__(self):
        self.calls = []

    def call(self, database, method, params=None, *, authorization=None):
        self.calls.append(
            ("call", database, method, list(params or []), authorization)
        )
        return "xml-result"


class MCPBridgeTestCase(unittest.TestCase):
    def setUp(self):
        self.json_client = FakeJSONClient()
        self.xml_client = FakeXMLClient()
        self.bridge = mcp.MCPBridge(
            "http://tryton.local",
            json_client=self.json_client,
            xml_client_factory=lambda: self.xml_client,
            token_ttl=5.0,
        )

    def test_session_login_and_call(self):
        login_response = self.bridge.login(
            {
                "database": "test",
                "username": "user",
                "password": "secret",
                "protocol": "jsonrpc",
            }
        )
        token = login_response["token"]
        call_response = self.bridge.call(
            {
                "token": token,
                "database": "test",
                "protocol": "jsonrpc",
                "method": "model.party.list",
                "params": ["arg"],
            }
        )
        self.assertEqual({"result": {"ok": True}}, call_response)
        _, _, _, _, authorization, _ = self.json_client.calls[-1]
        self.assertTrue(authorization.startswith("Session "))

    def test_basic_login_and_call(self):
        login_response = self.bridge.login(
            {
                "database": "test",
                "username": "user",
                "password": "secret",
                "protocol": "jsonrpc",
                "auth": "basic",
            }
        )
        token = login_response["token"]
        call_response = self.bridge.call(
            {
                "token": token,
                "protocol": "jsonrpc",
                "method": "model.party.get",
                "params": [1],
            }
        )
        self.assertEqual({"result": {"ok": True}}, call_response)
        _, _, _, _, authorization, _ = self.json_client.calls[-1]
        self.assertTrue(authorization.startswith("Basic "))

    def test_logout_clears_session(self):
        login_response = self.bridge.login(
            {
                "database": "test",
                "username": "user",
                "password": "secret",
                "protocol": "jsonrpc",
            }
        )
        token = login_response["token"]
        self.bridge.logout({"token": token})
        with self.assertRaises(mcp.MCPError):
            self.bridge.call(
                {
                    "token": token,
                    "protocol": "jsonrpc",
                    "method": "model.party.get",
                }
            )

    def test_xmlrpc_call(self):
        login_response = self.bridge.login(
            {
                "database": "test",
                "username": "user",
                "password": "secret",
                "protocol": "xmlrpc",
            }
        )
        token = login_response["token"]
        result = self.bridge.call(
            {
                "token": token,
                "protocol": "xmlrpc",
                "method": "system.listMethods",
                "params": [],
            }
        )
        self.assertEqual({"result": "xml-result"}, result)
        _, _, _, _, authorization = self.xml_client.calls[-1]
        self.assertTrue(authorization.startswith("Session "))

def suite():
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(MCPBridgeTestCase))
    return suite


if __name__ == "__main__":
    unittest.main()

