"""Demo data for Tuion when no server is available."""

DEMO_MODULES = [
    {"name": "Sales", "state": "installed", "summary": "Quotes, orders, and invoices"},
    {"name": "Stock", "state": "installed", "summary": "Inventory moves and locations"},
    {"name": "Projects", "state": "installed", "summary": "Tasks, work logs, and effort"},
    {"name": "Parties", "state": "installed", "summary": "Contacts and addresses"},
]

DEMO_MENUS = [
    {"path": "Sales > Customers", "model": "party.party", "count": 12},
    {"path": "Sales > Quotations", "model": "sale.quotation", "count": 4},
    {"path": "Projects > Work Logs", "model": "project.work", "count": 22},
    {"path": "Stock > Moves", "model": "stock.move", "count": 18},
]

DEMO_RECORDS = {
    "party.party": [
        {"id": 1, "name": "Example Customer", "city": "Helsinki", "country": "FI", "active": True},
        {"id": 2, "name": "Blue Steel", "city": "Lyon", "country": "FR", "active": False},
    ],
    "sale.quotation": [
        {
            "id": 1,
            "number": "QUO-0001",
            "party": "Example Customer",
            "total": 1234.50,
            "state": "draft",
            "quote_date": "2024-05-01",
            "expiry_date": "2024-06-01",
        },
        {
            "id": 2,
            "number": "QUO-0002",
            "party": "Blue Steel",
            "total": 845.20,
            "state": "confirmed",
            "quote_date": "2024-04-20",
            "expiry_date": "2024-05-20",
        },
    ],
    "project.work": [
        {
            "id": 1,
            "name": "Draft architecture",
            "hours": 12.5,
            "project": "New HQ",
            "billable": True,
            "start": "2024-04-28",
            "end": "2024-05-02",
        },
        {
            "id": 2,
            "name": "Implement API",
            "hours": 8.0,
            "project": "Mobile app",
            "billable": False,
            "start": "2024-05-05",
            "end": "2024-05-08",
        },
    ],
    "stock.move": [
        {
            "id": 1,
            "name": "WH/IN/00012",
            "from": "Vendor",
            "to": "Input",
            "quantity": 20,
            "done": False,
            "date": "2024-04-30",
        },
    ],
}

# Attachments are keyed by model and record id to mimic the attachment tab in GTK.
DEMO_ATTACHMENTS = {
    "party.party": {
        1: [
            {"id": 1, "name": "contract.pdf", "content": "Signed contract for Example Customer"},
            {"id": 2, "name": "notes.txt", "content": "Customer prefers email contact."},
        ],
    },
    "sale.quotation": {
        1: [
            {"id": 3, "name": "quote.pdf", "content": "PDF rendering placeholder"},
        ],
    },
}

DEMO_FIELDS = {
    "party.party": {
        "name": {"string": "Name", "type": "char"},
        "city": {"string": "City", "type": "char"},
        "country": {"string": "Country", "type": "selection", "selection": ["FI", "FR", "DE"]},
        "active": {"string": "Active", "type": "boolean"},
    },
    "sale.quotation": {
        "number": {"string": "Number", "type": "char"},
        "party": {"string": "Party", "type": "char"},
        "total": {"string": "Total", "type": "float"},
        "state": {"string": "State", "type": "selection", "selection": ["draft", "confirmed", "done"]},
        "quote_date": {"string": "Quote Date", "type": "date"},
        "expiry_date": {"string": "Expiry", "type": "date"},
    },
    "project.work": {
        "name": {"string": "Name", "type": "char"},
        "hours": {"string": "Hours", "type": "float"},
        "project": {"string": "Project", "type": "char"},
        "billable": {"string": "Billable", "type": "boolean"},
        "start": {"string": "Start", "type": "date"},
        "end": {"string": "End", "type": "date"},
    },
    "stock.move": {
        "name": {"string": "Name", "type": "char"},
        "from": {"string": "From", "type": "char"},
        "to": {"string": "To", "type": "char"},
        "quantity": {"string": "Quantity", "type": "float"},
        "done": {"string": "Done", "type": "boolean"},
        "date": {"string": "Date", "type": "date"},
    },
}

DEMO_ACTIONS = {
    "party.party": ["Export Cards", "Send Email"],
    "sale.quotation": ["Confirm", "Print"],
    "project.work": ["Start Timer", "Stop Timer"],
    "stock.move": ["Assign", "Done"],
}

DEMO_REPORTS = {
    "party.party": ["Address Labels"],
    "sale.quotation": ["Quotation PDF"],
    "project.work": ["Timesheet"],
    "stock.move": ["Picking List"],
}

# Wizard flows approximate multi-step dialogs in GTK.
DEMO_WIZARDS = {
    "sale.quotation": {
        "Confirm with note": [
            {"note": {"string": "Confirmation note", "type": "char"}},
        ],
        "Duplicate": [
            {"number": {"string": "New Number", "type": "char"}},
            {"copy_lines": {"string": "Copy Lines", "type": "boolean"}},
        ],
    },
    "stock.move": {
        "Force Done": [
            {"reason": {"string": "Reason", "type": "char"}},
        ],
    },
}

# Basic translations to mirror GTK's localization controls.
DEMO_TRANSLATIONS = {
    "es": {
        "Name": "Nombre",
        "City": "Ciudad",
        "Country": "País",
        "Active": "Activo",
        "Number": "Número",
        "Party": "Cliente",
        "Total": "Total",
        "State": "Estado",
        "Quote Date": "Fecha de presupuesto",
        "Expiry": "Caducidad",
        "Start": "Inicio",
        "End": "Fin",
        "Billable": "Facturable",
        "Quantity": "Cantidad",
        "From": "Desde",
        "To": "Hasta",
        "Date": "Fecha",
        "Attachments": "Adjuntos",
        "Wizards": "Asistentes",
        "Actions": "Acciones",
        "Reports": "Informes",
        "Preferences": "Preferencias",
    }
}
