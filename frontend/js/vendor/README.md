# Vendored code

Everything here is third-party, kept verbatim, and served from our own origin:
the content security policy allows `script-src 'self'` and nothing else, so a
CDN copy is not an option.

## `qrcode.mjs`

- **Project**: [QR Code Generator for JavaScript](https://github.com/kazuhikoarase/qrcode-generator)
- **Author**: Kazuhiko Arase
- **Version**: `js/dist/qrcode.mjs`, commit `83b7e8fe3fddd3b0368dbafd6ce56995bd25e3c8`
- **Licence**: MIT (header kept at the top of the file)
- **Why**: a host shows a join link on a projector; students scan it instead of
  typing a PIN. The library is pure computation — no network, no eval — and the
  matrix it produces is turned into one `<path>` by `frontend/js/qr.js`, so the
  code stays sharp at any size.

Unmodified. To update: replace the file, keep the licence header, and run the
QR tests in `tests/test_frontend_qr.py`.
