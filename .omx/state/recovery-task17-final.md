# Task17 G007 follow-up recovery evidence

## Scope and outcome

This follow-up commit corrects the production-critical `u5.B.h0()` reachable body against `.omx/analysis/task17-shared-support/u5_B.dex.txt`.

- `u5.B.h0()` now reads static field `m` and compares it to `"ThgStart"` with `Intrinsics.areEqual`, matching DEX instructions `sget-object Lu5/B;->m` then `Intrinsics.areEqual`.
- `u5.B.P0(String)` is the official setter path for field `m`; it now checks parameter name `product` and writes `m`.
- `u5.B.l()`/`p()` map returns were corrected after DEX audit: `l()` returns `t`; `p()` returns `s`.
- PreviewManagerII-reachable `u5.B` methods audited for this task: `k()` returns field `b`, `L()` calls `l2.k.e("PERFORMANCE_F22X", -1)`, `d0()` returns field `O`, and `h0()` returns `Intrinsics.areEqual(m, "ThgStart")`.

## Parity boundary

Do **not** treat this as full `u5.B` whole-class body parity. Current support keeps field/method ABI shape for the task17 support surface, but several non-reachable `u5.B` bodies and transitive models remain intentionally outside the accepted claim because official dependencies are not fully ported here:

- `DeviceLoginModel`, `F1DeviceInfo`, and `OfflineFileModel` are compile support stubs, not official full object structures.
- `u5.B.<clinit>()` does not reproduce official `OlmtLib` default credential calls or the full 1087-entry `S` serial array.
- `hik.common.yyrj.businesscommon.b` is retained for PreviewManagerII preference reachability; no full preference-holder body parity is claimed beyond the audited reachable behavior.
- No live-device, full app, or Celsius/temperature-conversion parity is claimed.

## Verification to rerun after this commit

Required gates for this follow-up:

- `./gradlew compileDebugKotlin compileDebugUnitTestKotlin lintDebug`
- focused task17/G007 unit tests including `Task17AdditionalParityGateTest` and `G007PreviewInitClosureTest`
- `git diff --check`
- `javap`/scan evidence for `u5.B` reachable descriptors and absence of Companion/accessor artifacts in `d2.a`, `Z2.a`, `hik.common.yyrj.businesscommon.b`, and `u5.B`.
