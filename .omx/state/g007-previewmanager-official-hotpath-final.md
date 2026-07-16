# G007 PreviewManagerII official hot-path closure final

Date: 2026-07-16

## Commit
- 52a6f5a

## Owned slice implemented
- Replaced Kotlin `PreviewManagerII.kt` official class with Java official-class files producing only official `PreviewManagerII` class files.
- Restored persistent `C0 = new PreviewManagerII$d(this)` and `B0 = new PreviewManagerII$e(this)` constructor wiring; `R()` returns the official F2 callback and `U()` returns the adjacent F1 callback.
- `PreviewManagerII$d` implements synchronized official byte-array mailbox behavior: exact `Arrays.copyOf(frameInfo.pBuf, dwBufSize)`, `Z2.g.a.A0(size)`, profile-size gate via `Z2.a.a.p().e()`, coding-12 offline literal gate, `r0/s0` writes, and 40s invalid-size `c0/P0` path.
- `K2.e` continues to call `PreviewManagerII.g(manager)`; `c1()` preserves r0 priority/clear, s0 duplicate hash suppression through `t0`, `u0` unchanged counter, and `G(byte[])` dispatch.
- Moved app observation and `OfficialProcessedF2Frame` into `kr.auto.titration.mobile.thermal`; official package no longer has `Companion`, `INSTANCE`, `PreviewManagerIIKt`, `OfficialF2StreamCallback`, `BufferedF2Packet`, `officialF2*` sets, or `createF2ModuleStreamCallback` ABI.
- `F2UsbModuleApi` obtains the app-held manager and starts production with `F2ModuleStreamCallback(null, previewManager.R())`.

## Evidence
- `compileDebugKotlin compileDebugUnitTestKotlin lintDebug` PASS.
- `git diff --check` PASS.
- Focused Android unit tests PASS: `PreviewManagerIIF2BufferingTest`, `F2OfficialLifecycleTest`, `G007OfficialPacketProcessorParityTest`.
- Host G007 contract tests PASS: `tests.test_g007_exact_dependency_closure`, `tests.test_g007_f2_architecture_contract`, `tests.test_g007_state_model_hotpath`, `tests.test_g007_codec_gyuv_contract`.
- `javap` forbidden grep PASS for `PreviewManagerII`: no `lambda`, `INSTANCE`, `createF2`, `officialF2`, `OFFICIAL`, or `F2_CONSUMER` tokens.

## Gaps / not claimed
- Full Android unit suite is not green: 172 run, 8 failed, 2 skipped. Failures are stale/source-shape tests expecting previous Kotlin `PreviewManagerII.kt` or JVM Android JSON stubs, not claimed as fixed in this owned slice.
- No live Mini2 hardware run performed; no full G007 pass claimed.

## Class-file inventory
- PreviewManagerII$a.class,PreviewManagerII$b.class PreviewManagerII$c.class,PreviewManagerII$d.class PreviewManagerII$defaultLifecycleObserver$1.class,PreviewManagerII$e.class PreviewManagerII$f.class,PreviewManagerII$g.class PreviewManagerII.class
