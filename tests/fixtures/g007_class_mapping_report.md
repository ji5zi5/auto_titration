# G007 official singleton graph class mapping

Source evidence:
- `.omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/dad/Z2_g.java`
- `_workspace/hikmicro-parity-20260715/g007-closure/extracted/z3_c.java`
- `_workspace/hikmicro-parity-20260715/g007-closure/extracted/z3_c.dex.txt`

## Ported singleton classes

| Official descriptor | Repo class | Evidence mapping | F2 stream/summary-temperature role |
| --- | --- | --- | --- |
| `LZ2/g;` | `mobile/android/app/src/main/java/Z2/g.kt` | Ports singleton `a`, cached fields `b..O`, defaults, accessors/mutators, USB-module-type detection, and preference-key methods from `Z2_g.java`. | `i3.b` uses `v()`, `M()`, `U()`, `K()` while translating official private/upload temperature metadata into callback beans. |
| `Lz3/c;` | `mobile/android/app/src/main/java/z3/c.kt` | Ports singleton `a`, fields `b..v`, defaults (`j=30f`, `k=10f`, `m/n=-1`, `q=true`, `u=960`, `v=720`), and `r(frameNumStamp) -> m` from extracted DEX/DAD. | `PreviewManagerII.f` stores official offline frame stamps through `z3.c.a.r(frameNumStamp)` before dispatching `K2.i`. |

## Dependency classes added for exact package/type references

| Official descriptor/package | Repo class(es) | Reason |
| --- | --- | --- |
| `Lcom/hik/viewercommon/data/bean/UsbModuleType;` | `com/hik/viewercommon/data/bean/UsbModuleType.kt` | Preserves official singleton identity states `NONE`, `F1`, `F2` used by `Z2.g`. |
| `Lcom/hik/viewercommon/data/bean/SceneModeBean;` | `com/hik/viewercommon/data/bean/SceneModeBean.kt` | Required for `Z2.g` scene-mode lists `M/N/O` and copy semantics. |
| `Ll2/k;`, `Ld2/a;`, `Lo2/a;`, `Lu5/B;` | `l2/k.kt`, `d2/a.kt`, `o2/a.kt`, `u5/B.kt` | Required official package dependencies for `Z2.g` preference keys, app context, USB probe, and current module serial access. |
| `LA3/f;` | `A3/f.kt` | Required by `z3.c.s(width,height)` record-size alignment. |
| `Lx3/a;`, `Lw3/k;`, `Lw3/f;`, `Ly3/b;` | `x3/a.kt`, `w3/k.kt`, `w3/f.kt`, `y3/b.kt` | Required renderer/drawer/recorder types for the official `z3.c` graph. |
| `Lcom/hikmicro/pm_hrl_bussinesscmp/model/*;` | `Frame.kt`, `FrameInfo.kt`, `ThermalModel.kt` | Required `z3.c.A/d` frame model package/type references. |

## Isolated graph gaps

- `z3.c` renderer/recorder dependencies (`x3.a`, `w3.k`, `y3.b`) are included as compileable official-package dependency surfaces with the methods exercised by `z3.c`. Their OpenGL rendering internals are not ported because the Viewer F2 stream/summary-temperature hot path only calls `z3.c.r(frameNumStamp)` from `PreviewManagerII.f`; branches `A`, `u`, `y`, and `z` are Android UI/recording paths and are not reachable from the F2 summary-temperature path covered by G007.
- `Z2.g.X()` avoids Gson-backed scene-mode JSON materialization because no F2 stream/summary-temperature caller reaches scene-mode initialization. The state fields and list/cache semantics are retained; JSON parsing internals remain outside the verified hot path.
