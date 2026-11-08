# axe-core (vendored)

`axe.min.js` is axe-core **4.10.2**, unmodified, from
<https://github.com/dequelabs/axe-core>. It is published by Deque Systems under
the Mozilla Public License 2.0 (<https://www.mozilla.org/en-US/MPL/2.0/>); the
header inside the file carries the same terms.

It sits in the repository for one reason: a build that cannot reach the internet
must still be able to audit its own pages, and the version that judged a release
must be the version a reader can check. Loading it from a CDN would make both
false.

It is **test-only**. No page served by the application loads it; it is injected
by `tests/test_accessibility.py` into a throwaway browser context, which is also
why that context sets `bypass_csp` — the product's own `script-src 'self'` is
correct and is not loosened to accommodate a probe.
