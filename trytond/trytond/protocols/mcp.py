"""Model Context Protocol integration for Tryton."""

# This file is part of Tryton.  The COPYRIGHT file at the top level of this
# repository contains the full copyright notices and license terms.

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from http import HTTPStatus as NativeHTTPStatus
from typing import Any, Optional

from mcp.server.fastmcp.server import Context, FastMCP

from trytond import backend, security
from trytond.config import config
from trytond.exceptions import (
    ConcurrencyException,
    LoginException,
    TrytonException,
    UserError,
    UserWarning,
)
from trytond.pool import Pool
from trytond.protocols.jsonrpc import JSONEncoder
from trytond.protocols.wrappers import HTTPStatus, Request, Response, abort
from trytond.rpc import RPCReturnException
from trytond.tools import is_instance_method
from trytond.transaction import Transaction, TransactionError
from trytond.worker import run_task
from trytond.wsgi import app

logger = logging.getLogger(__name__)


def _http_status_line(status_code: int) -> str:
    try:
        phrase = NativeHTTPStatus(status_code).phrase
    except ValueError:
        phrase = ""
    if phrase:
        return f"{status_code} {phrase}"
    return str(status_code)


def _jsonable(value: Any) -> Any:
    """Convert *value* into JSON serialisable data."""

    def _default(o: Any) -> Any:
        return JSONEncoder().default(o)  # type: ignore[misc]

    encoded = json.dumps(value, default=_default)
    return json.loads(encoded)


@dataclass
class TrytonRequestState:
    """Data attached to the ASGI scope for Tryton aware tools."""

    database: str
    user_id: int
    context: dict[str, Any]
    request_context: dict[str, Any]
    session: Optional[str] = None
    username: Optional[str] = None


class AsgiToWsgiAdapter:
    """Wrap an ASGI application so it can be used inside the WSGI stack."""

    def __init__(self, app: FastMCP) -> None:
        self.asgi_app = app.streamable_http_app()

    def __call__(self, environ: dict[str, Any], start_response):  # noqa: D401
        """Execute the wrapped ASGI application."""

        scope = self._build_scope(environ)
        body = environ.get("wsgi.input")
        request_body = body.read() if body is not None else b""

        loop = asyncio.new_event_loop()
        disconnect_future = loop.create_future()
        request_sent = False

        response_queue: queue.Queue[Optional[bytes]] = queue.Queue()
        status_holder: dict[str, Any] = {}
        response_started = threading.Event()
        stop_event = threading.Event()
        error_holder: dict[str, BaseException] = {}

        async def receive() -> dict[str, Any]:
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {
                    "type": "http.request",
                    "body": request_body,
                    "more_body": False,
                }
            await disconnect_future
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            message_type = message.get("type")
            if message_type == "http.response.start":
                status_holder["status"] = _http_status_line(message["status"])
                headers = []
                for name, value in message.get("headers", []):
                    headers.append((name.decode("latin1"), value.decode("latin1")))
                status_holder["headers"] = headers
                response_started.set()
            elif message_type == "http.response.body":
                if not response_started.is_set():
                    status_holder.setdefault("status", "200 OK")
                    status_holder.setdefault("headers", [])
                    response_started.set()
                body_bytes = message.get("body", b"")
                if body_bytes:
                    response_queue.put(body_bytes)
                if not message.get("more_body", False):
                    response_queue.put(None)
            else:
                logger.debug("Ignoring ASGI message %s", message_type)

        async def application_runner() -> None:
            try:
                await self.asgi_app(scope, receive, send)
            except Exception as exc:  # pragma: no cover - forwarded to caller
                error_holder["error"] = exc
                response_queue.put(None)
            finally:
                if not disconnect_future.done():
                    disconnect_future.set_result(None)
                response_started.set()
                stop_event.set()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(application_runner())
            finally:
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()

        thread = threading.Thread(target=run_loop, name="tryton-mcp-asgi", daemon=True)
        thread.start()

        response_started.wait()

        if "error" in error_holder and not response_queue.qsize():
            exc = error_holder["error"]
            logger.exception("ASGI application failed", exc_info=exc)
            status = _http_status_line(HTTPStatus.INTERNAL_SERVER_ERROR)
            start_response(status, [("Content-Type", "text/plain")])
            thread.join()
            return iter([b"Internal Server Error"])

        status = status_holder.get("status", "200 OK")
        headers = status_holder.get("headers", [])
        start_response(status, headers)

        def body_iter() -> Generator[bytes, None, None]:
            try:
                while True:
                    chunk = response_queue.get()
                    if chunk is None:
                        break
                    yield chunk
            finally:
                if not stop_event.is_set():
                    stop_event.set()
                    if not disconnect_future.done():
                        loop.call_soon_threadsafe(disconnect_future.set_result, None)
                thread.join()

        return body_iter()

    @staticmethod
    def _build_scope(environ: dict[str, Any]) -> dict[str, Any]:
        headers = []
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                header_name = key[5:].replace("_", "-").lower().encode("latin1")
                headers.append((header_name, value.encode("latin1")))
        if environ.get("CONTENT_TYPE"):
            headers.append((b"content-type", environ["CONTENT_TYPE"].encode("latin1")))
        if environ.get("CONTENT_LENGTH"):
            headers.append((b"content-length", environ["CONTENT_LENGTH"].encode("latin1")))

        client = None
        if environ.get("REMOTE_ADDR"):
            port = environ.get("REMOTE_PORT")
            client = (environ["REMOTE_ADDR"], int(port) if port else 0)

        server = None
        if environ.get("SERVER_NAME"):
            port = environ.get("SERVER_PORT")
            server = (environ["SERVER_NAME"], int(port) if port else 0)

        path = environ.get("PATH_INFO", "")
        scope = {
            "type": "http",
            "http_version": environ.get("SERVER_PROTOCOL", "HTTP/1.1").split("/", 1)[-1],
            "method": environ.get("REQUEST_METHOD", "GET"),
            "scheme": environ.get("wsgi.url_scheme", "http"),
            "path": path,
            "raw_path": path.encode("latin1"),
            "query_string": environ.get("QUERY_STRING", "").encode("latin1"),
            "headers": headers,
            "client": client,
            "server": server,
            "root_path": environ.get("SCRIPT_NAME", ""),
            "state": {"tryton": environ.get("tryton.mcp_state")},
        }
        return scope


class TrytonMCPServer(FastMCP):
    """FastMCP server exposing Tryton RPC capabilities."""

    def __init__(self) -> None:
        super().__init__(
            name="Tryton MCP",
            instructions=(
                "Authenticate just like the JSON-RPC API and select a database either "
                "by calling /<database>/mcp or by sending an X-Tryton-Database header. "
                "The tools provide zero-configuration access to every Tryton model."
            ),
            json_response=False,
        )
        self._register_tools()

    @staticmethod
    def _state_from_context(ctx: Context) -> TrytonRequestState:
        try:
            request = ctx.request_context.request
            state = request.scope.get("state", {}).get("tryton")  # type: ignore[assignment]
        except AttributeError as exc:  # pragma: no cover - defensive
            raise TrytonException("Tryton context is not available") from exc
        if not isinstance(state, TrytonRequestState):
            raise TrytonException("Missing Tryton state")
        return state

    @contextmanager
    def _transaction(self, state: TrytonRequestState, readonly: bool = False):
        pool = Pool(state.database)
        context = dict(state.context)
        context.setdefault("_request", state.request_context)
        user = state.user_id

        retry = config.getint("database", "retry")
        transaction_extras: dict[str, Any] = {"close": True}
        count = 0
        transaction: Transaction | None = None
        while True:
            if count:
                time.sleep(0.02 * count)
            with Transaction().start(
                    pool.database_name,
                    user,
                    readonly=readonly,
                    context=context,
                    **transaction_extras) as transaction:
                try:
                    yield pool, transaction
                    transaction.commit()
                except TransactionError as exc:
                    transaction.rollback()
                    transaction.tasks.clear()
                    exc.fix(transaction_extras)
                    count += 1
                    continue
                except backend.DatabaseOperationalError:
                    transaction.rollback()
                    transaction.tasks.clear()
                    if count < retry and not readonly:
                        count += 1
                        continue
                    raise
                break
        if transaction is not None:
            while transaction.tasks:
                task_id = transaction.tasks.pop()
                run_task(pool, task_id)
        if state.session:
            security.reset(
                pool.database_name,
                state.session,
                context={"_request": state.request_context},
            )

    def _register_tools(self) -> None:
        @self.tool(name="tryton.list_models", description="List available Tryton models.")
        def list_models(ctx: Context) -> Iterable[dict[str, Any]]:
            state = self._state_from_context(ctx)
            with self._transaction(state, readonly=True) as (pool, _):
                Model = pool.get("ir.model")
                models = Model.search([], order=[("model", "ASC")])
                result = Model.read(models, ["model", "name", "info"])
                return _jsonable(result)

        @self.tool(name="tryton.describe_model", description="Inspect the fields of a Tryton model.")
        def describe_model(model: str, ctx: Context) -> dict[str, Any]:
            state = self._state_from_context(ctx)
            with self._transaction(state, readonly=True) as (pool, _):
                Model = pool.get(model)
                fields = Model.fields_get()
                return _jsonable(fields)

        @self.tool(name="tryton.search", description="Search records using a domain.")
        def search(
                model: str,
                domain: Optional[list[Any]] = None,
                offset: Optional[int] = None,
                limit: Optional[int] = None,
                order: Optional[list[Any]] = None,
                ctx: Context = None) -> list[int]:  # type: ignore[override]
            assert ctx is not None
            state = self._state_from_context(ctx)
            with self._transaction(state, readonly=True) as (pool, _):
                Model = pool.get(model)
                return Model.search(domain or [], offset=offset, limit=limit, order=order)

        @self.tool(name="tryton.read", description="Read fields from records.")
        def read(
                model: str,
                ids: list[int],
                fields: Optional[list[str]] = None,
                ctx: Context = None) -> Iterable[dict[str, Any]]:  # type: ignore[override]
            assert ctx is not None
            state = self._state_from_context(ctx)
            with self._transaction(state, readonly=True) as (pool, _):
                Model = pool.get(model)
                data = Model.read(ids, fields)
                return _jsonable(data)

        @self.tool(name="tryton.create", description="Create new records.")
        def create(
                model: str,
                values: list[dict[str, Any]] | dict[str, Any],
                ctx: Context = None) -> list[int]:  # type: ignore[override]
            assert ctx is not None
            state = self._state_from_context(ctx)
            if isinstance(values, dict):
                payload = [values]
            else:
                payload = values
            with self._transaction(state, readonly=False) as (pool, _):
                Model = pool.get(model)
                return Model.create(payload)

        @self.tool(name="tryton.write", description="Update existing records.")
        def write(
                model: str,
                ids: list[int],
                values: dict[str, Any],
                ctx: Context = None) -> bool:  # type: ignore[override]
            assert ctx is not None
            state = self._state_from_context(ctx)
            with self._transaction(state, readonly=False) as (pool, _):
                Model = pool.get(model)
                Model.write(ids, values)
                return True

        @self.tool(name="tryton.delete", description="Delete records from a model.")
        def delete(model: str, ids: list[int], ctx: Context = None) -> bool:  # type: ignore[override]
            assert ctx is not None
            state = self._state_from_context(ctx)
            with self._transaction(state, readonly=False) as (pool, _):
                Model = pool.get(model)
                Model.delete(ids)
                return True

        @self.tool(name="tryton.call", description="Call an arbitrary model method exposed via RPC.")
        def call(
                model: str,
                method: str,
                args: Optional[list[Any]] = None,
                kwargs: Optional[dict[str, Any]] = None,
                ctx: Context = None) -> Any:  # type: ignore[override]
            assert ctx is not None
            state = self._state_from_context(ctx)
            return _jsonable(self._call_rpc(state, model, method, args or [], kwargs or {}))

    def _call_rpc(
            self,
            state: TrytonRequestState,
            model_name: str,
            method: str,
            args: list[Any],
            kwargs: dict[str, Any],
    ) -> Any:
        pool = Pool(state.database)
        obj = pool.get(model_name)
        if method not in obj.__rpc__:
            raise TrytonException(f"Method {method} is not available via RPC on {model_name}")
        rpc = obj.__rpc__[method]
        kwargs = dict(kwargs)
        kwargs.setdefault("context", dict(state.context))
        kwargs["context"]["_request"] = state.request_context

        retry = config.getint("database", "retry")
        transaction_extras: dict[str, Any] = {"close": True}
        count = 0
        transaction: Transaction | None = None
        while True:
            if count:
                time.sleep(0.02 * count)
            with Transaction().start(
                    state.database,
                    state.user_id,
                    readonly=rpc.readonly,
                    timeout=rpc.timeout,
                    **transaction_extras) as transaction:
                try:
                    converted_args, converted_kwargs, transaction.context, transaction.timestamp = rpc.convert(
                        obj, *args, **kwargs)
                    transaction.context.setdefault("_request", state.request_context)
                    method_fn = rpc.decorate(getattr(obj, method))
                    if rpc.instantiate is None or not is_instance_method(obj, method):
                        result = rpc.result(method_fn(*converted_args, **converted_kwargs))
                    else:
                        inst = converted_args.pop(0)
                        if hasattr(inst, method):
                            result = rpc.result(method_fn(inst, *converted_args, **converted_kwargs))
                        else:
                            result = [
                                rpc.result(method_fn(i, *converted_args, **converted_kwargs))
                                for i in inst
                            ]
                    transaction.commit()
                except TransactionError as exc:
                    transaction.rollback()
                    transaction.tasks.clear()
                    exc.fix(transaction_extras)
                    count += 1
                    continue
                except backend.DatabaseOperationalError:
                    transaction.rollback()
                    transaction.tasks.clear()
                    if count < retry and not rpc.readonly:
                        count += 1
                        continue
                    raise
                except backend.DatabaseTimeoutError:
                    transaction.rollback()
                    transaction.tasks.clear()
                    raise
                except RPCReturnException as exc:
                    transaction.rollback()
                    transaction.tasks.clear()
                    result = exc.result()
                except (ConcurrencyException, UserError, UserWarning, LoginException):
                    transaction.rollback()
                    transaction.tasks.clear()
                    raise
                except Exception:
                    transaction.rollback()
                    transaction.tasks.clear()
                    raise
            if transaction is not None:
                while transaction.tasks:
                    task_id = transaction.tasks.pop()
                    run_task(pool, task_id)
            if state.session:
                security.reset(
                    state.database,
                    state.session,
                    context={"_request": state.request_context},
                )
            return result


_server = TrytonMCPServer()
_adapter = AsgiToWsgiAdapter(_server)


def _database_from_request(request: Request, database_name: Optional[str]) -> str:
    if database_name:
        return database_name
    header = request.headers.get("X-Tryton-Database")
    if header:
        return header
    abort(HTTPStatus.BAD_REQUEST)


def _prepare_state(request: Request, database_name: str) -> TrytonRequestState:
    request.view_args = {"database_name": database_name}
    user_id = request.user_id
    if not user_id:
        abort(HTTPStatus.UNAUTHORIZED)
    authorization = request.authorization
    session = authorization.get("session") if authorization and authorization.type == "session" else None
    username = authorization.get("userid") if authorization else None
    language = request.headers.get("Accept-Language")
    context = dict(request.context)
    if language:
        context.setdefault("language", language.split(",")[0])
    return TrytonRequestState(
        database=database_name,
        user_id=user_id,
        context=context,
        request_context=request.context,
        session=session,
        username=username,
    )


def _forward_to_asgi(request: Request, state: TrytonRequestState) -> Response:
    environ = dict(request.environ)
    environ["tryton.mcp_state"] = state
    script_name = environ.get("SCRIPT_NAME", "")
    path_info = environ.get("PATH_INFO", "")
    database_prefix = f"/{state.database}"
    if state.database and path_info.startswith(database_prefix):
        environ["SCRIPT_NAME"] = script_name + database_prefix
        trimmed = path_info[len(database_prefix):]
        environ["PATH_INFO"] = trimmed or "/"
    return Response.from_app(_adapter, environ, buffered=False)


@app.route("/<string:database_name>/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
@app.route("/mcp", methods=["GET", "POST", "DELETE", "OPTIONS"])
def mcp_endpoint(request: Request, database_name: Optional[str] = None) -> Response:
    if request.method == "OPTIONS":
        response = Response(status=HTTPStatus.NO_CONTENT)
        response.headers["Allow"] = "GET, POST, DELETE, OPTIONS"
        return response
    database = _database_from_request(request, database_name)
    state = _prepare_state(request, database)
    return _forward_to_asgi(request, state)


__all__ = [
    "mcp_endpoint",
]

