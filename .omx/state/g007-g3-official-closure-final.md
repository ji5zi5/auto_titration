# G007 g3 official closure final state

Date: 2026-07-16
Owner scope: `mobile/android/app/src/main/java/g3/**`, dedicated g3/G007 tests, stale G007 host path updates.

## Implemented

- Replaced Kotlin `g3.a/b/c/d/e/f/g` production classes with Java official-shaped classes.
- Restored official g3 ABI field/method closure for:
  - `g3.a`: raw `Function1`/`Function5` callback slots `a/b/c/d/e`, `d(byte[])`, protected `e/f/g/h/i`, `j(...)`, `k()`.
  - `g3.b`: singleton static field `a`, private constructor, official module switch factory.
  - `g3.d`: static `h`, fields `f/g`, constructor `d(i3.a)`, `d(byte[])`, protected `m(byte[])`, protected `n(byte[])`, `l()`, `o(Function1)`, and i3 bridge methods.
  - `g3.e`: static `j`, field `i`, constructor `e(i3.a)`, overrides `d(byte[])` and protected `n(byte[])`.
  - `g3.c/f/g`: official static companion field, `f` stream-info delegate, `l(byte[])`, and dispatch methods.
- Deleted production `g3/F2OfficialPacketProcessor.kt`; no `OfficialPacketProcessor` class remains in the compiled g3 class set.
- Packet split/decode hot path now lives in official concrete `g3.c/d/e/f/g` methods. A public app-internal `kr.auto.titration.mobile.thermal.internal.G3DexBytes` helper exists only to keep non-DEX helper methods out of the official `g3` package inventory and out of `g3.d` declared method set while sharing byte concatenation/raw rotation mechanics.
- Unsupported `g3.d/e` branches still fail closed to empty `PreviewStreamInfo` and dispatch official callbacks; no format ladder/fallback was added.

## Verification evidence

- `ANDROID_HOME=$PWD/.tools/android-sdk JAVA_HOME=$PWD/.tools/jdk17 .tools/gradle/gradle-8.10.2/bin/gradle -p mobile/android compileDebugJavaWithJavac --stacktrace` → PASS.
- `javap -private g3.a g3.b g3.c g3.d g3.e g3.f g3.g` confirms required official fields/methods and no extra `g3.d` helper methods (`dispatch`, `emptyStreamInfo`, `concat`, `rotateRaw`) in `g3.d`.
- Compiled g3 class-file set contains only `g3/a,b,c,c$a,d,d$a,e,e$a,f,f$a,g,g$a` and no `DexBytes`, `F2OfficialPacketProcessor*`, or `OfficialPacketProcessor*` classes.
- Targeted host g3 checks:
  - `tests.test_g007_exact_dependency_closure.G007ExactDependencyClosureTests.test_g3_materializes_official_structs_and_uses_k3_gyuv_path` → PASS.
  - `tests.test_g007_f2_architecture_contract.G007F2CallbackSchedulerClosureTests.test_g3a_callback_slots_are_not_noop_and_are_cleared_by_k` → PASS.

## Remaining gaps / blockers

- `compileDebugUnitTestKotlin` passes in the current incremental build. Focused `testDebugUnitTest --tests g3.* --tests g007.*` still fails four non-g3 `G007PreviewInitClosureTest` assertions against separate PreviewManager Java content outside this executor's write scope.
- Host G007 suites still include non-owned PreviewManager/Z2 expectations that fail against current separate-executor Java paths or pending task17 state; those were not weakened or broadened in this g3-only closure.
- Live hardware parity is not claimed.
