// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Thin fetch wrapper: CSRF header, JSON handling, typed errors. */

const CSRF_COOKIE = "ol_csrf";

export class ApiError extends Error {
  constructor(status, detail, payload) {
    super(detail || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.payload = payload;
  }
}

export function readCookie(name) {
  const target = `${name}=`;
  for (const part of document.cookie.split(";")) {
    const value = part.trim();
    if (value.startsWith(target)) return decodeURIComponent(value.slice(target.length));
  }
  return "";
}

function buildHeaders(extra = {}) {
  const headers = { Accept: "application/json", ...extra };
  const csrf = readCookie(CSRF_COOKIE);
  if (csrf) headers["X-CSRF-Token"] = csrf;
  return headers;
}

async function request(method, path, { body, headers = {}, raw = false, withHeaders = false } = {}) {
  const options = { method, credentials: "same-origin", headers: buildHeaders(headers) };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(path, options);
  } catch {
    throw new ApiError(0, "Network error: the server is unreachable.");
  }
  if (response.status === 204) return null;
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = raw ? text : null;
    }
  }
  if (!response.ok) {
    let detail = payload && payload.detail;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || item.detail || "Invalid value").join("; ");
    }
    throw new ApiError(response.status, detail || response.statusText, payload);
  }
  // Callers that paginate need ``X-Total-Count`` from the same response.
  return withHeaders ? { data: payload, headers: response.headers } : payload;
}

export const api = {
  get: (path, opts) => request("GET", path, opts),
  post: (path, body, opts) => request("POST", path, { ...opts, body }),
  put: (path, body, opts) => request("PUT", path, { ...opts, body }),
  patch: (path, body, opts) => request("PATCH", path, { ...opts, body }),
  del: (path, opts) => request("DELETE", path, opts),
  /** GET that also returns the response headers (pagination totals). */
  getMeta: (path, opts) => request("GET", path, { ...opts, withHeaders: true }),
  request,
};

/**
 * Upload a question image.
 *
 * ``fetch`` cannot report upload progress, so this uses XHR: the editors show a
 * determinate bar while a phone sends a photo over a slow link. ``onProgress``
 * receives a 0..1 ratio.
 */
export function uploadImage(file, onProgress, endpoint = "/api/v1/uploads/question-image") {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", endpoint);
    xhr.withCredentials = true;
    for (const [name, value] of Object.entries(buildHeaders())) {
      if (name.toLowerCase() !== "content-type") xhr.setRequestHeader(name, value);
    }
    xhr.upload.addEventListener("progress", (event) => {
      if (onProgress && event.lengthComputable && event.total > 0) {
        onProgress(Math.min(1, event.loaded / event.total));
      }
    });
    xhr.addEventListener("load", () => {
      let payload = null;
      try {
        payload = JSON.parse(xhr.responseText);
      } catch {
        payload = null;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(1);
        resolve(payload);
        return;
      }
      reject(new ApiError(xhr.status, (payload && payload.detail) || "Upload failed", payload));
    });
    xhr.addEventListener("error", () => reject(new ApiError(0, "Network error: the upload failed.")));
    xhr.addEventListener("abort", () => reject(new ApiError(0, "Upload cancelled.")));
    xhr.send(form);
  });
}

/**
 * Fire-and-forget request that survives the page going away.
 *
 * Used by the editors to flush an autosave when the tab is closed or the user
 * navigates away: ``keepalive`` lets the browser finish the request even after
 * the document is unloaded.
 */
export function keepaliveRequest(method, path, body) {
  try {
    return fetch(path, {
      method,
      credentials: "same-origin",
      keepalive: true,
      headers: buildHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    return Promise.resolve(null);
  }
}

export async function ensureCsrf() {
  if (readCookie(CSRF_COOKIE)) return;
  try {
    await api.get("/api/v1/auth/csrf");
  } catch {
    /* anonymous browsing still works without a CSRF token */
  }
}
