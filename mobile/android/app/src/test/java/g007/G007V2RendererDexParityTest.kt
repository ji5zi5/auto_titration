package g007

import java.io.File
import java.lang.reflect.Field
import java.lang.reflect.InvocationTargetException
import java.lang.reflect.Method
import java.lang.reflect.Modifier
import kotlin.math.round
import org.Thermal.PlayM4.Player
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertSame
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class G007V2RendererDexParityTest {
    @Test fun v2bAndV2dUseOfficialExactModeBranchesForModesZeroThroughFour() {
        val v2b = source("app/src/main/java/V2/b.java")
        val v2d = source("app/src/main/java/V2/d.java")
        listOf(v2b, v2d).forEach { text ->
            assertFalse(text.contains("mode >="))
            listOf("mode == 1", "mode == 2", "mode == 3").forEach { assertTrue(text.contains(it)) }
        }
        assertFalse(v2b.contains("mode == 4"))
        assertTrue(v2b.substringAfter("else {").contains("setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, false)"))
        listOf("mode == 1", "mode == 2", "mode == 3", "mode == 4").forEach { assertTrue(v2d.contains(it)) }
    }

    @Test fun v2dGeometryIsDerivedFromOfficialZ2gFRowListAndOffsets() {
        val v2d = source("app/src/main/java/V2/d.java")
        assertTrue(v2d.contains("List<?> rowTypes = state.F()"))
        assertFalse(v2d.contains("officialRowHeights"))
        assertFalse(v2d.contains("fixed surrogate"))
        assertTrue(v2d.contains("firstRect.bottom + 0.008f"))
        assertTrue(v2d.contains("row1.bottom + 0.008f"))
        assertTrue(v2d.contains("row2.bottom + 0.008f"))
        assertTrue(v2d.contains("row3.bottom + 0.008f"))
        assertTrue(v2d.contains("0.046f"))
        assertTrue(v2d.contains("0.084f"))
        assertTrue(v2d.contains("0.12f"))
        assertEquals(
            listOf(0.0555f, 0.086f, 0.1215f, 0.162f).map { round6(it) },
            officialDexRowHeights(listOf(0, 1, 2, 3)).map { round6(it) },
        )
    }

    @Test fun recordCodecDefaultComesFromOfficialA2dSingletonBeforePreferenceOverride() {
        val v2b = source("app/src/main/java/V2/b.java")
        val v2d = source("app/src/main/java/V2/d.java")
        listOf(v2b, v2d).forEach { text ->
            assertTrue(text.contains("l2.k.e(\"RECORD_CODEC_TYPE\", A2.d.a.a())"))
            assertFalse(text.contains("l2.k.e(\"RECORD_CODEC_TYPE\", 0)"))
        }
        val a2d = source("app/src/main/java/A2/d.java")
        assertTrue(a2d.contains("Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_NV12"))
        assertTrue(a2d.contains("Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_I420"))
        assertTrue(a2d.contains("getDefaultRecordCodecType:manufacturer_"))
    }


    @Test fun v2SourceRestoresOfficialKotlinNullChecksAndDirectAssetDecodeShape() {
        val expectations = mapOf(
            "app/src/main/java/V2/b.java" to listOf(
                "surfaceView", "listener", "picSize", "filePath", "nv12Data", "yuvImgSize", "showSize",
            ),
            "app/src/main/java/V2/d.java" to listOf(
                "surfaceView", "listener", "picSize", "filePath", "nv12Data", "yuvImgSize", "showSize",
            ),
        )
        expectations.forEach { (path, parameterNames) ->
            val text = source(path)
            assertTrue("$path imports Intrinsics", text.contains("import kotlin.jvm.internal.Intrinsics;"))
            assertFalse("$path must not use try-with-resources asset streams", text.contains("try (InputStream"))
            assertTrue("$path must check getContext", text.contains("Intrinsics.checkNotNullExpressionValue(context, \"getContext(...)\")"))
            assertTrue("$path must check getHolder", text.contains("Intrinsics.checkNotNullExpressionValue(holder, \"getHolder(...)\")"))
            assertTrue("$path must check asset open result", text.contains("Intrinsics.checkNotNullExpressionValue(stream, \"open(...)\")"))
            assertTrue("$path must check decoded bitmap before OSD/logo handoff", text.contains("Intrinsics.checkNotNull(osdBitmap)"))
            assertTrue("$path must check decoded logo before handoff", text.contains("Intrinsics.checkNotNull(bitmap)"))
            parameterNames.forEach { name ->
                assertTrue("$path missing official null check for $name", text.contains("Intrinsics.checkNotNullParameter($name, \"$name\")"))
            }
            listOf("rawData", "overlays", "overlayBitmap").forEach { name ->
                assertFalse("$path should preserve nullable official parameter $name", text.contains("checkNotNullParameter($name,"))
            }
        }
    }


    @Test fun v2AssetOpenRethrowsOriginalIOExceptionWithoutRuntimeWrapper() {
        listOf(
            "app/src/main/java/V2/b.java" to V2.b::class.java,
            "app/src/main/java/V2/d.java" to V2.d::class.java,
        ).forEach { (path, type) ->
            val text = source(path)
            assertFalse("$path must not add private asset helper methods", text.contains("openAsset("))
            assertFalse("$path must not add private sneaky throw methods", text.contains("sneakyThrow"))
            assertFalse("$path must not wrap asset open failures", text.contains("new RuntimeException"))
            assertFalse("$path must not use try-with-resources asset streams", text.contains("try ("))
            assertTrue("$path must open official OSD asset path through external bridge", text.contains("AssetOpenBridge.open(d2.a.a().getResources().getAssets(), \"osd_bg.png\")"))
            assertTrue("$path must open official logo asset path through external bridge", text.contains("AssetOpenBridge.open(d2.a.a().getResources().getAssets(), \"logo_hik_w.png\")"))
            assertEquals("$path declared method descriptors must stay exact", parseDexMethods(officialSupport(type.simpleNameDexFile())), reflectMethods(type))
        }

        val bridge = Class.forName("V2.AssetOpenBridge")
        val bridgeSource = source("app/src/main/java/V2/AssetOpenBridge.java")
        assertTrue(bridgeSource.contains("return assets.open(assetPath)"))
        assertTrue(bridgeSource.contains("} catch (IOException exception) {"))
        assertTrue(bridgeSource.contains("return throwUnchecked(exception)"))
        assertFalse(bridgeSource.contains("new RuntimeException"))
        assertFalse(bridgeSource.contains("try ("))
        assertFalse(bridgeSource.contains(".close()"))

        val marker = java.io.IOException("asset-open-marker")
        val openerType = Class.forName("V2.AssetOpenBridge\$AssetOpener")
        val throwingOpener = java.lang.reflect.Proxy.newProxyInstance(
            bridge.classLoader,
            arrayOf(openerType),
        ) { _, method, _ ->
            if (method.name == "open") throw marker
            null
        }
        val open = bridge.getDeclaredMethod("open", openerType, String::class.java)
        open.isAccessible = true
        val thrown = assertThrows(InvocationTargetException::class.java) {
            open.invoke(null, throwingOpener, "osd_bg.png")
        }
        assertSame("AssetOpenBridge.open must rethrow the same IOException instance", marker, thrown.cause)
    }

    @Test fun ownedSliceHasNoTodoThrowOrNoOpSurrogatesExceptOfficialNoOps() {
        val owned = listOf(
            "app/src/main/java/V2/b.java",
            "app/src/main/java/V2/d.java",
            "app/src/main/java/A2/b.java",
            "app/src/main/java/A2/d.java",
        ).associateWith(::source)
        owned.forEach { (path, text) ->
            assertFalse("$path contains TODO", text.contains("TODO("))
            assertFalse("$path throws NotImplementedError", text.contains("NotImplementedError"))
            assertFalse("$path assumes l2.k codec default 0", text.contains("RECORD_CODEC_TYPE\", 0"))
        }
        assertTrue(owned.getValue("app/src/main/java/V2/b.java").contains("public void release() { }"))
        assertTrue(owned.getValue("app/src/main/java/V2/b.java").contains("public void b(com.hik.library.player.b listener) { Intrinsics.checkNotNullParameter(listener, \"listener\"); }"))
        assertTrue(owned.getValue("app/src/main/java/V2/d.java").contains("public void j("))
    }

    @Test fun a2BinaryAbiMatchesOfficialDexFieldsAndMethods() {
        assertEquals(parseDexFields(officialExtract("A2_b.dex.txt")), reflectFields(A2.b::class.java))
        assertEquals(parseDexFields(officialExtract("A2_d.dex.txt")), reflectFields(A2.d::class.java))
        assertEquals(parseDexMethods(officialExtract("A2_b.dex.txt")), reflectMethods(A2.b::class.java))
        assertEquals(parseDexMethods(officialExtract("A2_d.dex.txt")), reflectMethods(A2.d::class.java))
        assertEquals(parseDexConstructors(officialExtract("A2_b.dex.txt")), reflectConstructors(A2.b::class.java))
        assertEquals(parseDexConstructors(officialExtract("A2_d.dex.txt")), reflectConstructors(A2.d::class.java))
        assertFalse(A2.b::class.java.declaredClasses.any { it.simpleName == "Companion" })
        assertFalse(A2.d::class.java.declaredClasses.any { it.simpleName == "Companion" })
    }

    @Test fun a2CodecDefaultBehaviorMatchesOfficialGuardTruthTable() {
        val a2bSource = source("app/src/main/java/A2/b.java")
        ('b'..'w').forEach { fieldName ->
            assertTrue("A2.b missing official guard field $fieldName", a2bSource.contains("private static final boolean $fieldName;"))
        }
        val predicateMap = mapOf("a()" to "x", "b()" to "g", "c()" to "j", "d()" to "l", "e()" to "c")
        predicateMap.forEach { (method, fieldName) ->
            assertTrue("A2.b predicate $method should expose guard $fieldName", a2bSource.contains("public final boolean $method { return $fieldName; }"))
        }

        val guardFields = ('b'..'x').map { A2.b::class.java.getDeclaredField(it.toString()) }
        val original = guardFields.associateWith(::getStaticBoolean)
        try {
            setAll(guardFields, false)
            assertEquals(Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_NV12, A2.d.a.a())

            val officialI420Guards: Map<String, () -> Boolean> = mapOf(
                "c" to { A2.b.a.e() },
                "g" to { A2.b.a.b() },
                "j" to { A2.b.a.c() },
                "l" to { A2.b.a.d() },
                "x" to { A2.b.a.a() },
            )
            officialI420Guards.forEach { (fieldName, predicate) ->
                setAll(guardFields, false)
                setStaticBoolean(A2.b::class.java.getDeclaredField(fieldName), true)
                assertTrue("guard $fieldName should drive its public predicate", predicate())
                assertEquals("guard $fieldName should select I420", Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_I420, A2.d.a.a())
            }
        } finally {
            original.forEach { (field, value) -> setStaticBoolean(field, value) }
        }
    }

    @Test fun v2BinaryAbiMatchesOfficialDexMethodsFieldsAndCompanionConstructors() {
        assertEquals(parseDexFields(officialSupport("V2_b.dex.txt")), reflectFields(V2.b::class.java))
        assertEquals(parseDexFields(officialSupport("V2_d.dex.txt")), reflectFields(V2.d::class.java))
        assertEquals(parseDexMethods(officialSupport("V2_b.dex.txt")), reflectMethods(V2.b::class.java))
        assertEquals(parseDexMethods(officialSupport("V2_d.dex.txt")), reflectMethods(V2.d::class.java))
        assertEquals(parseDexConstructors(officialSupport("V2_b.dex.txt")), reflectConstructors(V2.b::class.java))
        assertEquals(parseDexConstructors(officialSupport("V2_d.dex.txt")), reflectConstructors(V2.d::class.java))

        mapOf(
            "V2.b\$a" to officialSupport("V2_b__a.dex.txt"),
            "V2.d\$a" to officialSupport("V2_d__a.dex.txt"),
        ).forEach { (name, officialFile) ->
            val official = officialFile.readText()
            assertTrue(official.contains("METHOD public synthetic constructor <init>(Lkotlin/jvm/internal/DefaultConstructorMarker;)V"))
            val companion = Class.forName(name)
            assertTrue(companion.declaredConstructors.any { Modifier.isPrivate(it.modifiers) && it.parameterTypes.isEmpty() })
            assertTrue(companion.declaredConstructors.any {
                constructorDescriptor(it) == "<init>(Lkotlin/jvm/internal/DefaultConstructorMarker;)V"
            })
        }
    }

    @Test fun v2dHBranchGraphUsesOfficialDexConstantsAndCompiledCalls() {
        val official = officialSupport("V2_d.dex.txt").readText()
        listOf(
            "invoke-virtual           v5, LZ2/a;->i()Z",
            "instance-of              v10, v9, Lh3/b;",
            "instance-of              v10, v9, Lh3/c;",
            "const                    v8, 98304",
            "const                    v9, 221184",
            "invoke-virtual           v4, LZ2/g;->j()[B",
            "invoke-virtual/range     v8 ... v15, Ld3/i;->m(",
            "invoke-virtual/range     v8 ... v21, Ld3/i;->k(",
            "const/16                 v3, 27640",
            "getYuvThermalDataInfo([B Landroid/util/Size;)[B",
            "getThermalDataInfo([B [B Landroid/util/Size; I)[B",
        ).forEach { assertTrue("official dex missing $it", official.contains(it)) }

        val impl = source("app/src/main/java/V2/d.java")
        listOf(
            "Z2.a.a.i()",
            "streamInfo instanceof h3.b",
            "streamInfo instanceof h3.c",
            "new Integer[] {98304, 221184}",
            "state.j()",
            "d3.i.a.m(",
            "d3.i.a.k(",
            "n() ? 27640 : 0",
            "getYuvThermalDataInfo(nv12Data, yuvImgSize)",
            "getYuvThermalDataInfo(state.j(), yuvImgSize)",
            "getThermalDataInfo(thermalPrivateInfoData, nv12Data, yuvImgSize, totalLength)",
        ).forEach { assertTrue("implementation missing $it", impl.contains(it)) }

        val privateStamp = impl.indexOf("privateInfo.privateInfo_header.dsp_std_stamp = frameNumStamp")
        val privateSerialize = impl.indexOf("thermalPrivateInfoData = k3.b.b(k3.b.a, info, null, 2, null)", privateStamp)
        assertTrue("private-stream stamp must target source privateInfo before serializing official info", privateStamp >= 0 && privateSerialize > privateStamp)
        val uploadStamp = impl.indexOf("info.privateInfo_header.dsp_std_stamp = frameNumStamp")
        val uploadSerialize = impl.indexOf("thermalPrivateInfoData = k3.b.b(k3.b.a, info, null, 2, null)", uploadStamp)
        assertTrue("upload branch must stamp serialized info before serialization", uploadStamp >= 0 && uploadSerialize > uploadStamp)
    }

    private fun officialDexRowHeights(rectTypes: List<Int>): FloatArray {
        val heights = FloatArray(4)
        rectTypes.take(4).forEachIndexed { index, rectType ->
            heights[index] = (rectType + 1) * 0.0405f
            when (rectType) {
                0 -> heights[index] += 0.01f
                1 -> heights[index] += 0.005f
                2 -> if (index == 0) heights[index] += 0.005f else heights[0] += 0.005f
            }
        }
        return heights
    }

    private fun round6(value: Float): Float = round(value * 1_000_000f) / 1_000_000f

    private fun parseDexFields(file: File): List<FieldAbi> {
        var inFieldBlock = false
        return file.readLines().mapNotNull { raw ->
            val line = raw.trim()
            when (line) {
                "FIELDS" -> { inFieldBlock = true; return@mapNotNull null }
                "METHODS" -> { inFieldBlock = false; return@mapNotNull null }
            }
            val body = when {
                line.startsWith("FIELD ") -> line.removePrefix("FIELD ")
                inFieldBlock && line.isNotEmpty() -> line
                else -> return@mapNotNull null
            }
            val tokens = body.split(Regex("\\s+"))
            FieldAbi(
                name = tokens[tokens.size - 2],
                descriptor = tokens.last(),
                modifiers = tokens.dropLast(2).toSet(),
            )
        }.sortedWith(compareBy({ it.name }, { it.descriptor }))
    }

    private fun reflectFields(type: Class<*>): List<FieldAbi> =
        type.declaredFields
            .filterNot { it.isSynthetic }
            .map {
                FieldAbi(
                    name = it.name,
                    descriptor = descriptor(it.type),
                    modifiers = modifierTokens(it.modifiers),
                )
            }
            .sortedWith(compareBy({ it.name }, { it.descriptor }))

    private fun parseDexMethods(file: File): List<String> =
        file.readLines().mapNotNull { raw ->
            val line = raw.trim()
            val body = when {
                line.startsWith("METHOD ") -> line.removePrefix("METHOD ")
                line.startsWith("### ") -> line.removePrefix("### ")
                else -> return@mapNotNull null
            }
            if (" constructor " in body || body.contains("<clinit>") || body.contains("<init>")) return@mapNotNull null
            val match = Regex("""(?:public|private|protected|static|final|synthetic|native|abstract|\s)+\s+([^\s(]+)\(([^)]*)\)(\S+)""")
                .find(body) ?: return@mapNotNull null
            val name = match.groupValues[1]
            val args = match.groupValues[2].replace(" ", "")
            val ret = match.groupValues[3].substringBefore(' ')
            "$name($args)$ret"
        }.sorted()

    private fun reflectMethods(type: Class<*>): List<String> =
        type.declaredMethods
            .filterNot { it.isSynthetic || it.isBridge }
            .map { methodDescriptor(it) }
            .sorted()

    private fun parseDexConstructors(file: File): List<String> =
        file.readLines().mapNotNull { raw ->
            val line = raw.trim()
            val body = when {
                line.startsWith("METHOD ") -> line.removePrefix("METHOD ")
                line.startsWith("### ") -> line.removePrefix("### ")
                else -> return@mapNotNull null
            }
            if (!body.contains("<init>")) return@mapNotNull null
            val match = Regex("""((?:public|private|protected|synthetic|\s)+)constructor <init>\(([^)]*)\)(\S+)""")
                .find(body) ?: return@mapNotNull null
            val modifiers = match.groupValues[1].trim().split(Regex("\\s+")).filter { it != "synthetic" }.sorted().joinToString(" ")
            val args = match.groupValues[2].replace(" ", "")
            val ret = match.groupValues[3].substringBefore(' ')
            "$modifiers <init>($args)$ret"
        }.sorted()

    private fun reflectConstructors(type: Class<*>): List<String> =
        type.declaredConstructors
            .filterNot { it.isSynthetic }
            .map { constructorDescriptorWithModifiers(it) }
            .sorted()

    private fun constructorDescriptorWithModifiers(constructor: java.lang.reflect.Constructor<*>): String =
        modifierTokens(constructor.modifiers).sorted().joinToString(" ") + " " + constructorDescriptor(constructor)

    private fun constructorDescriptor(constructor: java.lang.reflect.Constructor<*>): String =
        constructor.parameterTypes.joinToString(prefix = "<init>(", postfix = ")V", separator = "") { descriptor(it) }

    private fun methodDescriptor(method: Method): String =
        method.name + method.parameterTypes.joinToString(prefix = "(", postfix = ")", separator = "") { descriptor(it) } + descriptor(method.returnType)

    private fun descriptor(type: Class<*>): String = when {
        type == java.lang.Void.TYPE -> "V"
        type == java.lang.Boolean.TYPE -> "Z"
        type == java.lang.Byte.TYPE -> "B"
        type == java.lang.Character.TYPE -> "C"
        type == java.lang.Short.TYPE -> "S"
        type == java.lang.Integer.TYPE -> "I"
        type == java.lang.Long.TYPE -> "J"
        type == java.lang.Float.TYPE -> "F"
        type == java.lang.Double.TYPE -> "D"
        type.isArray -> type.name.replace('.', '/')
        else -> "L${type.name.replace('.', '/')};"
    }

    private fun modifierTokens(modifiers: Int): Set<String> = buildSet {
        if (Modifier.isPublic(modifiers)) add("public")
        if (Modifier.isPrivate(modifiers)) add("private")
        if (Modifier.isProtected(modifiers)) add("protected")
        if (Modifier.isStatic(modifiers)) add("static")
        if (Modifier.isFinal(modifiers)) add("final")
    }

    private fun setAll(fields: List<Field>, value: Boolean) = fields.forEach { setStaticBoolean(it, value) }

    private fun getStaticBoolean(field: Field): Boolean {
        field.isAccessible = true
        return unsafeMethod("getBooleanVolatile", Any::class.java, java.lang.Long.TYPE)
            .invoke(unsafe, unsafeBase(field), unsafeOffset(field)) as Boolean
    }

    private fun setStaticBoolean(field: Field, value: Boolean) {
        field.isAccessible = true
        unsafeMethod("putBooleanVolatile", Any::class.java, java.lang.Long.TYPE, java.lang.Boolean.TYPE)
            .invoke(unsafe, unsafeBase(field), unsafeOffset(field), value)
    }

    private fun unsafeBase(field: Field): Any? =
        unsafeMethod("staticFieldBase", Field::class.java).invoke(unsafe, field)

    private fun unsafeOffset(field: Field): Long =
        unsafeMethod("staticFieldOffset", Field::class.java).invoke(unsafe, field) as Long

    private fun unsafeMethod(name: String, vararg parameterTypes: Class<*>): Method =
        unsafe.javaClass.getMethod(name, *parameterTypes)

    private val unsafe: Any by lazy {
        Class.forName("sun.misc.Unsafe").getDeclaredField("theUnsafe").run {
            isAccessible = true
            get(null)
        }
    }

    private data class FieldAbi(val name: String, val descriptor: String, val modifiers: Set<String>)

    private fun Class<*>.simpleNameDexFile(): String = "V2_${simpleName}.dex.txt"

    private fun source(relativePath: String): String = File(mobileRoot(), relativePath).readText()

    private fun mobileRoot(): File = generateSequence(File(requireNotNull(System.getProperty("user.dir")))) { it.parentFile }
        .flatMap { sequenceOf(it, File(it, "mobile/android")) }
        .first { File(it, "app/src/main/java/V2/b.java").exists() }

    private fun officialSupport(name: String): File = File(mobileRoot(), "app/src/test/resources/official_parity/g007-v2-transitive-support/$name")
    private fun officialExtract(name: String): File = File(mobileRoot(), "app/src/test/resources/official_parity/a2-official-extract/$name")
}
