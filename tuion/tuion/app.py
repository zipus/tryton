"""Textual interface for the Tuion client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ast
from typing import Dict, Iterable, List, Optional, Sequence

from rich.panel import Panel
from textual.app import App, ComposeResult
from textual.containers import Grid, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Input, Label, OptionList, Static, TextLog

from .client import TrytonTuiClient


@dataclass
class LoginState:
    host: str = "localhost"
    port: int = 8000
    database: str = "demo"
    username: str = "demo"
    password: str = "demo"


@dataclass
class WorkspaceState:
    model: Optional[str] = None
    sort_field: Optional[str] = None
    sort_direction: str = "asc"
    limit: int = 10
    offset: int = 0
    search_query: str = ""
    view_mode: str = "list"
    group_field: Optional[str] = None
    calendar_field: Optional[str] = None
    last_records: List[Dict[str, object]] = None  # type: ignore[assignment]


class LoginScreen(Screen[bool]):
    BINDINGS = [
        ("escape", "app.quit", "Quit"),
    ]

    def __init__(self, client: TrytonTuiClient):
        super().__init__()
        self.client = client
        self.state = LoginState()
        self.error = reactive("")

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=True)
        yield Vertical(
            Label("Connect to Tryton", id="title"),
            Input(self.state.host, placeholder="Host", id="host"),
            Input(str(self.state.port), placeholder="Port", id="port"),
            Input(self.state.database, placeholder="Database", id="database"),
            Input(self.state.username, placeholder="User", id="username"),
            Input(self.state.password, placeholder="Password", password=True, id="password"),
            Button("Connect", id="connect", variant="primary"),
            Static(id="error"),
            id="login-form",
        )
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "connect":
            self._handle_connect()

    def _handle_connect(self) -> None:
        host = self.query_one("#host", Input).value or self.state.host
        port = int(self.query_one("#port", Input).value or self.state.port)
        database = self.query_one("#database", Input).value or self.state.database
        username = self.query_one("#username", Input).value or self.state.username
        password = self.query_one("#password", Input).value or self.state.password

        connected = self.client.connect(host, port, database, username, password)
        if connected:
            self.dismiss(True)
        else:
            self.error = self.client.last_error or "Unable to connect"
            self.query_one("#error", Static).update(Panel(self.error, border_style="red"))


class FormScreen(Screen[Dict[str, object]]):
    BINDINGS = [("escape", "app.pop_screen", "Cancel")]

    def __init__(self, title: str, fields: Dict[str, Dict[str, object]], values: Optional[Dict[str, object]] = None):
        super().__init__()
        self.title = title
        self.fields = fields
        self.values = values or {}
        self.error = reactive("")

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=False)
        with Vertical(id="form-panel"):
            yield Label(self.title, id="form-title")
            for field_name, meta in self.fields.items():
                label = f"{meta.get('string', field_name)} ({meta.get('type', 'char')})"
                choices = meta.get("selection", [])
                hint = f"Choices: {', '.join(map(str, choices))}" if choices else ""
                initial = str(self.values.get(field_name, ""))
                yield Label(label, id=f"label-{field_name}")
                yield Input(initial, placeholder=hint or label, id=f"field-{field_name}")
            yield Label(id="form-error")
            with Horizontal(id="form-buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._submit()
        else:
            self.app.pop_screen()

    def _submit(self) -> None:
        result: Dict[str, object] = {}
        for field_name, meta in self.fields.items():
            value = self.query_one(f"#field-{field_name}", Input).value
            if value:
                try:
                    ftype = meta.get("type")
                    if ftype in ("integer", "biginteger"):
                        result[field_name] = int(value)
                    elif ftype == "float":
                        result[field_name] = float(value)
                    elif ftype == "boolean":
                        result[field_name] = value.lower() in {"1", "true", "yes", "y"}
                    elif ftype == "selection":
                        selection = {str(v) for v in meta.get("selection", [])}
                        if value not in selection:
                            raise ValueError(f"Choose one of {', '.join(selection)}")
                        result[field_name] = value
                    else:
                        result[field_name] = value
                except Exception as exc:
                    self.query_one("#form-error", Label).update(str(exc))
                    return
            else:
                result[field_name] = None
        self.query_one("#form-error", Label).update("")
        self.dismiss(result)


class SelectionScreen(Screen[str]):
    BINDINGS = [("escape", "app.pop_screen", "Cancel")]

    def __init__(self, title: str, options: Sequence[str]):
        super().__init__()
        self.title = title
        self.options = options

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=False)
        yield Label(self.title, id="selection-title")
        option_list = OptionList(*self.options, id="selection-options")
        yield option_list
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.prompt))


class PreferencesScreen(Screen[Dict[str, object]]):
    BINDINGS = [("escape", "app.pop_screen", "Cancel")]

    def __init__(self, current: Dict[str, object]):
        super().__init__()
        self.current = current

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=False)
        with Vertical(id="prefs-panel"):
            yield Label("User Preferences", id="prefs-title")
            yield Input(str(self.current.get("language", "")), placeholder="Language", id="pref-language")
            yield Input(str(self.current.get("timezone", "")), placeholder="Timezone", id="pref-timezone")
            yield Input(str(self.current.get("limit", "10")), placeholder="Page size", id="pref-limit")
            with Horizontal(id="prefs-buttons"):
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._submit()
        else:
            self.app.pop_screen()

    def _submit(self) -> None:
        result = {
            "language": self.query_one("#pref-language", Input).value or "en",
            "timezone": self.query_one("#pref-timezone", Input).value or "UTC",
            "limit": int(self.query_one("#pref-limit", Input).value or 10),
        }
        self.dismiss(result)


class AttachmentsScreen(Screen[Dict[str, object]]):
    BINDINGS = [("escape", "app.pop_screen", "Close")]

    def __init__(self, attachments: List[Dict[str, object]]):
        super().__init__()
        self.attachments = attachments
        self.selected_id: Optional[int] = None

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=False)
        yield Label("Attachments", id="attach-title")
        prompts = []
        for att in self.attachments:
            label = f"{att.get('id')}: {att.get('name')}"
            prompts.append(label)
        option_list = OptionList(*prompts, id="attach-options")
        yield option_list
        yield Label("Name (for add)", id="attach-name-label")
        yield Input(placeholder="Attachment name", id="attach-name")
        yield Label("Content or file path (also used for download path)", id="attach-content-label")
        yield Input(placeholder="Content or file path", id="attach-content")
        with Horizontal(id="attach-buttons"):
            yield Button("Add", id="attach-add", variant="success")
            yield Button("Download", id="attach-download")
            yield Button("Delete", id="attach-delete", variant="error")
            yield Button("Close", id="attach-close")
        yield Label(id="attach-error")
        yield Footer()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        try:
            self.selected_id = int(str(event.option.prompt).split(":", 1)[0])
        except Exception:
            self.selected_id = None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "attach-close":
            self.app.pop_screen()
            return

        error_label = self.query_one("#attach-error", Label)
        error_label.update("")
        name_input = self.query_one("#attach-name", Input).value or "attachment.txt"
        content_input = self.query_one("#attach-content", Input).value or ""

        if event.button.id == "attach-add":
            content = content_input
            try:
                candidate = Path(content_input)
                if candidate.exists():
                    content = candidate.read_text()
            except Exception:
                pass
            self.dismiss({"action": "add", "name": name_input, "content": content})
        elif event.button.id == "attach-download":
            if self.selected_id is None:
                error_label.update("Select an attachment to download")
                return
            path = content_input or name_input
            self.dismiss({"action": "download", "id": self.selected_id, "path": path})
        elif event.button.id == "attach-delete":
            if self.selected_id is None:
                error_label.update("Select an attachment to delete")
                return
            self.dismiss({"action": "delete", "id": self.selected_id})


class WorkspaceScreen(Screen):
    BINDINGS = [
        ("escape", "app.pop_screen", "Back"),
        ("?", "toggle_help", "Help"),
    ]

    def __init__(self, client: TrytonTuiClient):
        super().__init__()
        self.client = client
        self.state = WorkspaceState(limit=client.get_preferences().get("limit", 10))
        self.state.last_records = []

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=True)
        with Grid(id="workspace"):
            with Vertical(id="menus"):
                yield Label("Menus", id="menus-title")
                yield DataTable(id="menu-table")
            with Vertical(id="records"):
                yield Label("Records", id="records-title")
                with Horizontal(id="record-controls"):
                    yield Input(placeholder="Search domain or text", id="search")
                    yield Button("Search", id="search-btn", variant="primary")
                    yield OptionList("List", "Kanban", "Calendar", id="view-mode")
                with Horizontal(id="sort-controls"):
                    yield Input(placeholder="Sort field", id="sort-field")
                    yield Button("Toggle Sort", id="sort-toggle")
                    yield Button("Prev", id="prev-page")
                    yield Button("Next", id="next-page")
                with Horizontal(id="view-controls"):
                    yield Input(placeholder="Group field (kanban)", id="group-field")
                    yield Input(placeholder="Date field (calendar)", id="calendar-field")
                with Horizontal(id="crud-controls"):
                    yield Button("New", id="new-record", variant="success")
                    yield Button("Edit", id="edit-record")
                    yield Button("Delete", id="delete-record", variant="error")
                    yield Button("Attach", id="attachments")
                    yield Button("Wizards", id="wizards")
                    yield Button("Actions", id="actions")
                    yield Button("Reports", id="reports")
                    yield Button("Prefs", id="prefs")
                yield DataTable(id="record-table")
                yield TextLog(highlight=True, markup=True, id="record-board")
                yield TextLog(highlight=True, markup=True, id="message-log")
            with Vertical(id="details"):
                yield Label("Details", id="details-title")
                yield TextLog(highlight=True, markup=True, id="record-detail")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_menus()
        self._refresh_preferences()
        view_selector = self.query_one("#view-mode", OptionList)
        view_selector.index = 0

    def action_toggle_help(self) -> None:
        help_text = (
            "Enter to drill menus, arrow keys to navigate records. "
            "Use Search to filter, Sort to change ordering, and Prev/Next for pagination."
        )
        self.app.push_screen(InfoScreen(help_text))

    # Menu and record handling -----------------------------------------
    def _populate_menus(self) -> None:
        table = self.query_one("#menu-table", DataTable)
        table.clear(columns=True)
        table.add_columns("Path", "Model", "Count")
        for menu in self.client.list_menus():
            table.add_row(menu.get("path", ""), menu.get("model", ""), str(menu.get("count", 0)))
        table.focus()
        table.cursor_type = "row"

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id == "menu-table":
            row = event.data_table.get_row(event.row_key)
            if row and len(row) > 1:
                self.state.model = str(row[1])
                self.state.offset = 0
                self._populate_records(self.state.model)

    def _populate_records(self, model: str) -> None:
        table = self.query_one("#record-table", DataTable)
        table.clear(columns=True)
        domain = self._parse_search(self.state.search_query)
        records = self.client.search_records(
            model,
            domain=domain,
            sort=(self.state.sort_field, self.state.sort_direction) if self.state.sort_field else None,
            limit=self.state.limit,
            offset=self.state.offset,
        )
        self.state.last_records = records
        headers = sorted({key for record in records for key in record.keys()}) or ["name"]
        self._render_records(headers, records)
        if headers and records:
            self._show_record_detail(headers, records[0])
        table.cursor_type = "row"
        self._log(f"Loaded {len(records)} records (offset {self.state.offset})")

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        if event.data_table.id == "record-table" and self.state.model:
            row = event.data_table.get_row(event.coordinate.row)
            headers = list(event.data_table.columns.keys())
            if row is not None:
                record = dict(zip(headers, row))
                self._show_record_detail(headers, record)

    def _show_record_detail(self, headers: Iterable[str], record: Dict[str, object]) -> None:
        detail = self.query_one("#record-detail", TextLog)
        detail.clear()
        for header in headers:
            label = self.client.translate(header)
            detail.write(f"[b]{label}[/b]: {record.get(header, '')}")

    def _render_records(self, headers: List[str], records: List[Dict[str, object]]) -> None:
        table = self.query_one("#record-table", DataTable)
        board = self.query_one("#record-board", TextLog)
        table.visible = self.state.view_mode == "list"
        board.visible = self.state.view_mode != "list"
        board.clear()
        table.clear(columns=True)
        if self.state.view_mode == "list":
            table.add_columns(*headers)
            for record in records:
                table.add_row(*(str(record.get(column, "")) for column in headers))
        elif self.state.view_mode == "kanban":
            group_field = self.state.group_field or headers[0]
            lanes: Dict[str, List[Dict[str, object]]] = {}
            for record in records:
                lane = str(record.get(group_field, "(none)"))
                lanes.setdefault(lane, []).append(record)
            for lane, items in lanes.items():
                board.write(f"[b]{self.client.translate(group_field)}: {lane}[/b]")
                for item in items:
                    summary = item.get("name") or item.get("number") or item
                    board.write(f" • {summary}")
                board.write("")
        elif self.state.view_mode == "calendar":
            date_field = self.state.calendar_field or headers[-1]
            calendar: Dict[str, List[Dict[str, object]]] = {}
            for record in records:
                date_value = str(record.get(date_field, "unscheduled"))
                calendar.setdefault(date_value, []).append(record)
            for day in sorted(calendar.keys()):
                board.write(f"[b]{self.client.translate(date_field)}: {day}[/b]")
                for item in calendar[day]:
                    summary = item.get("name") or item.get("number") or item
                    board.write(f" • {summary}")
                board.write("")

    def _parse_search(self, query: str) -> List[List[object]]:
        if not query:
            return []
        # Try to accept Tryton-style domain literals
        try:
            literal = ast.literal_eval(query)
            if isinstance(literal, list):
                return literal  # type: ignore[return-value]
        except Exception:
            pass
        clauses: List[List[object]] = []
        for fragment in query.split(";"):
            fragment = fragment.strip()
            if not fragment:
                continue
            if " " in fragment:
                parts = fragment.split()
                if len(parts) >= 3:
                    field, op, value = parts[0], parts[1], " ".join(parts[2:])
                    clauses.append([field, op, value])
                    continue
            if "=" in fragment:
                field, value = fragment.split("=", 1)
                clauses.append([field.strip(), "=", value.strip()])
            else:
                clauses.append(["name", "ilike", fragment])
        return [self._coerce_clause(clause) for clause in clauses]

    def _coerce_clause(self, clause: List[object]) -> List[object]:
        if len(clause) != 3 or not self.state.model:
            return clause
        fields = self.client.fields_get(self.state.model)
        field_name, op, value = clause
        meta = fields.get(str(field_name), {})
        ftype = meta.get("type")
        try:
            if ftype in ("integer", "biginteger"):
                return [field_name, op, int(value)]
            if ftype == "float":
                return [field_name, op, float(value)]
            if ftype == "boolean":
                lowered = str(value).lower()
                return [field_name, op, lowered in {"1", "true", "yes", "y"}]
            if ftype == "date":
                return [field_name, op, str(value)]
        except Exception:
            return clause
        return clause

    def _log(self, message: str) -> None:
        log = self.query_one("#message-log", TextLog)
        log.write(message)

    def _open_actions(self) -> None:
        if not self.state.model:
            self._log("Select a model to view actions")
            return
        options = self.client.actions_for(self.state.model)
        if not options:
            self._log("No actions available")
            return
        self.app.push_screen(
            SelectionScreen("Run Action", options),
            callback=lambda choice: self._run_action(choice or ""),
        )

    def _run_action(self, choice: str) -> None:
        if not choice or not self.state.model:
            return
        record = self._current_record()
        ids = [int(record["id"])] if record and "id" in record else []
        outcome = self.client.run_action(self.state.model, choice, ids)
        self._log(outcome)

    def _open_reports(self) -> None:
        if not self.state.model:
            self._log("Select a model to view reports")
            return
        options = self.client.reports_for(self.state.model)
        if not options:
            self._log("No reports available")
            return
        self.app.push_screen(
            SelectionScreen("Generate Report", options),
            callback=lambda choice: self._run_report(choice or ""),
        )

    def _run_report(self, choice: str) -> None:
        if not choice or not self.state.model:
            return
        record = self._current_record()
        ids = [int(record["id"])] if record and "id" in record else []
        outcome = self.client.run_report(self.state.model, choice, ids)
        self._log(outcome)

    def _open_attachments(self) -> None:
        record = self._current_record()
        if not record or "id" not in record or not self.state.model:
            self._log("Select a record to manage attachments")
            return
        attachments = self.client.list_attachments(self.state.model, int(record["id"]))
        self.app.push_screen(
            AttachmentsScreen(attachments),
            callback=lambda payload: self._after_attachment(payload, record),
        )

    def _after_attachment(self, payload: Optional[Dict[str, object]], record: Dict[str, object]) -> None:
        if payload is None or not self.state.model:
            return
        action = payload.get("action")
        if action == "add":
            new_id = self.client.add_attachment(
                self.state.model,
                int(record.get("id", 0)),
                str(payload.get("name", "attachment.txt")),
                str(payload.get("content", "")),
            )
            if new_id is None:
                self._log(self.client.last_error or "Unable to add attachment")
            else:
                self._log(f"Added attachment {new_id}")
        elif action == "delete":
            deleted = self.client.delete_attachment(
                self.state.model, int(record.get("id", 0)), int(payload.get("id", 0))
            )
            if deleted:
                self._log(f"Deleted attachment {payload.get('id')}")
            else:
                self._log(self.client.last_error or "Delete failed")
        elif action == "download":
            target = Path(str(payload.get("path", "attachment.txt")))
            location = self.client.download_attachment(
                self.state.model, int(record.get("id", 0)), int(payload.get("id", 0)), target
            )
            self._log(f"Saved to {location}")

    def _open_wizards(self) -> None:
        if not self.state.model:
            self._log("Select a model to view wizards")
            return
        options = self.client.wizards_for(self.state.model)
        if not options:
            self._log("No wizards available")
            return
        self.app.push_screen(
            SelectionScreen("Run Wizard", options),
            callback=lambda choice: self._start_wizard(choice or ""),
        )

    def _start_wizard(self, choice: str) -> None:
        if not choice or not self.state.model:
            return
        steps = self.client.wizard_steps(self.state.model, choice)
        if not steps:
            self._finish_wizard(choice, {})
            return
        self._wizard_step(0, steps, choice, {})

    def _wizard_step(
        self,
        index: int,
        steps: List[Dict[str, Dict[str, object]]],
        wizard: str,
        payload: Dict[str, object],
    ) -> None:
        if index >= len(steps):
            self._finish_wizard(wizard, payload)
            return
        fields = steps[index]
        self.app.push_screen(
            FormScreen(f"{wizard} (step {index + 1})", fields, {}),
            callback=lambda values: self._after_wizard(values, index, steps, wizard, payload),
        )

    def _after_wizard(
        self,
        values: Optional[Dict[str, object]],
        index: int,
        steps: List[Dict[str, Dict[str, object]]],
        wizard: str,
        payload: Dict[str, object],
    ) -> None:
        if values is None:
            return
        payload.update(values)
        self._wizard_step(index + 1, steps, wizard, payload)

    def _finish_wizard(self, wizard: str, payload: Dict[str, object]) -> None:
        record = self._current_record()
        ids = [int(record["id"])] if record and "id" in record else []
        outcome = self.client.run_wizard(self.state.model or "", wizard, ids, payload)
        self._log(outcome)
        if self.state.model:
            self._populate_records(self.state.model)

    def _open_preferences(self) -> None:
        prefs = self.client.get_preferences()
        self.app.push_screen(
            PreferencesScreen(prefs),
            callback=self._after_prefs,
        )

    def _after_prefs(self, values: Optional[Dict[str, object]]) -> None:
        if not values:
            return
        updated = self.client.set_preferences(**values)
        self.state.limit = int(updated.get("limit", self.state.limit))
        self._log("Preferences saved")
        if self.state.model:
            self._populate_records(self.state.model)

    def _refresh_preferences(self) -> None:
        prefs = self.client.get_preferences()
        self.state.limit = int(prefs.get("limit", self.state.limit))

    # Event handlers ---------------------------------------------------
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "search-btn":
            self.state.search_query = self.query_one("#search", Input).value or ""
            self.state.group_field = self.query_one("#group-field", Input).value or None
            self.state.calendar_field = self.query_one("#calendar-field", Input).value or None
            self.state.offset = 0
            if self.state.model:
                self._populate_records(self.state.model)
        elif event.button.id == "sort-toggle":
            self.state.sort_field = self.query_one("#sort-field", Input).value or None
            self.state.sort_direction = "desc" if self.state.sort_direction == "asc" else "asc"
            if self.state.model:
                self._populate_records(self.state.model)
        elif event.button.id == "prev-page":
            self.state.offset = max(self.state.offset - self.state.limit, 0)
            if self.state.model:
                self._populate_records(self.state.model)
        elif event.button.id == "next-page":
            self.state.offset += self.state.limit
            if self.state.model:
                self._populate_records(self.state.model)
        elif event.button.id == "new-record":
            self._open_form(new=True)
        elif event.button.id == "edit-record":
            self._open_form(new=False)
        elif event.button.id == "delete-record":
            self._delete_selected()
        elif event.button.id == "attachments":
            self._open_attachments()
        elif event.button.id == "wizards":
            self._open_wizards()
        elif event.button.id == "actions":
            self._open_actions()
        elif event.button.id == "reports":
            self._open_reports()
        elif event.button.id == "prefs":
            self._open_preferences()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_list.id == "view-mode":
            self.state.view_mode = event.option.prompt.lower()
            if self.state.model:
                self._populate_records(self.state.model)

    # CRUD helpers -----------------------------------------------------
    def _current_record(self) -> Optional[Dict[str, object]]:
        table = self.query_one("#record-table", DataTable)
        if table.cursor_row is None:
            return self.state.last_records[0] if self.state.last_records else None
        headers = list(table.columns.keys())
        row = table.get_row(table.cursor_row)
        if row is None:
            return None
        return dict(zip(headers, row))

    def _open_form(self, new: bool) -> None:
        if not self.state.model:
            self._log("Select a menu first")
            return
        fields = {
            name: {**meta, "string": self.client.translate(meta.get("string", name))}
            for name, meta in self.client.fields_get(self.state.model).items()
        }
        record = None if new else self._current_record()
        self.app.push_screen(
            FormScreen(f"{'New' if new else 'Edit'} {self.state.model}", fields, record or {}),
            callback=lambda values: self._after_form(values, new, record),
        )

    def _after_form(self, values: Optional[Dict[str, object]], new: bool, record: Optional[Dict[str, object]]) -> None:
        if values is None:
            return
        if new:
            created = self.client.create_record(self.state.model or "", values)
            if created is None:
                self._log(self.client.last_error or "Create failed")
            else:
                self._log(f"Created record {created}")
        else:
            if record and "id" in record:
                updated = self.client.update_record(self.state.model or "", int(record["id"]), values)
                if updated:
                    self._log(f"Updated record {record['id']}")
                else:
                    self._log(self.client.last_error or "Update failed")
        if self.state.model:
            self._populate_records(self.state.model)

    def _delete_selected(self) -> None:
        record = self._current_record()
        if not record or "id" not in record or not self.state.model:
            self._log("No record selected for deletion")
            return
        deleted = self.client.delete_record(self.state.model, int(record["id"]))
        if deleted:
            self._log(f"Deleted record {record['id']}")
            self._populate_records(self.state.model)
        else:
            self._log("Delete failed")


class InfoScreen(Screen[None]):
    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:  # type: ignore[override]
        yield Header(show_clock=False)
        yield Static(Panel(self.message, title="Help"), id="info")
        yield Footer()

    def on_key(self, event) -> None:  # type: ignore[override]
        self.app.pop_screen()


class TuionApp(App[None]):
    CSS = """
    #workspace {
        grid-size: 3;
        grid-columns: 1fr 2fr 1fr;
        grid-rows: auto 1fr;
        column-gap: 1;
    }
    #menus, #records, #details {
        border: solid $accent;
        padding: 1 1;
    }
    #record-controls, #sort-controls, #crud-controls {
        width: 100%;
        column-gap: 1;
        padding: 0 0 1 0;
    }
    #form-panel, #prefs-panel {
        width: 80%;
        margin: 2 auto;
        border: solid $accent;
        padding: 1;
    }
    #message-log {
        height: 6;
    }
    #title {
        padding: 1 0;
        text-style: bold;
    }
    #login-form {
        width: 60%;
        margin: 2 auto;
        padding: 1;
        border: solid $accent;
    }
    """

    def __init__(self, demo: bool = False):
        super().__init__()
        self.client = TrytonTuiClient(demo=demo)

    def on_mount(self) -> None:
        self.push_screen(LoginScreen(self.client), callback=self._after_login)

    def _after_login(self, success: Optional[bool]) -> None:
        if success:
            self.push_screen(WorkspaceScreen(self.client))
        else:
            self.exit()


def run_app(demo: bool = False) -> None:
    app = TuionApp(demo=demo)
    app.run()
