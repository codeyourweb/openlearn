# MCP server

OpenLearn exposes a [Model Context Protocol](https://modelcontextprotocol.io)
endpoint so an external agent (Claude Desktop, VS Code, Cursor, a custom
LangGraph worker…) can read the shared knowledge base: wikis, pages, search and
public quizzes. The server is **read-only on purpose** — an agent that could
edit a wiki would need a much stronger consent model than a bearer token, so
writes stay in the web interface and the REST API.

- Endpoint: `POST /mcp` (and `GET /mcp` for a human-readable description)
- Transport: streamable HTTP, JSON-RPC 2.0, no SSE
- Protocol version: `2024-11-05`
- Default state: enabled, authentication **required**

## Enable and configure

| Variable | Default | Meaning |
| --- | --- | --- |
| `OL_MCP_ENABLED` | `true` | Mount the endpoint at all. `false` returns 404. |
| `OL_MCP_REQUIRE_AUTH` | `true` | Reject anonymous calls; a token is then needed. |
| `OL_MCP_RATE_LIMIT` | `120` | Requests allowed per window, per client IP. |
| `OL_MCP_RATE_WINDOW_SECONDS` | `60` | Window length. |

A public demo instance usually keeps `OL_MCP_REQUIRE_AUTH=true` as well: the
tokens let you watch who reads what, and a leaked token can be revoked.

## Authenticate

Any of the three credentials the REST API accepts works here:

```http
Authorization: Bearer <personal API key or JWT>
X-API-Key: <personal API key>
```

A personal API key is created in **Account → API keys**. Anonymous calls are
accepted only when `OL_MCP_REQUIRE_AUTH=false`, and then they see public
content exclusively — exactly what a signed-out visitor sees.

## Tools

| Tool | Arguments | Returns |
| --- | --- | --- |
| `openlearn_instance_info` | — | Name, version, languages, demo flag, enabled features. |
| `openlearn_list_wikis` | `query?`, `language?`, `limit?` | Public wikis, with page counts. |
| `openlearn_get_wiki` | `slug` or `id` | Wiki metadata and its page tree. |
| `openlearn_search_pages` | `query`, `wiki?`, `limit?` | Pages matching the query, with excerpts. |
| `openlearn_get_page` | `page_id` or `wiki` + `slug` | Full markdown of a page, plus its revision id. |
| `openlearn_list_quizzes` | `query?`, `language?`, `limit?` | Published quizzes: title, language, question count. |
| `openlearn_get_quiz` | `quiz_id` | Questions and answers. Correct answers are included only when the caller owns the quiz. |

Drafts and private resources are visible to their owner (the token's user) and
to administrators, never to anyone else.

## Wiring a client

Claude Desktop (`claude_desktop_config.json`) and most MCP clients accept a
streamable-HTTP server with a header:

```json
{
  "mcpServers": {
    "openlearn": {
      "type": "http",
      "url": "https://learn.example.org/mcp",
      "headers": { "Authorization": "Bearer ol_xxxxxxxxxxxxxxxx" }
    }
  }
}
```

VS Code (`.vscode/mcp.json`):

```json
{
  "servers": {
    "openlearn": {
      "type": "http",
      "url": "https://learn.example.org/mcp",
      "headers": { "Authorization": "Bearer ol_xxxxxxxxxxxxxxxx" }
    }
  }
}
```

A client that only speaks stdio can bridge to the endpoint with
[`mcp-remote`](https://www.npmjs.com/package/mcp-remote):

```bash
npx -y mcp-remote https://learn.example.org/mcp \
  --header "Authorization: Bearer ol_xxxxxxxxxxxxxxxx"
```

## Trying it by hand

```bash
curl -s https://learn.example.org/mcp \
  -H "Authorization: Bearer $OPENLEARN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize",
       "params":{"protocolVersion":"2024-11-05","capabilities":{},
                 "clientInfo":{"name":"curl","version":"1"}}}'
```

Then list the tools and call one:

```bash
curl -s https://learn.example.org/mcp -H "Authorization: Bearer $OPENLEARN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

curl -s https://learn.example.org/mcp -H "Authorization: Bearer $OPENLEARN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call",
       "params":{"name":"openlearn_search_pages","arguments":{"query":"photosynthesis"}}}'
```

## Errors

JSON-RPC errors are returned with HTTP 200 and an `error` object, as the
protocol requires: `-32700` parse error, `-32600` invalid request, `-32601`
unknown method, `-32602` invalid arguments, `-32603` internal error. HTTP status
codes are reserved for transport-level problems: `401` when a token is required
or rejected, `404` when MCP is disabled, `429` with `Retry-After` on rate
limiting.

## Design notes

- **Read-only.** No tool mutates anything, so a compromised token cannot
  vandalise the wiki; it can only read what it is already allowed to read.
- **The same visibility rules as the web.** Tools reuse the API's permission
  checks instead of reimplementing them, so a private wiki stays private.
- **Search degrades gracefully.** Full-text search uses SQLite FTS5; on
  PostgreSQL and MySQL the server falls back to `LIKE`. The answer is coarser
  but never absent.
