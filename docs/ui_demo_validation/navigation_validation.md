# Browser navigation validation — 2026-09-13

## Outcome

PASS: Chromium at 375, 768, 1024 and 1440 pixels, each with compact idle,
full idle and full result screenshots. See [machine summary](navigation/summary.json).
Screenshots use **mocked empty sensors and a synthetic terminal-result fixture**;
they are not hardware measurements or evidence of chemical accuracy.

- Full/compact links preserve origin, pathname, backend/query values, duplicate
  unrelated parameters and hash. Explicit view survives reload.
- Initial full phone and desktop compact-to-full return retain server-settings
  ownership. Layout selection does not grant notebook settings-write authority.
  `remote_control=1` carries the remote role through navigation.
- Remote full view hides notebook configuration forms and allows the result tab.
- No horizontal overflow; compact STOP stays within the initial viewport.
- Missing temperature stays `-`; result fixture renders 9.820 mL and 0.09800 M.
- No runtime errors; no remote-config, pump, CSV or ROI writes from navigation.
  Read-only chemistry lookup POSTs are allowed. All requests are intercepted and
  fulfilled locally; EventSource is stubbed. No collector or hardware is contacted.
- Preview error/load/error events preserve the stream-state attribute contract.

## Reproduce

Playwright is validation-only tooling installed outside the product. From repo root:

```sh
PLAYWRIGHT_MODULE=/tmp/ui-demo-browser/node_modules/playwright \
OUTPUT=/tmp/ui-navigation-proof \
node docs/ui_demo_validation/verify_navigation.cjs

for file in tests/js/test_*.js; do node "$file" || exit; done
python3 -m unittest tests.test_view_navigation -v
node --check website/app.js
node --check docs/ui_demo_validation/verify_navigation.cjs
git diff --check
```

`VISUAL_ROOT` and `NAV_ROOT` optionally select website directories for isolated
Team integration. This evidence used worker-2 presentation files and worker-1 JS.
The integrated leader tree was rerun successfully on 2026-09-13 at 10:56 UTC: all four browser widths, ten Node suites and fifteen combined website/navigation unittests passed. No hardware traffic was permitted.

## Verification and bounded cleanup

- PASS: ten Node suites, including full remote saved-settings/STOP preemption.
- PASS: two navigation unittest cases; JavaScript syntax and diff whitespace checks.
- Typecheck/linter: N/A, no configured typed JS or lint toolchain; syntax checks do
  not substitute for a typecheck. No dependencies added to the product.
- Cleanup scope: changed navigation/authority helper and tests only. Behavior was
  locked with a failing full-phone ownership regression before the role fix.
  Plan: inspect fallback boundaries, dead code and duplication, then strengthen
  missing tests. No redundant abstraction or masking fallback was introduced.
  The optional DOM-anchor guard is retained for missing/native presentation
  surfaces and explicitly tested. Native bridge remains excluded from both roles.
- Preview changes reuse existing event handlers (four dataset assignments).
- Writer implementation/cleanup pass complete; independent review remains with
  the Team leader's separate reviewer lane. No native Android/backend changes.

## Screenshot set

Each width has `*-compact-idle.png`, `*-full-idle.png`, and
`*-full-result-fixture.png` in [navigation/](navigation/).
