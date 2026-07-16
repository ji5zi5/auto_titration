package kr.auto.titration.mobile.thermal.officialdex

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

class OfficialDexLoaderContractTest {
    @Test
    fun officialArtifactHashesMatchApprovedBytes() {
        assertEquals(
            OfficialDexArtifacts.CLASSES_SHA256,
            OfficialDexHashing.sha256(repoFile("src/main/assets/hikmicro/official/classes.dex")),
        )
        assertEquals(
            OfficialDexArtifacts.CLASSES2_SHA256,
            OfficialDexHashing.sha256(repoFile("src/main/assets/hikmicro/official/classes2.dex")),
        )
        assertEquals(
            OfficialDexArtifacts.CLASSES3_SHA256,
            OfficialDexHashing.sha256(repoFile("src/main/assets/hikmicro/official/classes3.dex")),
        )
        assertEquals(
            OfficialDexArtifacts.CLASSES4_SHA256,
            OfficialDexHashing.sha256(repoFile("src/main/assets/hikmicro/official/classes4.dex")),
        )
        assertEquals(
            OfficialDexArtifacts.NATIVE_LIBRARY_SHA256,
            OfficialDexHashing.sha256(repoFile("src/main/jniLibs/arm64-v8a/libSJNI.so")),
        )
    }

    @Test
    fun requiredIdentityClassesIncludeEntryPathTransitivesAndSwigSurface() {
        val required = OfficialDexArtifacts.REQUIRED_OFFICIAL_CLASSES
        listOf(
            "d3.f",
            "d3.d",
            "d3.e",
            "d3.g",
            "Z2.a",
            "Z2.g",
            "k3.b",
            "f3.k",
            "com.hik.f2module.IFR_INFO\$OFFLINE_TEMP_MEASURE_CFG",
            "com.hikmicro.analyzer.sdk.palette.bean.PaletteBean",
            "hik.common.yyrj.uicommon.data.ModuleType",
            "com.hikvision.microjita.AnalyzerII",
            "com.hikvision.microjita.bean.AnalyzerInfoPic",
            "com.guardexpert.microsensorsdk.MicroJITA",
            "com.guardexpert.microsensorsdk.MicroJITAPrivate",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MicroJITASWIG",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MicroJITASWIGJNI",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasureRule",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementStats",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasurementEnvParams",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MeasureRuleDict",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.MicroSmartSensorDataExtension\$JPEG",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.SharedByteBuffer",
            "com.guardexpert.microsensorsdk.core.microsmartsensordata.Image",
            "com.guardexpert.microsensorsdk.core.microsensorcontroldata.FrameData",
        ).forEach { className -> assertTrue("missing $className", required.contains(className)) }
    }

    @Test
    fun classRoutingIsParentFirstOnlyForRuntimeNamespaces() {
        assertTrue(OfficialDexClassLoader.isParentFirst("java.lang.String"))
        assertTrue(OfficialDexClassLoader.isParentFirst("android.content.Context"))
        assertTrue(OfficialDexClassLoader.isParentFirst("kotlin.Unit"))
        assertFalse(OfficialDexClassLoader.isParentFirst("d3.f"))
        assertTrue(OfficialDexClassLoader.isChildFirst("d3.f"))
        assertTrue(OfficialDexClassLoader.isChildFirst("A5.a"))
        assertTrue(OfficialDexClassLoader.isChildFirst("K2.f"))
        assertTrue(OfficialDexClassLoader.isChildFirst("com.hik.viewercommon.data.bean.TempCallbackBean"))
        assertTrue(OfficialDexClassLoader.isChildFirst("kr.auto.titration.mobile.MainActivity"))
        assertTrue(OfficialDexClassLoader.isRequiredOfficialIdentityClass("d3.f"))
        assertFalse(OfficialDexClassLoader.isRequiredOfficialIdentityClass("kr.auto.titration.mobile.MainActivity"))
    }

    @Test
    fun loaderSourceKeepsVerbatimDexAndReadOnlyInstallContract() {
        val artifactsSource = repoFile("src/main/java/kr/auto/titration/mobile/thermal/officialdex/OfficialDexArtifacts.java").readText()
        assertTrue(artifactsSource.contains("do not D8, smali-reassemble, decompile, or"))
        assertTrue(artifactsSource.contains("CLASSES_SHA256"))
        assertTrue(artifactsSource.contains("CLASSES2_SHA256"))
        assertTrue(artifactsSource.contains("CLASSES3_SHA256"))
        assertTrue(artifactsSource.contains("CLASSES4_SHA256"))

        val installerSource = repoFile("src/main/java/kr/auto/titration/mobile/thermal/officialdex/OfficialDexFileInstaller.java").readText()
        val outputOpen = installerSource.indexOf("new FileOutputStream(destination, false)")
        val markReadOnly = installerSource.indexOf("destination.setReadOnly()")
        val transfer = installerSource.indexOf("transferFrom")
        val force = installerSource.indexOf("force(true)")
        val postWriteHash = installerSource.indexOf("OfficialDexHashing.sha256(destination)", force)
        assertTrue("file output must open before read-only mark", outputOpen >= 0 && outputOpen < markReadOnly)
        assertTrue("read-only mark must happen before writing", markReadOnly >= 0 && markReadOnly < transfer)
        assertTrue("installed dex must be fsynced", transfer < force)
        assertTrue("installed dex must be hash-verified after fsync", force < postWriteHash)
    }

    private fun repoFile(pathFromApp: String): File {
        return listOf(
            File(pathFromApp),
            File("app", pathFromApp),
            File("mobile/android/app", pathFromApp),
        ).firstOrNull { it.exists() } ?: File(pathFromApp)
    }
}
