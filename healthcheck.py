# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 OpenLearn
"""Container health probe: HTTP on 8000, or HTTPS on the TLS port.

The same image serves both shapes, so the probe cannot hardcode a scheme.
"""

from __future__ import annotations

import os
import ssl
import sys
import urllib.request

tls = bool(os.environ.get("OL_TLS_CERT_FILE"))
port = os.environ.get("OL_TLS_PORT", "8443") if tls else os.environ.get("PORT", "8000")
scheme = "https" if tls else "http"
context = ssl._create_unverified_context() if tls else None  # self-signed is fine locally
url = f"{scheme}://127.0.0.1:{port}/api/v1/health"

try:
    with urllib.request.urlopen(url, timeout=4, context=context) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:  # noqa: BLE001 - any failure means "not healthy"
    sys.exit(1)
