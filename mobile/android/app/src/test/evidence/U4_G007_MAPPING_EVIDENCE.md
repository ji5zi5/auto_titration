# G007 Official U4 Codec Mapping Evidence

Source APK evidence used: `_workspace/hikmicro-parity-20260715/g007-codec-gyuv/extracted/` and matching closure copies under `g007-closure/extracted/`.

## Class graph implemented

| Official extraction | Repo implementation | Responsibility |
| --- | --- | --- |
| `U4_c.java` | `mobile/android/app/src/main/java/U4/c.kt` | Public entrypoint: `a(Object, ByteOrder)` delegates to `new U4.m(byteOrder).p0(...)`; `b(Object, byte[], ByteOrder)` delegates to `new U4.n(buffer, byteOrder).m0(...)`. |
| `U4_o.java` | `U4/o.kt` | Synchronized class metadata cache, `@U4.f` validation, public/non-abstract class validation, declared-field ordering by `@U4.i`. |
| `U4_g.java` | `U4/g.kt` | Ordered field metadata, modifier validation, getter/setter discovery for private/protected/package fields, `@U4.a` length-marker target map. |
| `U4_j.java` | `U4/j.kt` | Field metadata holder: field, getter, setter, accessor flag, length-marker flag, primitive/object kind. |
| `U4_b.java`, `U4_b__a.java` | `U4/b.kt` | Primitive/object kind resolver from field type name or array descriptor code. |
| `U4_l.java`, `U4_m.java` | `U4/l.kt`, `U4/m.kt` | Object-to-buffer traversal, getter-aware writes, nested object/object-array writes, primitive array writes, endian-selected `DataOutput`. |
| `U4_k.java`, `U4_n.java` | `U4/k.kt`, `U4/n.kt` | Buffer-to-object traversal, setter-aware reads, marker-driven array allocation, nested object/object-array reads, endian-selected `DataInput`. |
| `U4_d.java`, `U4_e.java` | `U4/d.kt`, `U4/e.kt` | Little-endian `DataInput` / `DataOutput` wrappers; non-little-endian uses Java `DataInputStream` / `DataOutputStream`. |
| `U4_a.java`, `U4_f.java`, `U4_i.java`, `U4_h.java` | `U4/Annotations.kt`, `U4/h.kt` | Runtime annotations and official checked exception messages. |
| `k3_b.java` | `mobile/android/app/src/main/java/k3/b.kt` | Kotlin facade delegation to `U4.c`, default little-endian masks, catch/print/return-null behavior for encode errors. |

## DEX-specific semantics covered by tests

- Getter/setter metadata: `AccessorLength` uses private fields with public getters/setters, including boolean `isActive` lookup.
- Length-marker access: `@U4.a(fieldName = "values")` is placed on marker fields as in `U4_g` target-map construction; `U4_n` allocates arrays from the marker before reading.
- Object arrays: marker-driven object array allocation instantiates component structs before nested reads.
- Null errors: null nested object encode raises `Struct classes cant be null. `; null unmarked array decode raises `Arrays can not be null. : <field>`.
- Endian behavior: little-endian uses `U4.d/e`; big-endian uses Java data streams.
- Inheritance/order: `U4_o` uses `getDeclaredFields()`, so inherited fields are not serialized by the official graph.
- No monolithic shortcut: `U4.c` is only the entrypoint; traversal and metadata live in the official responsibility classes.

## Fresh verification

- `python3 -m unittest discover -v -p 'test_g007*.py' tests` → OK, 22 tests.
- Standalone U4/k3/JUnit compile and execution with Kotlin compiler embeddable + JUnit 4.13.2 → OK, 7 `g007.G007U4CodecTest` tests.
- Full Android Gradle command attempted: `ANDROID_HOME=$PWD/.tools/android-sdk JAVA_HOME=$PWD/.tools/jdk .tools/gradle/gradle-8.10.2/bin/gradle -p mobile/android testDebugUnitTest --tests 'g007.G007U4CodecTest'` → blocked before U4 tests by existing disallowed-scope compile error in `mobile/android/app/src/main/java/Z2/a.kt:18:40` (`expected 'j', actual 'Size'`). Per scope guard, Z2 was not touched.
