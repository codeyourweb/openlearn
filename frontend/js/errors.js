// SPDX-License-Identifier: AGPL-3.0-only
// Copyright (C) 2026 Jean-Pierre GARNIER (@codeyourweb)
/* Turning a failed request into a sentence the visitor can act on.

   The API answers in English, which is right for a documented endpoint and
   wrong in a French toast. A 429 is the one case where the server knows
   something the interface must repeat — how long to wait — so it is told in the
   reader's language and with the delay the Retry-After header carried. */

import { t } from "./i18n.js";

export function explainError(error, fallback = "") {
  if (!error) return fallback;
  if (error.status === 429) {
    const seconds = Math.max(0, Number(error.retryAfter) || 0);
    if (seconds >= 90) return t("error.rate_limited_minutes", { n: Math.ceil(seconds / 60) });
    if (seconds > 0) return t("error.rate_limited_wait", { n: seconds });
    return t("error.rate_limited");
  }
  return error.detail || fallback;
}
