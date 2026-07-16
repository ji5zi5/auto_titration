# Task17 G007 final recovery evidence

## Corrective implementation
- Replaced Kotlin `d2.a` with Java `d2.a`: fields are only `public static final d2.a a` and `private static android.content.Context b`; `a()` throws Kotlin uninitialized-property exception for `appContext` when unset; `b(Context)` stores `context.getApplicationContext()`.
- Replaced Kotlin `Z2.a` with Java `Z2.a`: official obfuscated singleton fields `a` through `u`, no Companion/accessors, and `t()` preserves the audited `UsbModuleType.F1 && s` predicate.
- Replaced Kotlin `hik.common.yyrj.businesscommon.b` with Java field/method ABI matching the official preference holder; `w(String)` returns false when the serial is present in `preview_logo_visible` and true otherwise; `x(...)` preserves the default serial lookup through `u5.B.a.k().getSerialNumber()`.
- Expanded `u5.B` from the reachable-only Kotlin surrogate to Java with the official field/method descriptor surface used by the task17 support DEX. Added minimal entry/support types needed for descriptors to compile.
- Strengthened task17/G007 tests to assert official field descriptors and absence of `Companion`/`access$` artifacts for recovered support classes.

## Verification evidence
- Required compile/lint: `JAVA_HOME=/home/jio/code/auto_titration/.tools/jdk17 ANDROID_HOME=/home/jio/code/auto_titration/.tools/android-sdk ANDROID_SDK_ROOT=/home/jio/code/auto_titration/.tools/android-sdk /home/jio/code/auto_titration/.tools/gradle/gradle-8.10.2/bin/gradle -p /home/jio/code/auto_titration/mobile/android compileDebugKotlin compileDebugUnitTestKotlin lintDebug` -> BUILD SUCCESSFUL.
- Focused tests: same env, `gradle -p /home/jio/code/auto_titration/mobile/android testDebugUnitTest --tests 'g007.*' --tests 'com.hik.viewer.manager.Task17*' --tests 'g3.G007OfficialPacketProcessorParityTest' --tests 'i3.G007I3CallbackParityTest'` -> BUILD SUCCESSFUL.
- Combined focused gate with compile/lint and `Task17AdditionalParityGateTest`/`g007.*` -> BUILD SUCCESSFUL.
- Whitespace: `git diff --check` -> clean.
- `javap -private -s -classpath mobile/android/app/build/tmp/kotlin-classes/debug:mobile/android/app/build/intermediates/javac/debug/compileDebugJavaWithJavac/classes d2.a` -> exactly `public static final d2.a a; private static android.content.Context b; private constructor; static a()/b(Context);` and no `Companion`.
- Filesystem/class check: `find mobile/android/app/build -path '*d2/a$Companion.class' ...` -> no Companion class files; `find .../d2/*` shows only `d2/a.class`.
- Synthetic accessor check: `javap -private` grep for `access$` across `d2.a`, `Z2.a`, `hik.common.yyrj.businesscommon.b`, `u5.B` -> no matches.

## Notes / limits
- The official APK evidence contains `com.fasterxml.jackson.databind.ObjectMapper`; the existing in-tree ObjectMapper surface remains the local compile-time substitute because Gradle dependency edits were outside this worker's requested source focus.
- No live HIKMICRO Mini2/F1/F2 hardware run was performed; Celsius/live-device parity is not claimed.
