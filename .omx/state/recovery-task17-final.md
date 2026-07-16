# Task17 G007 audit recovery evidence

## Fixed in this follow-up
- `Z2.a.t()` now follows the extracted DEX predicate: `Z2.g.b(Z2.g.a, false, 1, null) == UsbModuleType.F1 && appendEnabled`; the non-F1 surrogate flag was removed.
- `d2.a` is no longer a Kotlin `object`; it exposes the official singleton/context API shape (`a`, `b`, static `a(): Context`, static `b(Context): void`). Kotlin still emits a Companion/accessors; exact no-extra-field parity remains noted below.
- `hik.common.yyrj.businesscommon.b` no longer uses Gson/TypeToken for `preview_logo_visible`; its `n()` path uses `com.fasterxml.jackson.databind.ObjectMapper.readValue(..., ArrayList().javaClass)` and `w()` preserves the DEX behavior of returning false when the serial exists.
- Added a narrow in-tree `com.fasterxml.jackson.databind.ObjectMapper` shim for the preview-logo-visible string-array path because the project did not already declare Jackson and build.gradle is outside this worker's ownership.
- Confirmed `PreviewManagerII` no longer has the duplicate `streamingNew` named argument and retains direct calls for `u5.B.a.L()/d0()/h0()` and `businesscommon.b.x(...)`.

## Verification evidence
- Compile/lint: `JAVA_HOME=/home/jio/code/auto_titration/.tools/jdk17 ANDROID_HOME=/home/jio/code/auto_titration/.tools/android-sdk ANDROID_SDK_ROOT=/home/jio/code/auto_titration/.tools/android-sdk /home/jio/code/auto_titration/.tools/gradle/gradle-8.10.2/bin/gradle -p /home/jio/code/auto_titration/mobile/android compileDebugKotlin compileDebugUnitTestKotlin lintDebug` -> BUILD SUCCESSFUL.
- Focused tests: same env, `gradle ... testDebugUnitTest --tests 'g007.*' --tests 'com.hik.viewer.manager.Task17*' --tests 'g3.G007OfficialPacketProcessorParityTest' --tests 'i3.G007I3CallbackParityTest'` -> BUILD SUCCESSFUL; 57 tests completed, 2 skipped.
- Whitespace: `git diff --check` -> clean.
- Final owned-path scan for `reflect`, `reflection`, `TODO`, `NotImplemented`, `no-op`, `surrogate`, `isF2Module`, `Z2.g.a.a(true)`, `Gson`, `TypeToken`, `nonF1ProcessingEnabled` -> no matches.

## javap ABI audit highlights (`javap -private -s`)
- `Z2.a`: has `public static final Z2.a a`, `t():Z`, `r():I`, `s():I`; source body now matches DEX `F1 && s` semantics. Kotlin-emitted Companion and descriptive private field names remain intentionally deferred from exact obfuscated field identity.
- `d2.a`: has `public static final d2.a a`, `private static Context b`, `public static final a(): Context`, `public static final b(Context): void`; Kotlin Companion/accessors are extra versus official DEX.
- `u5.B`: has `public static final u5.B a`, `L():I`, `d0():Z`, `h0():Z`, `k():DeviceInfoModel`; implementation remains narrowed to the l0/u0-reachable static state and intentionally does not port the full official field set (`S`, `c`..`z`, maps, login/offline models, etc.).
- `businesscommon.b`: has `ObjectMapper b`, `SharedPreferences c`, `v(Context):void`, private `n():List`, `w(String):Z`, synthetic-style `x(b,String,int,Object):Z`; `context` field is named differently from official private `a` because Kotlin source also contains nested class `a`.
- `PreviewManagerII`: public constructor descriptor `(Landroidx/lifecycle/Lifecycle;ZZ)V`; `m0` default bridge descriptor includes the expected bitmask/object tail; nested `PreviewManagerII$g` and `PreviewManagerII$defaultLifecycleObserver$1` are present.
- `FloatTextureView`: fields `a:F`, `b:F`, `c:I`, `d:I`, `e:Function1`; private `b()`, `c(FF)`, `g()`, `h(FF)`; public `d(IZ)`, `f(IZ,Size,Size)`, touch handler, nested evaluator classes present.

## Remaining live-device-only / intentionally deferred gaps
- No live HIKMICRO Mini2/F1/F2 device run was performed; Celsius/temperature correctness is not claimed.
- Full official `u5.B` and exact obfuscated private field identity for Kotlin support classes remain narrowed to the PreviewManagerII l0/u0 reachable closure.
- The in-tree ObjectMapper shim covers the DEX-proven preview-logo-visible list path only; it is not a general Jackson replacement.
