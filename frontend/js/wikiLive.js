// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Live co-editing client for one wiki page: one socket, one revision.

   The browser never decides what the document is: it sends the text it holds
   with the revision it started from, and the server answers with one splice
   that everybody applies in the same order. This file keeps the server
   revision, the other editors' carets and the queued typing in sync, so two
   keystrokes never travel with the same base revision. */

const RETRY_DELAYS = [800, 1600, 3200, 6400];

export function connectLive(pageId, handlers = {}) {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${protocol}//${location.host}/api/v1/wiki/pages/${pageId}/live`;

  const client = {
    rev: 0,
    content: "",
    me: null,
    users: [],
    connected: false,
    closed: false,
    socket: null,
    pending: null, // text waiting for the previous op to be acknowledged
    retry: 0,
    sendText(text) {
      client.pending = text;
      flush();
    },
    sendCursor(anchor, head) {
      if (!client.connected) return;
      client.socket.send(JSON.stringify({ type: "cursor", anchor, head }));
    },
    close() {
      client.closed = true;
      if (client.socket) client.socket.close();
    },
  };

  function flush() {
    if (!client.connected || client.pending === null) return;
    const text = client.pending;
    client.pending = null;
    client.socket.send(JSON.stringify({ type: "op", rev: client.rev, text }));
  }

  function open() {
    const socket = new WebSocket(url);
    client.socket = socket;

    socket.addEventListener("open", () => {
      client.retry = 0;
    });

    socket.addEventListener("message", (event) => {
      let message = null;
      try {
        message = JSON.parse(event.data);
      } catch {
        return;
      }
      switch (message.type) {
        case "hello":
          client.connected = true;
          client.rev = message.rev;
          client.content = message.content;
          client.me = message.me;
          client.users = message.users || [];
          handlers.onHello?.(message);
          // Typing that happened before the socket came up is still valid.
          flush();
          break;
        case "presence":
          client.users = message.users || [];
          handlers.onPresence?.(client.users);
          break;
        case "op":
          client.rev = message.rev;
          handlers.onOp?.({
            rev: message.rev,
            pos: message.pos,
            delete: message.delete,
            insert: message.insert,
            clientId: message.client_id,
            userId: message.user_id,
            name: message.name,
            color: message.color,
            isMine: Boolean(client.me && message.client_id === client.me.client_id),
            conflict: Boolean(message.conflict),
          });
          flush();
          break;
        case "reset":
          client.rev = message.rev;
          client.content = message.content;
          handlers.onReset?.(message);
          break;
        case "resync":
          client.rev = message.rev;
          client.content = message.content;
          handlers.onResync?.(message);
          break;
        case "cursor":
          if (client.me && message.client_id === client.me.client_id) break;
          handlers.onCursor?.(message);
          break;
        case "denied":
          handlers.onDenied?.(message);
          break;
        default:
          break;
      }
    });

    socket.addEventListener("close", () => {
      client.connected = false;
      handlers.onStatus?.("offline");
      if (client.closed) return;
      const delay = RETRY_DELAYS[Math.min(client.retry, RETRY_DELAYS.length - 1)];
      client.retry += 1;
      window.setTimeout(() => {
        if (!client.closed) open();
      }, delay);
    });

    socket.addEventListener("error", () => {
      handlers.onStatus?.("offline");
    });
  }

  open();
  return client;
}

/** Apply a server splice to a text, exactly as every other screen does. */
export function applySplice(text, pos, remove, insert) {
  return text.slice(0, pos) + insert + text.slice(pos + remove);
}

/** People currently editing, minus me. */
export function otherEditors(users, me) {
  if (!me) return users || [];
  return (users || []).filter((user) => user.client_id !== me.client_id);
}

export function initials(name) {
  const words = String(name || "?")
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[words.length - 1][0]).toUpperCase();
}
