# Design

## Source of truth
- **Status:** Active · 2026-09-13
- **Surfaces:** Windows/laptop browser console and phone compact remote.
- **Evidence:** `website/index.html`, `website/styles.css`, `website/app.js`, `website/demo-view.js`, and `tests/test_website_assets.py`.
- This instrument-specific contract replaces the previous generic Apple marketing-page analysis. It preserves its white/charcoal/Action Blue palette, quiet chrome, and restraint, while using the repository's local Pretendard font and real experiment controls.

## Brand
Precise, calm, and legible: an instrument console, not a landing page. Trust comes from real readings, explicit units, visible connection status, and an unmistakable pump STOP. Avoid marketing heroes, decorative gradients, invented charts, simulated measurements, and ornamental motion.

## Product goals
- Make camera observation, injected volume, elapsed time, and pump state easy to scan.
- Keep full and compact views reversible without losing connection parameters.
- Let the operator stop from compact view without scrolling.
- Non-goals: new pump semantics, native Android changes, backend changes, or inferred chemistry readings.
- Success: two camera panels side by side on laptops; no horizontal overflow at 375/768/1024/1440px; permanent view links; clear loading and missing-data states.

## Personas and jobs
- Laptop operator: prepare settings/ROI, observe both cameras, record a session, inspect results.
- Phone operator: use the configured remote connection to monitor and send existing recording/pump commands. Settings remain server-owned; the phone is not a second control implementation.

## Information architecture
- Permanent header: instrument name and `viewFullLink` / `viewCompactLink`.
- Full view: controls and collapsible settings → prominent live readings → dual camera panels; result mode exposes existing final readings and trends.
- Compact view: header → live readings → essential controls and connection state. Pump STOP remains fixed at the bottom.
- Preserve every existing DOM ID and existing recording/result visibility behavior.
- Navigation changes presentation only. JavaScript preserves other URL parameters/hash and excludes native Android navigation.

## Design principles
1. Data before decoration: use large tabular numerals with explicit units.
2. Separate reading from editing: charcoal readout, white control surfaces.
3. One primary action: blue recording start; pump STOP uses safety red.
4. Progressive disclosure: settings, ROI detail, and diagnostics stay available without dominating the initial view.
5. Never imply disconnection stops the pump; retain the explicit remote warning.

## Visual language
- Canvas `#f5f5f7`; cards white; ink/readout `#1d1d1f`; divider `#e2e2e7`.
- Action Blue `#0066cc`; STOP/error `#b42318`. Green/amber remain semantic states, not decorative accents.
- Local `assets/fonts/PretendardVariable.woff2`, system/Korean fallbacks, font-display swap.
- Headings approximately 24–30px; live numeric readings 35–56px desktop / 40–43px compact; supporting text 12–16px.
- Major spacing 16–24px; compact gaps 6–12px. White cards use hairline borders, readout 18px radius, operational buttons 10px, navigation 12px.
- Avoid decorative shadows; fixed STOP uses an opaque canvas-colored separation ring. Preserve functional ROI overlays and notice elevation.
- Keep camera pixels uncropped with `object-fit: contain`; no fabricated preview images.
- Motion: short color/focus transitions only; honor reduced motion.

## Components
- **View navigation:** two semantic anchors, always outside drawers and mode-hidden controls; selected styling follows remote body class and accessible current state is set by navigation logic.
- **Live stage:** state label, status note, injected volume, elapsed time; no fabricated zeros for unavailable measurements.
- **Control panel:** existing buttons and forms; blue recording start, separate recording end and pump STOP.
- **Sensor cards:** numbered camera headers, equal-width previews, unchanged ROI interactions and thermal rotate control.
- **Results:** existing final-result cards, honest empty-state charts, CSV actions.
- **Compact STOP:** same `serialPumpStopButton`, not a duplicate; fixed, full-width within a 496px maximum; safe-area bottom offset and reserved page space.
- Tokens and breakpoints live in `website/styles.css`; behavior remains in existing JavaScript.

## Accessibility
- Target WCAG AA contrast and keyboard use; do not equate a visual refresh with a completed accessibility audit.
- View links and controls have at least 44px touch height; compact controls 64px.
- Visible keyboard focus includes anchors; preserve native buttons, forms, tabs, status announcements, and preview alternative text.
- Do not convey status through color alone. Preserve STOP wording and missing/raw units.
- Text wraps naturally, with no hard line breaks in the remote warning. Reduced-motion overrides stay intact.

## Responsive behavior
- **Above 1200px:** control title and action grid share a row.
- **701–1200px:** controls span the row; camera previews remain two columns, including 768px and 1024px.
- **700px and below:** full view stacks cameras and readout sections; controls use two columns, pump STOP spans both.
- **Compact mode at any width:** maximum 560px, always single-column content; two-column essential control grid; fixed bottom STOP and safe-area padding.
- View navigation stays visible in both modes and both recording/result contexts. It is never buried in settings.
- Browser evidence targets 375, 768, 1024, and 1440px; include compact scroll and result-mode checks.

## Interaction states
- Connecting/offline: show actual connection state and retain warning that a disconnected page does not automatically stop the pump.
- Empty: preserve “관측 대기”, missing values, and stream placeholders.
- Recording/result/success/error: retain existing state rendering and event handlers.
- Disabled: preserve existing disabled semantics; do not cosmetically enable an unavailable control.
- Long state strings wrap; fixed STOP must not cover the last content item.

## Content voice
Concise Korean operational labels. “녹화 종료” is not “펌프 정지”. Keep units attached to values and distinguish raw thermal data from verified Celsius. No promotional claims or unverified hardware readiness.

## Implementation constraints
Plain HTML/CSS/JavaScript, no new dependencies or external fonts. This refresh does not mutate native Android or backend logic and must not issue real hardware commands during validation. Preserve DOM IDs, ROI geometry, settings semantics, STOP priority, and CSV links.

Verification uses existing static/regression tests, syntax checks, DOM ID comparison, and isolated browser screenshots. Browser fixtures must intercept service requests; visual fixtures are not real experimental evidence.

## Open questions
- [ ] Owner: hardware operator — validate remote STOP feedback and visibility on physical Windows/phone devices after integration; no real pumping was authorized for UI verification.
