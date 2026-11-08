// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* MCP: the page an integrator lands on.
 *
 * The body is the repository's own `docs/MCP.md`, rendered here rather than
 * copied, so the guide in the app and the guide on GitHub cannot drift. The
 * header carries what is specific to *this* instance: its endpoint URL and the
 * tools it actually exposes.
 */

import { api } from "../api.js";
import { t } from "../i18n.js";
import { markdownToHtml } from "../markdown.js";
import { sanitizeHtml } from "../sanitize.js";
import { escapeHtml } from "../ui.js";

function _code(value) {
  return `<code class="docs-path">${escapeHtml(value)}</code>`;
}

function _snippet(endpoint) {
  return JSON.stringify(
    {
      mcpServers: {
        openlearn: {
          type: "http",
          url: endpoint,
          headers: { Authorization: "Bearer <your API key>" },
        },
      },
    },
    null,
    2,
  );
}

export async function renderMcpDocs() {
  const root = document.createElement("section");
  root.className = "page-narrow docs mcp-docs";
  root.innerHTML = `
    <header class="docs-head">
      <h1>${escapeHtml(t("docs.mcp_title"))}</h1>
      <p class="muted">${escapeHtml(t("docs.mcp_lede"))}</p>
    </header>
    <div class="mcp-summary card">
      <p><strong>${escapeHtml(t("docs.mcp_endpoint"))}</strong> <span id="mcp-endpoint">…</span></p>
      <p><strong>${escapeHtml(t("docs.mcp_tools"))}</strong> <span id="mcp-tools" class="muted">…</span></p>
      <p><strong>${escapeHtml(t("docs.mcp_auth"))}</strong> ${escapeHtml(t("docs.mcp_auth_body"))}</p>
    </div>
    <h2 class="mcp-h2">${escapeHtml(t("docs.mcp_client"))}</h2>
    <p class="muted">${escapeHtml(t("docs.mcp_client_body"))}</p>
    <pre class="docs-code" id="mcp-snippet"></pre>
    <div id="mcp-body" class="docs-body prose"><p class="muted">${escapeHtml(t("common.loading"))}</p></div>`;

  const endpointNode = root.querySelector("#mcp-endpoint");
  const toolsNode = root.querySelector("#mcp-tools");
  const snippet = root.querySelector("#mcp-snippet");
  const endpoint = `${window.location.origin}/mcp`;

  try {
    const descriptor = await api.get("/mcp");
    endpointNode.innerHTML = _code(descriptor.endpoint ? `${window.location.origin}${descriptor.endpoint}` : endpoint);
    toolsNode.textContent = (descriptor.tools || []).join(" · ") || "—";
    if (descriptor.transport) {
      toolsNode.textContent += ` — ${descriptor.transport}`;
    }
  } catch {
    // MCP disabled on this instance: say so instead of showing an empty list.
    endpointNode.innerHTML = _code(endpoint);
    toolsNode.textContent = "—";
  }
  snippet.textContent = _snippet(endpoint);

  const body = root.querySelector("#mcp-body");
  try {
    const response = await fetch("/docs/mcp.md", { credentials: "same-origin" });
    if (!response.ok) throw new Error(String(response.status));
    const markdown = await response.text();
    // The guide starts with its own title, which the page already shows.
    body.innerHTML = sanitizeHtml(markdownToHtml(markdown.replace(/^#\s+.*\n/, "")));
  } catch {
    body.innerHTML = `<p class="muted">${escapeHtml(t("docs.mcp_full"))} — ${_code(
      "docs/MCP.md",
    )}</p>`;
  }
  return root;
}
