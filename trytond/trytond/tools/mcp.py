# -*- coding: utf-8 -*-
"""MCP translation layer for Tryton.

This module implements a lightweight HTTP service that accepts simplified
"Model Context Protocol" (MCP) requests and forwards them to Tryton using the
existing JSON-RPC or XML-RPC endpoints.  The bridge is designed so external
systems can exchange MCP messages without having to learn the Tryton specific
RPC formats.

The bridge focuses on two authentication schemes that are available on Tryton:

* Session based authentication, where the MCP client performs a login and the
  bridge keeps track of the resulting session identifier.
* HTTP Basic authentication, where the MCP client supplies credentials that are
  forwarded to Tryton on each RPC call.

The bridge is intentionally stateless for Basic authentication and keeps short
term session state for session authentication so that it can issue
``Authorization: Session`` headers when proxying requests to Tryton.

The module also exposes a small HTTP server that can be started from the
``trytond-mcp`` command line entry point.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import gzip
import json
import logging
import secrets
import threading
import time
import urllib.error
import urllib.request
import xmlrpc.client
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional


LOGGER = logging.getLogger(__name__)


class MCPError(Exception):
    """Base exception for MCP bridge errors."""

    def __init__(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST):
        super().__init__(message)
        self.status = status


class TrytonRPCError(MCPError):
    """Raised when Tryton returns an error payload."""


class TrytonTransportError(MCPError):
    """Raised when the HTTP transport could not reach Tryton."""


def _json_dumps(data: Any) -> bytes:
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def _json_loads(data: bytes) -> Any:
    return json.loads(data.decode("utf-8"))


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _session_auth_header(username: str, user_id: int, session_id: str) -> str:
    token = base64.b64encode(
        f"{username}:{user_id}:{session_id}".encode("utf-8")
    ).decode("ascii")
    return f"Session {token}"


class TrytonJSONRPCClient:
    """Minimal JSON-RPC client for Tryton."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def login(
        self,
        database: str,
        username: str,
        password: str,
        *,
        language: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Login against Tryton and return session information."""

        params: Iterable[Any] = [username, {"password": password}]
        if language is not None:
            params = [username, {"password": password}, language]
        result = self.call(database, "common.db.login", list(params))
        if not isinstance(result, (list, tuple)) or len(result) != 2:
            raise TrytonRPCError("Unexpected login response from Tryton")
        user_id, session_id = result
        authorization = _session_auth_header(username, int(user_id), session_id)
        return {
            "user_id": int(user_id),
            "session": session_id,
            "authorization": authorization,
        }

    def logout(self, database: str, authorization: str) -> Any:
        return self.call(
            database,
            "common.db.logout",
            [],
            authorization=authorization,
        )

    def call(
        self,
        database: Optional[str],
        method: str,
        params: Optional[Iterable[Any]] = None,
        *,
        authorization: Optional[str] = None,
        request_id: Optional[int] = None,
    ) -> Any:
        payload = {
            "id": request_id if request_id is not None else int(time.time() * 1000),
            "method": method,
            "params": list(params or []),
        }
        headers = {"Content-Type": "application/json"}
        if authorization:
            headers["Authorization"] = authorization
        path = f"/{database}/" if database else "/"
        response = self._request(path, payload, headers=headers)
        if isinstance(response, MutableMapping):
            if "error" in response:
                raise TrytonRPCError(json.dumps(response["error"]))
            if "result" in response:
                return response["result"]
        return response

    def _request(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        headers: Optional[Mapping[str, str]] = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        data = _json_dumps(payload)
        request = urllib.request.Request(url, data=data, headers=dict(headers or {}))
        try:
            with contextlib.closing(
                self._opener.open(request, timeout=self.timeout)
            ) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return _json_loads(raw)
        except urllib.error.HTTPError as exc:
            message = exc.read()
            try:
                parsed = _json_loads(message)
            except Exception:
                parsed = message.decode("utf-8", "replace")
            raise TrytonTransportError(
                f"Tryton returned HTTP {exc.code}: {parsed}",
                status=HTTPStatus(exc.code),
            ) from exc
        except urllib.error.URLError as exc:
            raise TrytonTransportError(str(exc), status=HTTPStatus.BAD_GATEWAY) from exc


class _XMLRPCAuthorizationTransport(xmlrpc.client.Transport):
    """XML-RPC transport that injects custom HTTP headers."""

    def __init__(self, headers: Mapping[str, str], timeout: float, use_https: bool):
        super().__init__()
        self._headers = dict(headers)
        self._timeout = timeout
        self._use_https = use_https

    # ``Transport`` in the stdlib uses ``make_connection`` to create the HTTP
    # connection object.  ``SafeTransport`` overrides this for HTTPS connections,
    # so we need to replicate the logic depending on the scheme.
    def make_connection(self, host: str):  # pragma: no cover - exercised indirectly
        if self._use_https:
            conn = xmlrpc.client.SafeTransport.make_connection(self, host)
        else:
            conn = super().make_connection(host)
        if self._timeout:
            conn.timeout = self._timeout
        return conn

    def send_headers(self, connection, headers):  # pragma: no cover - thin wrapper
        super().send_headers(connection, headers)
        for key, value in self._headers.items():
            connection.putheader(key, value)


class TrytonXMLRPCClient:
    """Minimal XML-RPC client for Tryton."""

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def call(
        self,
        database: Optional[str],
        method: str,
        params: Optional[Iterable[Any]] = None,
        *,
        authorization: Optional[str] = None,
    ) -> Any:
        headers = {}
        if authorization:
            headers["Authorization"] = authorization
        use_https = self.base_url.startswith("https://")
        transport = _XMLRPCAuthorizationTransport(headers, self.timeout, use_https)
        path = f"{self.base_url}{'/' if database else ''}{database or ''}/"
        proxy = xmlrpc.client.ServerProxy(
            path,
            allow_none=True,
            transport=transport,
        )
        target = proxy
        for segment in method.split('.'):
            target = getattr(target, segment)
        return target(*list(params or []))


@dataclass
class SessionState:
    token: str
    database: str
    username: str
    user_id: Optional[int]
    session: Optional[str]
    authorization: str
    protocol: str
    auth_mode: str
    created_at: float
    ttl: float

    def is_expired(self) -> bool:
        return time.monotonic() > self.created_at + self.ttl


class MCPBridge:
    """Bridge MCP requests to Tryton RPC services."""

    def __init__(
        self,
        tryton_url: str,
        *,
        timeout: float = 30.0,
        token_ttl: float = 3600.0,
        json_client: Optional[TrytonJSONRPCClient] = None,
        xml_client_factory: Optional[callable] = None,
    ):
        self.tryton_url = tryton_url.rstrip("/")
        self.timeout = timeout
        self.token_ttl = token_ttl
        self._json_client = json_client or TrytonJSONRPCClient(self.tryton_url, timeout)
        self._xml_client_factory = (
            xml_client_factory
            if xml_client_factory is not None
            else lambda: TrytonXMLRPCClient(self.tryton_url, timeout)
        )
        self._sessions: Dict[str, SessionState] = {}
        self._lock = threading.RLock()

    # ------------------------------------------------------------------ helpers
    def _store_session(self, state: SessionState) -> SessionState:
        with self._lock:
            self._sessions[state.token] = state
        return state

    def _get_session(self, token: str) -> SessionState:
        with self._lock:
            state = self._sessions.get(token)
            if not state:
                raise MCPError("Unknown session token", HTTPStatus.UNAUTHORIZED)
            if state.is_expired():
                del self._sessions[token]
                raise MCPError("Session token expired", HTTPStatus.UNAUTHORIZED)
            return state

    def _purge_sessions(self) -> None:
        with self._lock:
            expired = [token for token, state in self._sessions.items() if state.is_expired()]
            for token in expired:
                LOGGER.debug("Expiring MCP session token %s", token)
                del self._sessions[token]

    # ---------------------------------------------------------------- operations
    def login(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        protocol = payload.get("protocol", "jsonrpc")
        auth_mode = payload.get("auth", "session")
        database = payload.get("database")
        username = payload.get("username")
        password = payload.get("password")
        language = payload.get("language")
        if not database:
            raise MCPError("Missing database name for login")
        if not username:
            raise MCPError("Missing username for login")
        if not password:
            raise MCPError("Missing password for login")

        self._purge_sessions()

        if protocol not in {"jsonrpc", "xmlrpc"}:
            raise MCPError(f"Unsupported protocol '{protocol}'")
        if auth_mode not in {"session", "basic"}:
            raise MCPError(f"Unsupported authentication mode '{auth_mode}'")

        token = secrets.token_urlsafe(32)

        if auth_mode == "session":
            login_info = self._json_client.login(
                database,
                username,
                password,
                language=language,
            )
            state = SessionState(
                token=token,
                database=database,
                username=username,
                user_id=login_info["user_id"],
                session=login_info["session"],
                authorization=login_info["authorization"],
                protocol=protocol,
                auth_mode=auth_mode,
                created_at=time.monotonic(),
                ttl=self.token_ttl,
            )
            self._store_session(state)
            return {
                "token": token,
                "user_id": login_info["user_id"],
                "session": login_info["session"],
                "authorization": login_info["authorization"],
                "expires_in": self.token_ttl,
            }

        # Basic authentication is stateless so we simply remember the header so
        # that subsequent MCP calls do not need to re-compute it.
        authorization = _basic_auth_header(username, password)
        state = SessionState(
            token=token,
            database=database,
            username=username,
            user_id=None,
            session=None,
            authorization=authorization,
            protocol=protocol,
            auth_mode=auth_mode,
            created_at=time.monotonic(),
            ttl=self.token_ttl,
        )
        self._store_session(state)
        return {
            "token": token,
            "authorization": authorization,
            "expires_in": self.token_ttl,
        }

    def logout(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        token = payload.get("token")
        if not token:
            raise MCPError("Missing session token for logout")
        state = self._get_session(token)
        if state.auth_mode == "session":
            self._json_client.logout(state.database, state.authorization)
        with self._lock:
            self._sessions.pop(token, None)
        return {"status": "ok"}

    def call(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        protocol = payload.get("protocol", "jsonrpc")
        auth_mode = payload.get("auth", "session")
        method = payload.get("method")
        params = payload.get("params", [])
        database = payload.get("database")
        token = payload.get("token")
        request_id = payload.get("id")

        if not method:
            raise MCPError("Missing RPC method")
        if protocol not in {"jsonrpc", "xmlrpc"}:
            raise MCPError(f"Unsupported protocol '{protocol}'")
        if auth_mode not in {"session", "basic"}:
            raise MCPError(f"Unsupported authentication mode '{auth_mode}'")

        authorization: Optional[str] = None
        target_database: Optional[str] = database
        if auth_mode in {"session", "basic"}:
            if not token:
                raise MCPError("Missing session token", HTTPStatus.UNAUTHORIZED)
            state = self._get_session(token)
            authorization = state.authorization
            if not target_database:
                target_database = state.database
            if protocol != state.protocol:
                raise MCPError(
                    "Protocol mismatch for session token",
                    HTTPStatus.BAD_REQUEST,
                )

        if protocol == "jsonrpc":
            result = self._json_client.call(
                target_database,
                method,
                params,
                authorization=authorization,
                request_id=request_id,
            )
        else:
            client = self._xml_client_factory()
            result = client.call(
                target_database,
                method,
                params,
                authorization=authorization,
            )
        return {"result": result}


class MCPHTTPRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def __init__(self, bridge: MCPBridge, *args, **kwargs):
        self.bridge = bridge
        super().__init__(*args, **kwargs)

    # ---------------------------------------------------------------- utilities
    def _read_json_body(self) -> Mapping[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            raise MCPError("Invalid JSON body") from exc

    def _send_response(self, status: HTTPStatus, payload: Mapping[str, Any]):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, handler):
        try:
            payload = self._read_json_body()
            response = handler(payload)
            self._send_response(HTTPStatus.OK, response)
        except MCPError as exc:
            LOGGER.debug("MCP error: %s", exc, exc_info=True)
            self._send_response(exc.status, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.exception("Unhandled MCP error")
            self._send_response(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": str(exc)},
            )

    # ---------------------------------------------------------------- handlers
    def do_POST(self):
        if self.path == "/mcp/login":
            self._handle(self.bridge.login)
        elif self.path == "/mcp/logout":
            self._handle(self.bridge.logout)
        elif self.path == "/mcp/call":
            self._handle(self.bridge.call)
        else:  # pragma: no cover - defensive
            self._send_response(HTTPStatus.NOT_FOUND, {"error": "Unknown path"})

    def do_GET(self):  # pragma: no cover - basic health endpoint
        if self.path == "/health":
            self._send_response(HTTPStatus.OK, {"status": "ok"})
        else:
            self._send_response(HTTPStatus.NOT_FOUND, {"error": "Unknown path"})

    # Silence the default logging so that we rely on ``logging`` instead.
    def log_message(self, format, *args):  # pragma: no cover - delegate to logging
        LOGGER.info("%s - %s", self.address_string(), format % args)


def run_server(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Tryton MCP bridge server")
    parser.add_argument("tryton_url", help="Base URL of the Tryton server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the MCP server")
    parser.add_argument("--port", type=int, default=8650, help="Port to bind the MCP server")
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="Timeout in seconds for requests sent to Tryton",
    )
    parser.add_argument(
        "--token-ttl",
        type=float,
        default=3600.0,
        help="Lifetime of MCP session tokens in seconds",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING, ERROR)",
    )

    args = parser.parse_args(list(argv) if argv is not None else None)

    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    bridge = MCPBridge(
        args.tryton_url,
        timeout=args.timeout,
        token_ttl=args.token_ttl,
    )

    def handler(*handler_args, **handler_kwargs):
        return MCPHTTPRequestHandler(bridge, *handler_args, **handler_kwargs)

    server = ThreadingHTTPServer((args.host, args.port), handler)
    LOGGER.info("Starting MCP bridge on %s:%s", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - manual shutdown
        LOGGER.info("Stopping MCP bridge")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(run_server())

