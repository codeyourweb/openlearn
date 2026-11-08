// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/**
 * API reference.
 *
 * `/docs` used to answer with the SPA shell and render nothing: the strict CSP
 * (no `unsafe-inline`, no CDN) makes FastAPI's Swagger page unusable anyway.
 * This page reads `/openapi.json` and renders it with our own styles, so the
 * reference works offline and behind the same policy as the rest of the app.
 */

import { api } from "../api.js";
import { escapeHtml } from "../ui.js";
import { t } from "../i18n.js";

const METHOD_ORDER = ["get", "post", "put", "patch", "delete"];

function schemaType(schema) {
  if (!schema) return "—";
  if (schema.$ref) return String(schema.$ref).split("/").pop();
  if (schema.anyOf) {
    const parts = schema.anyOf.map((item) => schemaType(item)).filter((item) => item !== "—");
    return [...new Set(parts)].join(" | ") || "any";
  }
  if (schema.type === "array") return `${schemaType(schema.items)}[]`;
  if (schema.enum) return (schema.enum || []).map((value) => String(value)).join(" | ");
  return schema.type || "any";
}

function parametersTable(parameters) {
  if (!parameters || !parameters.length) return "";
  const rows = parameters
    .map(
      (parameter) => `
        <tr>
          <td><code>${escapeHtml(parameter.name)}</code></td>
          <td>${escapeHtml(parameter.in)}</td>
          <td>${escapeHtml(schemaType(parameter.schema))}</td>
          <td>${parameter.required ? `<span class="badge muted">${escapeHtml(t("docs.required"))}</span>` : ""}</td>
          <td>${escapeHtml(parameter.description || "")}</td>
        </tr>`,
    )
    .join("");
  return `
    <table class="docs-table">
      <thead><tr>
        <th>${escapeHtml(t("docs.param"))}</th>
        <th>${escapeHtml(t("docs.location"))}</th>
        <th>${escapeHtml(t("docs.type"))}</th>
        <th></th>
        <th>${escapeHtml(t("docs.description"))}</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function bodyBlock(operation, spec) {
  const body = operation.requestBody;
  if (!body) return "";
  const content = body.content || {};
  const mediaType = Object.keys(content)[0];
  if (!mediaType) return "";
  const schema = content[mediaType].schema || {};
  const name = schema.$ref ? String(schema.$ref).split("/").pop() : schemaType(schema);
  const definition = (spec.components && spec.components.schemas && spec.components.schemas[name]) || null;
  const fields = definition && definition.properties ? Object.entries(definition.properties) : [];
  const required = new Set((definition && definition.required) || []);
  const rows = fields
    .map(
      ([field, value]) => `
        <tr>
          <td><code>${escapeHtml(field)}</code>${required.has(field) ? " *" : ""}</td>
          <td>${escapeHtml(schemaType(value))}</td>
          <td>${escapeHtml(value.description || "")}</td>
        </tr>`,
    )
    .join("");
  return `
    <div class="docs-block">
      <h4>${escapeHtml(t("docs.body"))} <span class="muted">${escapeHtml(name)}</span></h4>
      ${rows ? `<table class="docs-table"><tbody>${rows}</tbody></table>` : `<p class="muted">${escapeHtml(name)}</p>`}
    </div>`;
}

function responsesBlock(operation) {
  const responses = operation.responses || {};
  const rows = Object.entries(responses)
    .map(
      ([code, value]) => `
        <tr>
          <td><code>${escapeHtml(code)}</code></td>
          <td>${escapeHtml(value.description || "")}</td>
        </tr>`,
    )
    .join("");
  if (!rows) return "";
  return `
    <div class="docs-block">
      <h4>${escapeHtml(t("docs.responses"))}</h4>
      <table class="docs-table"><tbody>${rows}</tbody></table>
    </div>`;
}

export function renderDocs() {
  // Pages receive no container: build the fragment here and return it.
  const root = document.createElement("div");
  root.innerHTML = `
    <section class="page-narrow docs">
      <header class="docs-head">
        <h1>${escapeHtml(t("docs.title"))}</h1>
        <p class="muted">${escapeHtml(t("docs.lede"))}</p>
        <input id="docs-filter" class="input" type="search" placeholder="${escapeHtml(t("docs.filter"))}" />
      </header>
      <div id="docs-body" class="docs-body"><p class="muted">${escapeHtml(t("common.loading"))}</p></div>
    </section>`;

  const body = root.querySelector("#docs-body");
  const filter = root.querySelector("#docs-filter");

  const paint = (spec) => {
    const groups = new Map();
    for (const [path, operations] of Object.entries(spec.paths || {})) {
      for (const method of METHOD_ORDER) {
        const operation = operations[method];
        if (!operation) continue;
        const group = (operation.tags && operation.tags[0]) || t("docs.other");
        if (!groups.has(group)) groups.set(group, []);
        groups.get(group).push({ path, method, operation, parameters: operations.parameters || [] });
      }
    }

    const sections = [...groups.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([group, entries]) => {
        const items = entries
          .map(({ path, method, operation, parameters }) => {
            const allParams = [...(parameters || []), ...(operation.parameters || [])];
            return `
              <article class="docs-op" data-search="${escapeHtml(`${method} ${path} ${operation.summary || ""}`.toLowerCase())}">
                <header class="docs-op-head">
                  <span class="docs-method is-${method}">${method.toUpperCase()}</span>
                  <code class="docs-path">${escapeHtml(path)}</code>
                </header>
                <p class="docs-summary">${escapeHtml(operation.summary || "")}</p>
                ${operation.description ? `<p class="muted small">${escapeHtml(operation.description)}</p>` : ""}
                ${parametersTable(allParams)}
                ${bodyBlock(operation, spec)}
                ${responsesBlock(operation)}
              </article>`;
          })
          .join("");
        return `<section class="docs-group"><h2>${escapeHtml(group)}</h2>${items}</section>`;
      })
      .join("");

    body.innerHTML = sections || `<p class="muted">${escapeHtml(t("docs.empty"))}</p>`;

    // "No match" state: an empty page reads as a broken page.
    const noMatch = document.createElement("p");
    noMatch.className = "muted docs-no-match";
    noMatch.hidden = true;
    noMatch.textContent = t("docs.no_match");
    body.appendChild(noMatch);

    if (filter) {
      const applyFilter = () => {
        const needle = filter.value.trim().toLowerCase();
        let shown = 0;
        body.querySelectorAll(".docs-op").forEach((node) => {
          const match = !needle || node.dataset.search.includes(needle);
          node.hidden = !match;
          if (match) shown += 1;
        });
        body.querySelectorAll(".docs-group").forEach((group) => {
          const visible = [...group.querySelectorAll(".docs-op")].some((node) => !node.hidden);
          group.hidden = !visible;
        });
        noMatch.hidden = shown > 0;
        noMatch.textContent = shown ? "" : t("docs.no_match", { query: filter.value.trim() });
      };
      filter.addEventListener("input", applyFilter);
    }
  };

  api
    .get("/api/openapi.json")
    .then(paint)
    .catch((error) => {
      body.innerHTML = `<p class="error">${escapeHtml(error.detail || t("docs.failed"))}</p>`;
    });

  return root;
}
