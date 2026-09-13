package com.hcusbsdk

import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_COMMON_COND
import com.hcusbsdk.Interface.USB_CTRL_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_DEVICE_INFO
import com.hcusbsdk.Interface.USB_DEVICE_REG_RES
import com.hcusbsdk.Interface.USB_GET_IMAGE_BRIGHTNESS
import com.hcusbsdk.Interface.USB_GET_IMAGE_CONTRAST
import com.hcusbsdk.Interface.USB_GET_IMAGE_ENHANCEMENT
import com.hcusbsdk.Interface.USB_GET_IMAGE_ENHANCEMENT_V20
import com.hcusbsdk.Interface.USB_IMAGE_BRIGHTNESS
import com.hcusbsdk.Interface.USB_IMAGE_CONTRAST
import com.hcusbsdk.Interface.USB_IMAGE_ENHANCEMENT
import com.hcusbsdk.Interface.USB_IMAGE_ENHANCEMENT_EX
import com.hcusbsdk.Interface.USB_SYSTEM_DEVICE_INFO
import com.hcusbsdk.Interface.USB_THERMAL_STREAM_PARAM
import com.hcusbsdk.Interface.USB_THERMOMETRY_CALIBRATION_FILE
import com.hcusbsdk.Interface.USB_USER_LOGIN_INFO
import com.hcusbsdk.Interface.USB_VIDEO_PARAM
import com.sun.jna.Structure
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class JavaInterfaceImageEnhancementFacadeTest {

    @Test
    fun interfaceDtosExposeOfficialFieldsOnly() {
        assertEquals(listOf("dwBrightness"), publicFields(USB_IMAGE_BRIGHTNESS::class.java))
        assertEquals(listOf("dwContrast"), publicFields(USB_IMAGE_CONTRAST::class.java))
        assertEquals(
            listOf(
                "byAISuperResolution",
                "byBirdWatchingMode",
                "byHighLightLevel",
                "byHighLightMode",
                "byHookEdgeLevel",
                "byHookEdgeMode",
                "byIspAgcMode",
                "byLSEDetailEnabled",
                "byNoiseReduceMode",
                "byPaletteMode",
                "byWideTemperatureMode",
                "byWideTemperatureWork",
                "dwFrameNoiseReduceLevel",
                "dwGeneralLevel",
                "dwInterFrameNoiseReduceLevel",
                "dwLSEDetailLevel",
                "dwWideTemperatureDownThreshold",
                "dwWideTemperatureUpThreshold",
            ),
            publicFields(USB_IMAGE_ENHANCEMENT::class.java),
        )
        assertEquals(
            listOf(
                "byAGCMode",
                "byAutoShutEnabled",
                "byBurnPreventionEnabled",
                "byBurnPreventionMode",
                "byBurnPreventionRecovery",
                "byBurnPreventionShutterControl",
                "byColorAlarmType",
                "byEdgePreservingFilterEnabled",
                "byGaussianFilterEnabled",
                "byGeneralLevelDefault",
                "byGeneralLevelMax",
                "byGeneralLevelMin",
                "byIsothermEnabled",
                "byIsothermalType",
                "byRawDataNoiseReduceEnabled",
                "byRelativeHumidityThreshold",
                "bySharpenBoost",
                "bySkyAreaCullLevel",
                "dwAtmosphericTemperature",
                "dwBilateralFilterEdgeThreshold",
                "dwBilateralFilterRadius",
                "dwBurnPreventionShutterCloseTime",
                "dwColorAlarmLowerLimit",
                "dwColorAlarmUpperLimit",
                "dwGaussianFilterCenterPoint",
                "dwIsothermalLowerThreshold",
                "dwIsothermalUpperThreshold",
                "dwRelativeHumidity",
                "struImageEnhancement",
            ),
            publicFields(USB_IMAGE_ENHANCEMENT_EX::class.java),
        )
    }

    @Test
    fun jnaStructuresExposeOfficialFieldOrderAndSizes() {
        assertFieldOrder<com.hcusbsdk.jna.USB_IMAGE_BRIGHTNESS>("dwSize", "dwBrightness", "byRes")
        assertFieldOrder<com.hcusbsdk.jna.USB_IMAGE_CONTRAST>("dwSize", "dwContrast", "byRes")
        assertFieldOrder<com.hcusbsdk.jna.USB_IMAGE_ENHANCEMENT>(
            "dwSize",
            "byNoiseReduceMode",
            "byBirdWatchingMode",
            "byHighLightMode",
            "byHighLightLevel",
            "dwGeneralLevel",
            "dwFrameNoiseReduceLevel",
            "dwInterFrameNoiseReduceLevel",
            "byPaletteMode",
            "byLSEDetailEnabled",
            "byHookEdgeMode",
            "byHookEdgeLevel",
            "dwLSEDetailLevel",
            "byWideTemperatureMode",
            "byWideTemperatureWork",
            "byIspAgcMode",
            "byAISuperResolution",
            "dwWideTemperatureUpThreshold",
            "dwWideTemperatureDownThreshold",
            "byRes",
        )
        assertFieldOrder<com.hcusbsdk.jna.USB_IMAGE_ENHANCEMENT_EX>(
            "struImageEnhancement",
            "bySkyAreaCullLevel",
            "byAGCMode",
            "byGaussianFilterEnabled",
            "byEdgePreservingFilterEnabled",
            "dwGaussianFilterCenterPoint",
            "dwBilateralFilterRadius",
            "dwBilateralFilterEdgeThreshold",
            "byBurnPreventionEnabled",
            "byBurnPreventionMode",
            "byRelativeHumidityThreshold",
            "bySharpenBoost",
            "dwBurnPreventionShutterCloseTime",
            "byBurnPreventionShutterControl",
            "byBurnPreventionRecovery",
            "byIsothermEnabled",
            "byRawDataNoiseReduceEnabled",
            "dwIsothermalUpperThreshold",
            "dwIsothermalLowerThreshold",
            "byIsothermalType",
            "byColorAlarmType",
            "dwColorAlarmUpperLimit",
            "dwColorAlarmLowerLimit",
            "dwRelativeHumidity",
            "dwAtmosphericTemperature",
            "byAutoShutEnabled",
            "byGeneralLevelDefault",
            "byGeneralLevelMin",
            "byGeneralLevelMax",
            "byRes",
        )
        ensureJnaNativeDispatchAvailable()
        val source = String(
            java.nio.file.Files.readAllBytes(
                java.nio.file.Paths.get("src/main/java/com/hcusbsdk/jna/HCUSBSDKByJNA.kt"),
            ),
        )
        assertTrue(source.contains("class USB_IMAGE_BRIGHTNESS : Structure()"))
        assertTrue(source.contains("class USB_IMAGE_CONTRAST : Structure()"))
        assertTrue(source.contains("class USB_IMAGE_ENHANCEMENT : Structure()"))
        assertTrue(source.contains("class USB_IMAGE_ENHANCEMENT_EX : Structure()"))
        assertStructureSizeAndOffsets(
            com.hcusbsdk.jna.USB_IMAGE_BRIGHTNESS(),
            OFFICIAL_BRIGHTNESS_SIZE,
            mapOf("dwSize" to 0, "dwBrightness" to 4, "byRes" to 8),
        )
        assertStructureSizeAndOffsets(
            com.hcusbsdk.jna.USB_IMAGE_CONTRAST(),
            OFFICIAL_CONTRAST_SIZE,
            mapOf("dwSize" to 0, "dwContrast" to 4, "byRes" to 8),
        )
        assertStructureSizeAndOffsets(
            com.hcusbsdk.jna.USB_IMAGE_ENHANCEMENT(),
            OFFICIAL_BASE_ENHANCEMENT_SIZE,
            mapOf(
                "dwSize" to 0,
                "byNoiseReduceMode" to 4,
                "dwGeneralLevel" to 8,
                "dwFrameNoiseReduceLevel" to 12,
                "dwInterFrameNoiseReduceLevel" to 16,
                "byPaletteMode" to 20,
                "dwLSEDetailLevel" to 24,
                "byWideTemperatureMode" to 28,
                "dwWideTemperatureUpThreshold" to 32,
                "dwWideTemperatureDownThreshold" to 36,
                "byRes" to 40,
            ),
        )
        assertStructureSizeAndOffsets(
            com.hcusbsdk.jna.USB_IMAGE_ENHANCEMENT_EX(),
            OFFICIAL_V20_ENHANCEMENT_SIZE,
            mapOf(
                "struImageEnhancement" to 0,
                "bySkyAreaCullLevel" to 80,
                "dwGaussianFilterCenterPoint" to 84,
                "dwBilateralFilterRadius" to 88,
                "dwBilateralFilterEdgeThreshold" to 92,
                "byBurnPreventionEnabled" to 96,
                "dwBurnPreventionShutterCloseTime" to 100,
                "byBurnPreventionShutterControl" to 104,
                "dwIsothermalUpperThreshold" to 108,
                "dwIsothermalLowerThreshold" to 112,
                "byIsothermalType" to 116,
                "dwColorAlarmUpperLimit" to 120,
                "dwColorAlarmLowerLimit" to 124,
                "dwRelativeHumidity" to 128,
                "dwAtmosphericTemperature" to 132,
                "byAutoShutEnabled" to 136,
                "byRes" to 140,
            ),
        )
        assertEquals(40, com.hcusbsdk.jna.USB_IMAGE_BRIGHTNESS().byRes.size)
        assertEquals(40, com.hcusbsdk.jna.USB_IMAGE_CONTRAST().byRes.size)
        assertEquals(40, com.hcusbsdk.jna.USB_IMAGE_ENHANCEMENT().byRes.size)
        assertEquals(902, com.hcusbsdk.jna.USB_IMAGE_ENHANCEMENT_EX().byRes.size)
    }

    @Test
    fun javaInterfaceFacadeUsesOfficialGetCommandsChannelOneAndCopiesFields() {
        val fake = FakeImageBridge()
        val javaInterface = JavaInterface.getInstance().apply { configureNativeBridge(fake) }

        val brightness = USB_IMAGE_BRIGHTNESS()
        val contrast = USB_IMAGE_CONTRAST()
        val enhancement = USB_IMAGE_ENHANCEMENT()
        val enhancementV20 = USB_IMAGE_ENHANCEMENT_EX()

        assertTrue(javaInterface.USB_GetImageBrightNess(11, brightness))
        assertTrue(javaInterface.USB_GetImageContrast(12, contrast))
        assertTrue(javaInterface.USB_GetImageEnhancement(13, enhancement))
        assertTrue(javaInterface.USB_GetImageEnhancementV20(14, enhancementV20))

        assertEquals(listOf(USB_GET_IMAGE_BRIGHTNESS, USB_GET_IMAGE_CONTRAST, USB_GET_IMAGE_ENHANCEMENT, USB_GET_IMAGE_ENHANCEMENT_V20), fake.commands)
        assertEquals(listOf(11, 12, 13, 14), fake.userIds)
        assertEquals(listOf(1, 1, 1, 1), fake.channels)
        assertEquals(77, brightness.dwBrightness)
        assertEquals(88, contrast.dwContrast)
        assertBaseFields(enhancement)
        assertBaseFields(enhancementV20.struImageEnhancement)
        assertEquals(31, enhancementV20.bySkyAreaCullLevel.toInt())
        assertEquals(32, enhancementV20.byAGCMode.toInt())
        assertEquals(33, enhancementV20.byGaussianFilterEnabled.toInt())
        assertEquals(34, enhancementV20.byEdgePreservingFilterEnabled.toInt())
        assertEquals(35, enhancementV20.dwGaussianFilterCenterPoint)
        assertEquals(36, enhancementV20.dwBilateralFilterRadius)
        assertEquals(37, enhancementV20.dwBilateralFilterEdgeThreshold)
        assertEquals(38, enhancementV20.byBurnPreventionEnabled.toInt())
        assertEquals(39, enhancementV20.byBurnPreventionMode.toInt())
        assertEquals(40, enhancementV20.byRelativeHumidityThreshold.toInt())
        assertEquals(41, enhancementV20.bySharpenBoost.toInt())
        assertEquals(42, enhancementV20.dwBurnPreventionShutterCloseTime)
        assertEquals(43, enhancementV20.byBurnPreventionShutterControl.toInt())
        assertEquals(44, enhancementV20.byBurnPreventionRecovery.toInt())
        assertEquals(45, enhancementV20.byIsothermEnabled.toInt())
        assertEquals(46, enhancementV20.byRawDataNoiseReduceEnabled.toInt())
        assertEquals(47, enhancementV20.dwIsothermalUpperThreshold)
        assertEquals(48, enhancementV20.dwIsothermalLowerThreshold)
        assertEquals(49, enhancementV20.byIsothermalType.toInt())
        assertEquals(50, enhancementV20.byColorAlarmType.toInt())
        assertEquals(51, enhancementV20.dwColorAlarmUpperLimit)
        assertEquals(52, enhancementV20.dwColorAlarmLowerLimit)
        assertEquals(53, enhancementV20.dwRelativeHumidity)
        assertEquals(54, enhancementV20.dwAtmosphericTemperature)
        assertEquals(55, enhancementV20.byAutoShutEnabled.toInt())
        assertEquals(56, enhancementV20.byGeneralLevelDefault.toInt())
        assertEquals(57, enhancementV20.byGeneralLevelMin.toInt())
        assertEquals(58, enhancementV20.byGeneralLevelMax.toInt())
    }


    @Test
    fun javaInterfaceFacadeReturnsFalseOnNullOutputWithoutNativeCall() {
        val fake = FakeImageBridge()
        val javaInterface = JavaInterface.getInstance().apply { configureNativeBridge(fake) }

        assertFalse(javaInterface.USB_GetImageBrightNess(21, null))
        assertFalse(javaInterface.USB_GetImageContrast(22, null))
        assertFalse(javaInterface.USB_GetImageEnhancement(23, null))
        assertFalse(javaInterface.USB_GetImageEnhancementV20(24, null))

        assertEquals(emptyList<Int>(), fake.commands)
        assertEquals(emptyList<Int>(), fake.userIds)
        assertEquals(emptyList<Int>(), fake.channels)
    }

    @Test
    fun javaInterfaceFacadeReturnsFalseWithoutFabricatedValuesOnNativeFailure() {
        val javaInterface = JavaInterface.getInstance().apply { configureNativeBridge(FailingImageBridge) }
        val brightness = USB_IMAGE_BRIGHTNESS().apply { dwBrightness = 123 }
        val contrast = USB_IMAGE_CONTRAST().apply { dwContrast = 124 }
        val enhancement = USB_IMAGE_ENHANCEMENT().apply { dwGeneralLevel = 125 }
        val enhancementV20 = USB_IMAGE_ENHANCEMENT_EX().apply { bySkyAreaCullLevel = 126 }

        assertFalse(javaInterface.USB_GetImageBrightNess(1, brightness))
        assertFalse(javaInterface.USB_GetImageContrast(1, contrast))
        assertFalse(javaInterface.USB_GetImageEnhancement(1, enhancement))
        assertFalse(javaInterface.USB_GetImageEnhancementV20(1, enhancementV20))

        assertEquals(123, brightness.dwBrightness)
        assertEquals(124, contrast.dwContrast)
        assertEquals(125, enhancement.dwGeneralLevel)
        assertEquals(126, enhancementV20.bySkyAreaCullLevel.toInt())
    }

    private fun publicFields(clazz: Class<*>): List<String> = clazz.fields.map { it.name }.sorted()

    private inline fun <reified T : Structure> assertFieldOrder(vararg expected: String) {
        val annotation = T::class.java.getAnnotation(Structure.FieldOrder::class.java)
        assertArrayEquals(expected, annotation!!.value)
    }



    private fun ensureJnaNativeDispatchAvailable() {
        if (!System.getProperty("jna.boot.library.path").isNullOrBlank()) return
        val jar = findCachedDesktopJnaJar() ?: downloadDesktopJnaJar()
        val entryName = "com/sun/jna/linux-x86-64/libjnidispatch.so"
        val outDir = java.nio.file.Files.createTempDirectory("jna-native-dispatch")
        val out = outDir.resolve("libjnidispatch.so")
        java.util.zip.ZipFile(jar.toFile()).use { zip ->
            val entry = zip.getEntry(entryName) ?: throw AssertionError("JNA desktop jar lacks $entryName: $jar")
            zip.getInputStream(entry).use { input ->
                java.nio.file.Files.copy(input, out, java.nio.file.StandardCopyOption.REPLACE_EXISTING)
            }
        }
        System.setProperty("jna.boot.library.path", outDir.toString())
    }

    private fun findCachedDesktopJnaJar(): java.nio.file.Path? {
        val cache = java.nio.file.Paths.get(
            System.getProperty("user.home"),
            ".gradle",
            "caches",
            "modules-2",
            "files-2.1",
            "net.java.dev.jna",
            "jna",
            "5.18.1",
        )
        if (!java.nio.file.Files.isDirectory(cache)) return null
        val stream = java.nio.file.Files.walk(cache)
        return try {
            stream
                .filter { java.nio.file.Files.isRegularFile(it) }
                .filter { it.fileName.toString() == "jna-5.18.1.jar" }
                .findFirst()
                .orElse(null)
        } finally {
            stream.close()
        }
    }

    private fun downloadDesktopJnaJar(): java.nio.file.Path {
        val out = java.nio.file.Files.createTempFile("jna-5.18.1", ".jar")
        val url = java.net.URI("https://repo1.maven.org/maven2/net/java/dev/jna/jna/5.18.1/jna-5.18.1.jar").toURL()
        url.openStream().use { input ->
            java.nio.file.Files.copy(input, out, java.nio.file.StandardCopyOption.REPLACE_EXISTING)
        }
        return out
    }

    private fun assertStructureSizeAndOffsets(
        structure: Structure,
        expectedSize: Int,
        expectedOffsets: Map<String, Int>,
    ) {
        assertEquals(expectedSize, structure.size())
        expectedOffsets.forEach { (fieldName, expectedOffset) ->
            assertEquals("offset for $fieldName", expectedOffset, structure.actualFieldOffset(fieldName))
        }
    }

    private fun Structure.actualFieldOffset(fieldName: String): Int {
        val method = Structure::class.java.getDeclaredMethod("fieldOffset", String::class.java)
        method.isAccessible = true
        return method.invoke(this, fieldName) as Int
    }

    private fun assertBaseFields(value: USB_IMAGE_ENHANCEMENT) {
        assertEquals(1, value.byNoiseReduceMode.toInt())
        assertEquals(2, value.byBirdWatchingMode.toInt())
        assertEquals(3, value.byHighLightMode.toInt())
        assertEquals(4, value.byHighLightLevel.toInt())
        assertEquals(5, value.dwGeneralLevel)
        assertEquals(6, value.dwFrameNoiseReduceLevel)
        assertEquals(7, value.dwInterFrameNoiseReduceLevel)
        assertEquals(8, value.byPaletteMode.toInt())
        assertEquals(9, value.byLSEDetailEnabled.toInt())
        assertEquals(10, value.byHookEdgeMode.toInt())
        assertEquals(11, value.byHookEdgeLevel.toInt())
        assertEquals(12, value.dwLSEDetailLevel)
        assertEquals(13, value.byWideTemperatureMode.toInt())
        assertEquals(14, value.byWideTemperatureWork.toInt())
        assertEquals(15, value.byIspAgcMode.toInt())
        assertEquals(16, value.byAISuperResolution.toInt())
        assertEquals(17, value.dwWideTemperatureUpThreshold)
        assertEquals(18, value.dwWideTemperatureDownThreshold)
    }

    private open class MinimalBridge : JavaInterface.NativeBridge {
        override fun USB_Init(): Boolean = true
        override fun USB_Cleanup(): Boolean = true
        override fun USB_GetLastError(): Int = 0
        override fun USB_GetDeviceCount(): Int = 0
        override fun USB_EnumDevices_C(count: Int, devices: Array<USB_DEVICE_INFO>): Boolean = false
        override fun USB_Login(loginInfo: USB_USER_LOGIN_INFO, deviceRegRes: USB_DEVICE_REG_RES): Int = -1
        override fun USB_GetSysTemDeviceInfo(userId: Int, info: USB_SYSTEM_DEVICE_INFO): Boolean = false
        override fun USB_GetThermometryCalibrationFile(userId: Int, cond: USB_COMMON_COND, out: USB_THERMOMETRY_CALIBRATION_FILE): Boolean = false
        override fun USB_SetVideoParam(userId: Int, param: USB_VIDEO_PARAM): Boolean = false
        override fun USB_SetThermalStreamParam(userId: Int, param: USB_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_GetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_SetThermalStreamCtrl(userId: Int, param: USB_CTRL_THERMAL_STREAM_PARAM): Boolean = false
        override fun USB_StopChannel(userId: Int, channel: Int): Boolean = false
        override fun USB_Logout(userId: Int): Boolean = false
    }

    private class FakeImageBridge : MinimalBridge() {
        val commands = mutableListOf<Int>()
        val userIds = mutableListOf<Int>()
        val channels = mutableListOf<Int>()

        override fun USB_GetImageBrightNess(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_BRIGHTNESS): Boolean {
            record(userId, USB_GET_IMAGE_BRIGHTNESS, cond)
            out.dwBrightness = 77
            return true
        }

        override fun USB_GetImageContrast(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_CONTRAST): Boolean {
            record(userId, USB_GET_IMAGE_CONTRAST, cond)
            out.dwContrast = 88
            return true
        }

        override fun USB_GetImageEnhancement(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT): Boolean {
            record(userId, USB_GET_IMAGE_ENHANCEMENT, cond)
            fillBase(out)
            return true
        }

        override fun USB_GetImageEnhancementV20(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT_EX): Boolean {
            record(userId, USB_GET_IMAGE_ENHANCEMENT_V20, cond)
            fillEx(out)
            return true
        }

        private fun record(userId: Int, command: Int, cond: USB_COMMON_COND) {
            userIds += userId
            commands += command
            channels += cond.byChannelID.toInt()
        }
    }

    private object FailingImageBridge : MinimalBridge() {
        override fun USB_GetImageBrightNess(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_BRIGHTNESS): Boolean = false
        override fun USB_GetImageContrast(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_CONTRAST): Boolean = false
        override fun USB_GetImageEnhancement(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT): Boolean = false
        override fun USB_GetImageEnhancementV20(userId: Int, cond: USB_COMMON_COND, out: USB_IMAGE_ENHANCEMENT_EX): Boolean = false
    }

    companion object {
        private const val OFFICIAL_BRIGHTNESS_SIZE = 48
        private const val OFFICIAL_CONTRAST_SIZE = 48
        private const val OFFICIAL_BASE_ENHANCEMENT_SIZE = 80
        private const val OFFICIAL_V20_ENHANCEMENT_SIZE = 1044

        private fun fillBase(out: USB_IMAGE_ENHANCEMENT) {
            out.byNoiseReduceMode = 1
            out.byBirdWatchingMode = 2
            out.byHighLightMode = 3
            out.byHighLightLevel = 4
            out.dwGeneralLevel = 5
            out.dwFrameNoiseReduceLevel = 6
            out.dwInterFrameNoiseReduceLevel = 7
            out.byPaletteMode = 8
            out.byLSEDetailEnabled = 9
            out.byHookEdgeMode = 10
            out.byHookEdgeLevel = 11
            out.dwLSEDetailLevel = 12
            out.byWideTemperatureMode = 13
            out.byWideTemperatureWork = 14
            out.byIspAgcMode = 15
            out.byAISuperResolution = 16
            out.dwWideTemperatureUpThreshold = 17
            out.dwWideTemperatureDownThreshold = 18
        }

        private fun fillEx(out: USB_IMAGE_ENHANCEMENT_EX) {
            fillBase(out.struImageEnhancement)
            out.bySkyAreaCullLevel = 31
            out.byAGCMode = 32
            out.byGaussianFilterEnabled = 33
            out.byEdgePreservingFilterEnabled = 34
            out.dwGaussianFilterCenterPoint = 35
            out.dwBilateralFilterRadius = 36
            out.dwBilateralFilterEdgeThreshold = 37
            out.byBurnPreventionEnabled = 38
            out.byBurnPreventionMode = 39
            out.byRelativeHumidityThreshold = 40
            out.bySharpenBoost = 41
            out.dwBurnPreventionShutterCloseTime = 42
            out.byBurnPreventionShutterControl = 43
            out.byBurnPreventionRecovery = 44
            out.byIsothermEnabled = 45
            out.byRawDataNoiseReduceEnabled = 46
            out.dwIsothermalUpperThreshold = 47
            out.dwIsothermalLowerThreshold = 48
            out.byIsothermalType = 49
            out.byColorAlarmType = 50
            out.dwColorAlarmUpperLimit = 51
            out.dwColorAlarmLowerLimit = 52
            out.dwRelativeHumidity = 53
            out.dwAtmosphericTemperature = 54
            out.byAutoShutEnabled = 55
            out.byGeneralLevelDefault = 56
            out.byGeneralLevelMin = 57
            out.byGeneralLevelMax = 58
        }

    }
}
