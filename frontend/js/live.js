// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 OpenLearn
/* WebSocket client for live sessions: reconnects with backoff, keeps a ping. */

export class LiveConnection {
  constructor(code, token, { onState, onFinished, onStatus } = {}) {
    this.code = String(code).toUpperCase();
    this.token = token || "";
    this.onState = onState || (() => {});
    this.onFinished = onFinished || (() => {});
    this.onStatus = onStatus || (() => {});
    this.socket = null;
    this.attempt = 0;
    this.closedByUser = false;
    this.pingTimer = null;
  }

  connect() {
    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const url = `${scheme}://${location.host}/api/v1/sessions/${this.code}/ws?token=${encodeURIComponent(this.token)}`;
    this.onStatus("connecting");
    try {
      this.socket = new WebSocket(url);
    } catch {
      this.onStatus("offline");
      this.scheduleReconnect();
      return;
    }
    this.socket.addEventListener("open", () => {
      this.attempt = 0;
      this.onStatus("online");
      this.startPing();
    });
    this.socket.addEventListener("message", (event) => {
      let message;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      if (message.type === "state" && message.state) this.onState(message.state);
      if (message.type === "finished" && message.state) {
        this.onState(message.state);
        this.onFinished(message.state);
      }
    });
    this.socket.addEventListener("close", () => {
      this.stopPing();
      if (this.closedByUser) return;
      this.onStatus("offline");
      this.scheduleReconnect();
    });
    this.socket.addEventListener("error", () => {
      this.onStatus("offline");
    });
  }

  startPing() {
    this.stopPing();
    this.pingTimer = setInterval(() => {
      if (this.socket && this.socket.readyState === WebSocket.OPEN) this.socket.send("ping");
    }, 20000);
  }

  stopPing() {
    if (this.pingTimer) clearInterval(this.pingTimer);
    this.pingTimer = null;
  }

  scheduleReconnect() {
    this.attempt += 1;
    if (this.attempt > 8) return;
    const delay = Math.min(15000, 500 * 2 ** this.attempt);
    setTimeout(() => {
      if (!this.closedByUser) this.connect();
    }, delay);
  }

  close() {
    this.closedByUser = true;
    this.stopPing();
    if (this.socket) this.socket.close();
  }
}

export function websocketToken(code, { preferHost = false } = {}) {
  return preferHost
    ? localStorage.getItem(`ol_ht_${code}`) || localStorage.getItem(`ol_pt_${code}`) || ""
    : localStorage.getItem(`ol_pt_${code}`) || localStorage.getItem(`ol_ht_${code}`) || "";
}
