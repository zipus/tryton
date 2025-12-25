"""Minimal Tryton RPC helper for the Tuion console UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import data

try:
    from tryton.jsonrpc import ServerProxy
except Exception:  # pragma: no cover - optional dependency for demo mode
    ServerProxy = None  # type: ignore


@dataclass
class ConnectionInfo:
    host: str
    port: int
    database: str
    username: str

    @property
    def base_url(self) -> str:
        return f"{self.host}:{self.port}/{self.database}"


class TrytonTuiClient:
    """Lightweight facade for a Tryton JSON-RPC server."""

    def __init__(self, demo: bool = False):
        self.demo = demo or ServerProxy is None
        self.connection: Optional[ConnectionInfo] = None
        self._proxy = None
        self._session: Optional[str] = None
        self._user_id: Optional[int] = None
        self._last_error: Optional[str] = None
        self._demo_store: Dict[str, List[Dict[str, Any]]] = {
            model: [dict(record) for record in records] for model, records in data.DEMO_RECORDS.items()
        }
        self._demo_attachments: Dict[str, Dict[int, List[Dict[str, Any]]]] = {
            model: {rid: [dict(att) for att in attachments] for rid, attachments in records.items()}
            for model, records in data.DEMO_ATTACHMENTS.items()
        }
        self._translations: Dict[str, Dict[str, str]] = {**data.DEMO_TRANSLATIONS}
        self._prefs_path = Path.home() / ".tuion_prefs.json"
        self._cache_path = Path.home() / ".tuion_cache.json"
        self._demo_preferences: Dict[str, Any] = self._load_preferences()
        self._load_cache()

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def connect(
        self,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
    ) -> bool:
        """Establishes a JSON-RPC session.

        When the client is in demo mode the call always succeeds and the demo
        data is kept in memory. Otherwise it will attempt to authenticate using
        ``common.db.login`` and build a session-enabled :class:`ServerProxy`.
        """

        self._last_error = None
        self.connection = ConnectionInfo(host, port, database, username)

        if self.demo:
            return True

        try:
            proxy = ServerProxy(host, port, database)
            login_result = proxy.common.db.login(username, {"password": password})
            if not login_result or not isinstance(login_result, Iterable):
                self._last_error = "Authentication failed"
                return False

            user_id, session = login_result
            self._user_id = int(user_id)
            self._session = f"{username}:{user_id}:{session}"
            self._proxy = ServerProxy(host, port, database, session=self._session)
            return True
        except Exception as exc:  # pragma: no cover - network code
            self._last_error = str(exc)
            return False

    # Data loaders -----------------------------------------------------
    def server_version(self) -> str:
        if self.demo or not self._proxy:
            return "demo"
        try:
            return str(self._proxy.common.server.version())  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - network code
            return "unknown"

    def list_modules(self) -> List[Dict[str, Any]]:
        if self.demo or not self._proxy:
            return list(data.DEMO_MODULES)
        try:
            ids = self._proxy.model.ir.module.search([])  # type: ignore[attr-defined]
            return self._proxy.model.ir.module.read(ids, ["name", "state", "summary"])  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - network code
            return list(data.DEMO_MODULES)

    def list_menus(self) -> List[Dict[str, Any]]:
        if self.demo or not self._proxy:
            return list(data.DEMO_MENUS)
        try:
            ids = self._proxy.model.ir.ui.menu.search([])  # type: ignore[attr-defined]
            menus = self._proxy.model.ir.ui.menu.read(ids, ["complete_name", "action", "childs"])
            normalized = []
            for menu in menus:
                normalized.append(
                    {
                        "path": menu.get("complete_name"),
                        "model": menu.get("action"),
                        "count": len(menu.get("childs", [])),
                    }
                )
            return normalized
        except Exception:  # pragma: no cover - network code
            return list(data.DEMO_MENUS)

    def list_records(self, model: str) -> List[Dict[str, Any]]:
        return self.search_records(model, domain=[], limit=None, offset=0, sort=None)

    def search_records(
        self,
        model: str,
        domain: Sequence[Tuple[str, str, Any]] | Sequence[Any],
        sort: Optional[Tuple[str, str]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if self.demo or not self._proxy:
            records = list(self._demo_store.get(model, []))
            filtered = self._apply_domain(records, domain)
            if sort:
                key, direction = sort
                reverse = direction.lower() == "desc"
                filtered.sort(key=lambda rec: rec.get(key), reverse=reverse)
            if limit is None:
                return filtered[offset:]
            return filtered[offset : offset + limit]
        try:
            sort_clause = None
            if sort:
                field, direction = sort
                sort_clause = [(field, direction)]
            ids = self._proxy.model[model].search(list(domain), offset=offset, limit=limit, order=sort_clause)  # type: ignore[index]
            fields = list(self._proxy.model[model].fields_get([]).keys())  # type: ignore[index]
            return self._proxy.model[model].read(ids, fields)  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            return []

    def fields_get(self, model: str) -> Dict[str, Dict[str, Any]]:
        if self.demo or not self._proxy:
            return data.DEMO_FIELDS.get(model, {})
        try:
            return self._proxy.model[model].fields_get([])  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            return {}

    def translate(self, text: str) -> str:
        language = self.get_preferences().get("language", "en")
        translations = self._translations.get(language, {})
        return translations.get(text, text)

    def create_record(self, model: str, values: Dict[str, Any]) -> Optional[int]:
        cleaned = self._validate_values(model, values)
        if cleaned is None:
            return None
        if self.demo or not self._proxy:
            store = self._demo_store.setdefault(model, [])
            new_id = max([rec.get("id", 0) for rec in store] or [0]) + 1
            cleaned["id"] = new_id
            store.append(cleaned)
            self._save_cache()
            return new_id
        try:
            return int(self._proxy.model[model].create([cleaned])[0])  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            self._last_error = "Unable to create record"
            return None

    def update_record(self, model: str, record_id: int, values: Dict[str, Any]) -> bool:
        cleaned = self._validate_values(model, values)
        if cleaned is None:
            return False
        if self.demo or not self._proxy:
            store = self._demo_store.setdefault(model, [])
            for rec in store:
                if rec.get("id") == record_id:
                    rec.update(cleaned)
                    self._save_cache()
                    return True
            return False
        try:
            return bool(self._proxy.model[model].write([record_id], cleaned))  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            self._last_error = "Unable to update record"
            return False

    def delete_record(self, model: str, record_id: int) -> bool:
        if self.demo or not self._proxy:
            store = self._demo_store.setdefault(model, [])
            before = len(store)
            self._demo_store[model] = [rec for rec in store if rec.get("id") != record_id]
            removed = len(self._demo_store[model]) < before
            if removed:
                self._save_cache()
            return removed
        try:
            return bool(self._proxy.model[model].delete([record_id]))  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            self._last_error = "Unable to delete record"
            return False

    def actions_for(self, model: str) -> List[str]:
        if self.demo or not self._proxy:
            return list(data.DEMO_ACTIONS.get(model, []))
        try:
            return list(self._proxy.model[model].actions)  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            return []

    def run_action(self, model: str, action: str, ids: Sequence[int]) -> str:
        if self.demo or not self._proxy:
            updated: List[int] = []
            for record_id in ids:
                store = self._demo_store.get(model, [])
                for rec in store:
                    if rec.get("id") == record_id:
                        if model == "sale.quotation" and action.lower().startswith("confirm"):
                            rec["state"] = "confirmed"
                        elif model == "sale.quotation" and action.lower().startswith("print"):
                            pass
                        elif model == "stock.move" and action.lower() == "done":
                            rec["done"] = True
                        updated.append(record_id)
            return f"Action '{action}' executed for ids {updated}" if updated else "Nothing changed"
        try:
            result = self._proxy.model[model].execute_action(action, list(ids))  # type: ignore[index]
            return str(result)
        except Exception:  # pragma: no cover - network code
            return "Unable to run action"

    def reports_for(self, model: str) -> List[str]:
        if self.demo or not self._proxy:
            return list(data.DEMO_REPORTS.get(model, []))
        try:
            return list(self._proxy.model[model].reports)  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            return []

    def run_report(self, model: str, report: str, ids: Sequence[int]) -> str:
        if self.demo or not self._proxy:
            target = Path("/tmp") / f"tuion_{model.replace('.', '_')}_{report.replace(' ', '_').lower()}.txt"
            target.write_text(f"Demo report {report} for ids {list(ids)}\n")
            return f"Report '{report}' saved to {target}"
        try:
            return str(self._proxy.model[model].execute_report(report, list(ids)))  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            return "Unable to generate report"

    # Attachments ------------------------------------------------------
    def list_attachments(self, model: str, record_id: int) -> List[Dict[str, Any]]:
        if self.demo or not self._proxy:
            model_store = self._demo_attachments.get(model, {})
            return [dict(att) for att in model_store.get(record_id, [])]
        try:
            domain = [("resource", "=", f"{model},{record_id}")]
            ids = self._proxy.model.ir.attachment.search(domain)  # type: ignore[attr-defined]
            return self._proxy.model.ir.attachment.read(ids, ["id", "name", "description", "data"])  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - network code
            return []

    def add_attachment(self, model: str, record_id: int, name: str, content: str) -> Optional[int]:
        if self.demo or not self._proxy:
            model_store = self._demo_attachments.setdefault(model, {})
            attachments = model_store.setdefault(record_id, [])
            new_id = max([att.get("id", 0) for att in attachments] or [0]) + 1
            attachments.append({"id": new_id, "name": name, "content": content})
            self._save_cache()
            return new_id
        try:
            values = {"name": name, "data": content, "resource": f"{model},{record_id}"}
            return int(self._proxy.model.ir.attachment.create([values])[0])  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - network code
            self._last_error = "Unable to add attachment"
            return None

    def delete_attachment(self, model: str, record_id: int, attachment_id: int) -> bool:
        if self.demo or not self._proxy:
            model_store = self._demo_attachments.setdefault(model, {})
            attachments = model_store.setdefault(record_id, [])
            before = len(attachments)
            model_store[record_id] = [att for att in attachments if att.get("id") != attachment_id]
            removed = len(model_store[record_id]) < before
            if removed:
                self._save_cache()
            return removed
        try:
            return bool(self._proxy.model.ir.attachment.delete([attachment_id]))  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - network code
            self._last_error = "Unable to delete attachment"
            return False

    def download_attachment(self, model: str, record_id: int, attachment_id: int, target: Path) -> str:
        if self.demo or not self._proxy:
            attachments = self._demo_attachments.get(model, {}).get(record_id, [])
            for att in attachments:
                if att.get("id") == attachment_id:
                    target.write_text(str(att.get("content", "")))
                    return str(target)
            return "Attachment not found"
        try:
            record = self._proxy.model.ir.attachment.read([attachment_id], ["data", "name"])[0]  # type: ignore[attr-defined]
            content = record.get("data", "")
            target.write_text(str(content))
            return str(target)
        except Exception:  # pragma: no cover - network code
            return "Unable to download attachment"

    # Wizards ----------------------------------------------------------
    def wizards_for(self, model: str) -> List[str]:
        if self.demo or not self._proxy:
            return list(data.DEMO_WIZARDS.get(model, {}).keys())
        try:
            model_proxy = self._proxy.model[model]
            return list(getattr(model_proxy, "wizards", []))  # type: ignore[index]
        except Exception:  # pragma: no cover - network code
            return []

    def wizard_steps(self, model: str, wizard: str) -> List[Dict[str, Dict[str, Any]]]:
        if self.demo or not self._proxy:
            return list(data.DEMO_WIZARDS.get(model, {}).get(wizard, []))
        return []

    def run_wizard(self, model: str, wizard: str, ids: Sequence[int], values: Dict[str, Any]) -> str:
        if self.demo or not self._proxy:
            if wizard.lower().startswith("confirm"):
                for record_id in ids:
                    for rec in self._demo_store.get(model, []):
                        if rec.get("id") == record_id:
                            rec["state"] = "confirmed"
                self._save_cache()
                return f"Wizard '{wizard}' confirmed records {list(ids)}"
            if wizard.lower().startswith("duplicate") and ids:
                source_id = ids[0]
                source = next((rec for rec in self._demo_store.get(model, []) if rec.get("id") == source_id), None)
                if source:
                    copy = dict(source)
                    copy["id"] = max([rec.get("id", 0) for rec in self._demo_store.get(model, [])] or [0]) + 1
                    copy["number"] = values.get("number", f"COPY-{source_id}")
                    self._demo_store[model].append(copy)
                    self._save_cache()
                    return f"Duplicated record {source_id} to {copy['id']}"
            if wizard.lower().startswith("force done"):
                for record_id in ids:
                    for rec in self._demo_store.get(model, []):
                        if rec.get("id") == record_id:
                            rec["done"] = True
                self._save_cache()
                return f"Forced completion for {list(ids)}"
            return f"Wizard '{wizard}' executed"
        try:
            model_proxy = self._proxy.model[model]
            if hasattr(model_proxy, "execute_wizard"):
                return str(model_proxy.execute_wizard(wizard, list(ids), values))  # type: ignore[index]
            return "Wizard RPC unavailable"
        except Exception:  # pragma: no cover - network code
            return "Unable to run wizard"

    def get_preferences(self) -> Dict[str, Any]:
        if self.demo or not self._proxy:
            return dict(self._demo_preferences)
        try:
            return dict(self._proxy.model.res.user.get_preferences(True, {}))  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - network code
            return {}

    def set_preferences(self, **values: Any) -> Dict[str, Any]:
        if self.demo or not self._proxy:
            self._demo_preferences.update(values)
            self._save_preferences(self._demo_preferences)
            return dict(self._demo_preferences)
        try:
            return dict(self._proxy.model.res.user.set_preferences(values))  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - network code
            return {}

    # Internal helpers -------------------------------------------------
    def _apply_domain(
        self, records: List[Dict[str, Any]], domain: Sequence[Tuple[str, str, Any]] | Sequence[Any]
    ) -> List[Dict[str, Any]]:
        if not domain:
            return records
        normalized: List[Tuple[str, str, Any]] = []
        for item in domain:
            if isinstance(item, (list, tuple)) and len(item) == 3:
                normalized.append((str(item[0]), str(item[1]).lower(), item[2]))
        result = []
        for record in records:
            include = True
            for field, operator, value in normalized:
                candidate = record.get(field)
                if operator == "ilike":
                    if value is None or candidate is None or str(value).lower() not in str(candidate).lower():
                        include = False
                        break
                elif operator == "like":
                    if value is None or candidate is None or str(value) not in str(candidate):
                        include = False
                        break
                elif operator == "=":
                    if candidate != value:
                        include = False
                        break
                elif operator == "!=":
                    if candidate == value:
                        include = False
                        break
                elif operator == ">":
                    if candidate is None or candidate <= value:
                        include = False
                        break
                elif operator == "<":
                    if candidate is None or candidate >= value:
                        include = False
                        break
                elif operator == ">=":
                    if candidate is None or candidate < value:
                        include = False
                        break
                elif operator == "<=":
                    if candidate is None or candidate > value:
                        include = False
                        break
                elif operator == "in":
                    try:
                        if candidate not in value:
                            include = False
                            break
                    except Exception:
                        include = False
                        break
            if include:
                result.append(record)
        return result

    # Validation and persistence ---------------------------------------
    def _validate_values(self, model: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate and coerce form values using ``fields_get`` metadata.

        Returns a cleaned dict or ``None`` if validation failed, populating
        ``self._last_error`` with the failure reason. This mirrors the GTK
        client's typed widgets and inline validation messages.
        """

        fields = self.fields_get(model)
        cleaned: Dict[str, Any] = {}
        for name, meta in fields.items():
            raw = values.get(name)
            if raw in (None, ""):
                cleaned[name] = None
                continue

            ftype = meta.get("type")
            try:
                if ftype in ("integer", "biginteger"):
                    cleaned[name] = int(raw)
                elif ftype == "float":
                    cleaned[name] = float(raw)
                elif ftype == "boolean":
                    cleaned[name] = str(raw).lower() in {"1", "true", "yes", "y"}
                elif ftype == "selection":
                    selection = {str(v) for v in meta.get("selection", [])}
                    if str(raw) not in selection:
                        raise ValueError(f"{raw} not in {sorted(selection)}")
                    cleaned[name] = raw
                elif ftype == "date":
                    if isinstance(raw, datetime):
                        cleaned[name] = raw.strftime("%Y-%m-%d")
                    else:
                        cleaned[name] = datetime.fromisoformat(str(raw)).date().isoformat()
                else:
                    cleaned[name] = raw
            except Exception as exc:  # pragma: no cover - trivial conversions
                self._last_error = f"Invalid value for {name}: {exc}"
                return None
        return cleaned

    def _load_preferences(self) -> Dict[str, Any]:
        default = {"language": "en", "timezone": "UTC", "limit": 10}
        if not self._prefs_path.exists():
            return default
        try:
            data = json.loads(self._prefs_path.read_text())
            return {**default, **data}
        except Exception:  # pragma: no cover - IO
            return default

    def _save_preferences(self, prefs: Dict[str, Any]) -> None:
        try:
            self._prefs_path.write_text(json.dumps(prefs, indent=2))
        except Exception:  # pragma: no cover - IO
            pass

    def _load_cache(self) -> None:
        if not self._cache_path.exists():
            return
        try:
            payload = json.loads(self._cache_path.read_text())
            self._demo_store.update(payload.get("records", {}))
            self._demo_attachments.update(payload.get("attachments", {}))
        except Exception:  # pragma: no cover - IO
            return

    def _save_cache(self) -> None:
        try:
            payload = {"records": self._demo_store, "attachments": self._demo_attachments}
            self._cache_path.write_text(json.dumps(payload, indent=2))
        except Exception:  # pragma: no cover - IO
            return
