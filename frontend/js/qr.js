// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* A QR code for a URL, drawn as one SVG path.

   The host shows this in the lobby so a room full of students can join by
   scanning instead of copying a PIN off a projector. The encoder is vendored
   (see `vendor/README.md`): we render the module matrix ourselves rather than
   use its `createSvgTag`, so the result is a single path that stays sharp at
   any size, with a white background that scanners can find on a dark theme.
*/

import qrcode from "./vendor/qrcode.mjs";

// Error correction M tolerates a dirty or partly hidden code without inflating
// the matrix; 4 modules of quiet zone is the margin the specification asks for.
const QUIET_ZONE = 4;

export function qrPayload(text) {
  const value = String(text || "").trim();
  if (!value) return null;
  const code = qrcode(0, "M");
  code.addData(value, "Byte");
  code.make();
  return code;
}

export function qrSvg(text, { label = "" } = {}) {
  const code = qrPayload(text);
  if (!code) return "";
  const count = code.getModuleCount();
  const total = count + QUIET_ZONE * 2;
  let path = "";
  for (let row = 0; row < count; row += 1) {
    for (let column = 0; column < count; column += 1) {
      if (code.isDark(row, column)) {
        path += `M${column + QUIET_ZONE} ${row + QUIET_ZONE}h1v1h-1z`;
      }
    }
  }
  const described = label ? ` role="img" aria-label="${escapeAttr(label)}"` : ' role="img" aria-hidden="true"';
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${total}" ` +
    `width="100%" height="100%" shape-rendering="crispEdges" focusable="false"${described}>` +
    `<rect width="${total}" height="${total}" fill="#ffffff"/>` +
    `<path d="${path}" fill="#000000"/>` +
    "</svg>"
  );
}

function escapeAttr(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
