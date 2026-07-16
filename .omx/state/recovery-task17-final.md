# Recovery task17 final evidence

## DEX-vs-source audit table

| Gate | Official DEX evidence | Source result |
| --- | --- | --- |
| Constructor descriptor | `PreviewManagerII.<init>(Landroidx/lifecycle/m;ZZ)V` and fields `d/m/n/p/q/t/v/A/B/C/F/K/L/S/i0/j0/l0/r0/s0/y0/z0/A0/B0/C0` in `com_hik_viewer_manager_PreviewManagerII.dex.txt` | Public constructor compiles as `(Landroidx/lifecycle/Lifecycle;ZZ)V` (Lifecycle is the AndroidX source name for DEX `m`); field identities restored for the required binary names except F1 callback bodies remain app-owned nullable until stream binding. |
| Nested classes | DEX constructs `PreviewManagerII$g` and `PreviewManagerII$defaultLifecycleObserver$1` | Explicit nested classes compile to `com.hik.viewer.manager.PreviewManagerII$g` and `$defaultLifecycleObserver$1`; `javap` verified callback/lifecycle descriptors. |
| Default bridge | DEX `m0(PreviewManagerII, View, SurfaceView, TextView, FloatTextureView, SceneModeBean, Function1, Function1, Function1, int, Object): void` with masks 4/16/32/64/128 | Static `m0` restored with the same descriptor and bitmask behavior. |
| `l0` predicates/init chain | DEX uses private `s0()`/`r0()`, F2 size init, optional `n0/p0`, `b1`, `g3.b.a(..., t0())`, F1 `USB_SetYuvSize`, `S=(B.L()==1)`, `g1(...false...)`, renderer bind, listener, lifecycle observer | Source follows this ordering directly; no reflection/default fallback in l0-reachable support calls. |
| Renderer handoff | DEX branch: non-F2 `factory.a`, F2+`Z2.a.t()` `factory.c`, otherwise `factory.b`; frame path passes literal null raw to `h`/`j` at the proven call sites | `bindOfficialRenderer` matches the branch predicates; `handOffOfficialFrame` has one `j(null, ...)` and one `h(null, ...)` call. |
| `u0` teardown | DEX order: renderer `c/release/null`, callback fields null, processor `k/null`, executor shutdown/null, `e1`, flags, view refs, handler callbacks | Source keeps this order in `u0`; app synchronization remains only around wrapper callers. |
| `FloatTextureView` | Official field/method structure `a:F,b:F,c:I,d:I,e:Function1`, private `b/c/g/h`, public `d/f`, companion `a/e`, evaluator/update listener | Source compiles with matching field descriptors and methods; tests verify evaluator class and no helper substitute remains. |
| Shared support | `Z2_a.dex.txt`, `d2_a.dex.txt`, `u5_B.dex.txt`, `businesscommon_b.dex.txt` | `Z2.a.t()` now uses `Z2.g.b(... default mask)` != F1 then static flag; `d2.a` app-context singleton present; `u5.B.k/L/d0/h0` descriptors verified; `businesscommon.b.x` default bridge present. |

## Verification evidence

- `JAVA_HOME=.tools/jdk17 ANDROID_HOME=.tools/android-sdk ANDROID_SDK_ROOT=.tools/android-sdk .tools/gradle/gradle-8.10.2/bin/gradle -p mobile/android compileDebugKotlin compileDebugUnitTestKotlin lintDebug --stacktrace` → BUILD SUCCESSFUL.
- Focused tests: `... gradle -p mobile/android testDebugUnitTest --tests com.hik.viewer.manager.Task17PreviewRendererParityTest --tests com.hik.viewer.manager.Task17AdditionalParityGateTest --tests g007.G007PreviewInitClosureTest --stacktrace` → BUILD SUCCESSFUL, 14 tests.
- `git diff --check -- <owned task17 paths>` → no output.
- `javap -private -s` verified descriptors for `PreviewManagerII`, `PreviewManagerII$g`, `PreviewManagerII$defaultLifecycleObserver$1`, `FloatTextureView`, `Z2.a`, `d2.a`, `u5.B`, `businesscommon.b`.
- Final forbidden-token scan over owned l0/u0/FloatTexture/support sources for `Class.forName`, `getDeclaredMethod`, `.getMethod(`, `TODO`, `NotImplemented`, `fake Unit`, `no-op`, `surrogate`, `isF2Module` → no output.

## Remaining live-device-only gaps

- No live Mini2/F1/F2 USB device stream was available in this worker lane, so physical preview, RID, calibration-file effects, and Celsius parity remain live-device-only.
- This task does not claim full app parity or Celsius parity; it closes the task17 structural/reachable PreviewManagerII/FloatTexture/support gates only.
