.. _topics-mcp:

============================
Model Context Protocol (MCP)
============================

``trytond`` exposes the Model Context Protocol (MCP) over HTTP on the
``/mcp`` route.  The service is available once the server is started and uses
the same authentication system as the JSON-RPC API.

Routes
======

Two URL shapes are accepted:

* ``/<database>/mcp`` – the database name is taken from the path.
* ``/mcp`` – the target database must be supplied via the
  ``X-Tryton-Database`` header.

Every request must provide valid Tryton credentials using either HTTP Basic
authentication or a ``session`` token, exactly like the JSON-RPC endpoints.  If
the request authenticates with a session token the session is automatically
refreshed after each successful tool invocation.

Available tools
===============

The server automatically exposes generic tools that work with every installed
model:

``tryton.list_models``
    Lists all models registered in the ``ir.model`` table.

``tryton.describe_model``
    Returns field metadata for a model.

``tryton.search``
    Executes ``Model.search`` with the provided domain.

``tryton.read``
    Reads the requested fields from the given record identifiers.

``tryton.create``
    Creates new records.

``tryton.write``
    Updates existing records.

``tryton.delete``
    Deletes records.

``tryton.call``
    Calls any method exported through the standard Tryton RPC machinery.  The
    helper transparently applies all RPC decorators, context handling and
    post-call tasks, so behaviour matches the JSON-RPC interface.

The tool results are serialised with the same rules as the JSON-RPC protocol.

Using MCP Inspector
===================

`MCP Inspector <https://github.com/modelcontextprotocol/inspector>`_ can be used
to explore the service locally.  A minimal configuration looks like::

    {
      "servers": [
        {
          "name": "Tryton",
          "transport": "streamable-http",
          "url": "http://localhost:8000/test/mcp",
          "headers": {
            "Authorization": "Basic <base64 username:password>",
            "X-Tryton-Database": "test"
          }
        }
      ]
    }

When the database is part of the path (``/test/mcp`` in the example above) the
``X-Tryton-Database`` header can be omitted.  The server advertises the
standard ``streamable-http`` transport and supports both JSON responses and
server sent events.  The tools listed above become immediately available to the
client and operate on whichever models are installed in the selected database.

