# Tuion

Tuion is a text-based Tryton client inspired by the existing desktop client and Sao, but rendered fully in the terminal. It borrows layout ideas from [jiratui](https://github.com/whyisdifficult/jiratui) to keep navigation concise while still surfacing record details, menus, and context.

## Features

* Login flow that reuses Tryton's JSON-RPC endpoints to authenticate against any reachable server.
* Workspace that mirrors the common Tryton panels: a navigator for menus, a table for record lists, and a detail viewer for the current record.
* Multi-view browsing (list/kanban/calendar) with grouping and date fields so records can be visualized beyond a flat table.
* Full CRUD in the terminal with sortable lists, paging, and a search box that accepts either free text or multi-clause domains.
* Server actions, wizards, attachments, and reports selectable per model, plus user preferences (language, timezone, page size, and language translations) stored to disk between sessions in demo mode.
* Wizard flows and attachment management mirror the GTK client's dialogs with add/download/delete support.
* Offline-friendly caching of demo records and attachments so work can resume from the last session.
* Fallback demo mode so the interface can be explored without a server running.
* Configurable key bindings for fast keyboard-driven workflows.

## Running

From the repository root:

```bash
python -m pip install -e ./tuion
python -m tuion --demo
```

Once the app is running you can press <kbd>Ctrl+C</kbd> to quit or <kbd>?</kbd> inside the app to see the built-in help panel. To connect to a real server, launch without `--demo` and provide your host, port, database, username, and password on the login screen.

## Notes

Tuion targets feature parity with the desktop and web clients while remaining usable in constrained terminals. It reuses the same JSON-RPC calls as the other clients, so it should work with any modern Tryton deployment as long as the server allows API access. The interface honors language preferences and will translate field labels when translations are available.
