package kr.auto.titration.mobile.thermal

import android.util.Size
import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.Interface.JavaInterface
import com.hcusbsdk.Interface.USB_DEVICE_INFO
import com.hcusbsdk.Interface.USB_DEVICE_REG_RES
import com.hcusbsdk.Interface.USB_USER_LOGIN_INFO
import com.hcusbsdk.jna.HCUSBSDK
import com.hcusbsdk.jna.HCUSBSDKByJNA
import com.hcusbsdk.jna.USB_CONFIG_INPUT_INFO as JnaUSB_CONFIG_INPUT_INFO
import com.hcusbsdk.jna.USB_CTRL_THERMAL_STREAM_PARAM as JnaUSB_CTRL_THERMAL_STREAM_PARAM
import com.hcusbsdk.jna.USB_STREAM_CALLBACK_PARAM as JnaUSB_STREAM_CALLBACK_PARAM
import com.hcusbsdk.jna.USB_THERMAL_STREAM_PARAM as JnaUSB_THERMAL_STREAM_PARAM
import com.hcusbsdk.jna.USB_VIDEO_PARAM as JnaUSB_VIDEO_PARAM
import com.hik.f2module.F2UsbModuleHelper
import com.hik.f2module.HIKMICRO_FRAME_RATE
import com.hik.f2module.HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE
import com.hik.f2module.HIKMICRO_PREVIEW_HEIGHT
import com.hik.f2module.HIKMICRO_PREVIEW_WIDTH
import com.hik.f2module.HIKMICRO_THERMAL_VIDEO_CODING_TYPE
import com.sun.jna.Pointer
import com.sun.jna.Structure
import java.io.File
import java.lang.reflect.InvocationHandler
import java.lang.reflect.Proxy
import java.net.URLClassLoader
import java.nio.file.Files
import java.util.concurrent.TimeUnit
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class F2OfficialBehaviorTraceTest {
    private val javaInterface = JavaInterface.getInstance()
    private val helper = F2UsbModuleHelper.INSTANCE
    private lateinit var traceSdk: TraceHcUsbSdk

    @Before
    fun installTraceSdk() {
        installJnaDispatchForHostUnitTest()
        traceSdk = TraceHcUsbSdk()
        val fakeSdk = traceSdk.proxy()
        setHcUsbSdkInstance(fakeSdk)
        javaInterface.configureNativeBridge(JavaInterface.JnaNativeBridge(fakeSdk))
        helper.installSessionCloseOperationsForTests(
            stopChannel = { _, _ -> true },
            logout = { _ -> true },
        )
        helper.closeSession()
        setHelperProfile(HikmicroF2ProfileResolver.resolve("0953060001", "APP_010203_20240101"))
        F2UsbModuleHelper.userId = -1
        F2UsbModuleHelper.channel = -1
    }

    @After
    fun resetTraceSdk() {
        helper.closeSession()
        F2UsbModuleHelper.userId = -1
        F2UsbModuleHelper.channel = -1
        setHelperProfile(null)
        helper.installSessionCloseOperationsForTests(stopChannel = null, logout = null)
        javaInterface.resetJniStartStreamCallbackInvokerForTest()
        setHcUsbSdkInstance(null)
    }

    @Test
    fun fakeNativeTraceShowsSingleF2StartAttemptInOfficialOrderWithoutFormatLadder() {
        assertTrue(javaInterface.USB_Init())
        val devices = Array(1) { USB_DEVICE_INFO() }
        assertTrue(javaInterface.USB_EnumDevices_C(1, devices))
        val userId = javaInterface.USB_Login(
            USB_USER_LOGIN_INFO().apply {
                dwTimeout = 5_000
                dwDevIndex = devices[0].dwIndex
                dwVID = devices[0].dwVID
                dwPID = devices[0].dwPID
                dwFd = devices[0].dwFd
            },
            USB_DEVICE_REG_RES(),
        )
        F2UsbModuleHelper.userId = userId

        val result = helper.startStreamPreviewJNA(
            fStreamCallBack = HCUSBSDKByJNA.FStreamCallBack { _, _, _ -> },
            size = hostAndroidSize(HIKMICRO_PREVIEW_WIDTH, HIKMICRO_PREVIEW_HEIGHT),
            frameRate = HIKMICRO_FRAME_RATE,
            videoCodingType = HIKMICRO_THERMAL_VIDEO_CODING_TYPE,
            streamType = HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE,
            streamingNew = true,
        )

        assertTrue(result.ok)
        assertTrue(result.waitingForFrame)
        assertEquals(1, result.channel)
        assertEquals("stream_attempt_started", result.reason)
        assertEquals(3, F2UsbModuleHelper.channel)
        assertEquals(
            listOf(
                "USB_Init",
                "USB_EnumDevices_C:1",
                "USB_Login",
                "USB_SetDeviceConfig:3004",
                "USB_StartStreamCallback:103",
                "USB_SetDeviceConfig:2039",
                "USB_SetDeviceConfig:2111",
            ),
            traceSdk.events,
        )
        assertEquals(1, traceSdk.events.count { it.startsWith("USB_StartStreamCallback") })
        assertEquals(listOf(3004, 2039, 2111), traceSdk.setConfigCommands)
        assertEquals(
            listOf(listOf(HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE, 256, 344, 25)),
            traceSdk.videoParams,
        )
        assertEquals(listOf(HIKMICRO_THERMAL_VIDEO_CODING_TYPE), traceSdk.thermalCodingTypes)
        assertEquals(listOf(1), traceSdk.thermalCtrlValues)
        assertEquals(listOf(HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE), traceSdk.startStreamTypes)
        assertFalse(traceSdk.events.any { it.contains("102944") || it.contains("format_ladder") || it.contains("diagnostic") })
        assertTrue(result.stageReport.contains("startStreamPreviewJNA resultCode=1 channel=3 streamingNew=true"))
    }

    @Test
    fun interfaceStartKeepsOfficialJniOrderChannelZeroAndThermalControlDelay() {
        F2UsbModuleHelper.userId = 7
        setHelperProfile(HikmicroF2ProfileResolver.resolve("0953060001", "APP_010203_20240101"))
        setHelperField("selectedDeviceInfo", USB_DEVICE_INFO().apply {
            dwIndex = 1
            dwVID = 11231
            dwPID = 257
            dwFd = 55
            szDeviceName = "Mini2"
        })
        val callback = FStreamCallBack { _, _ -> }
        var observedJniStreamType = -1
        var observedJniSize = -1
        var observedJniUserId = -1
        var observedJniCallback: com.hcusbsdk.jni.StreamCallBack_JNI? = null
        javaInterface.jniStartStreamCallbackInvoker = JavaInterface.JniStartStreamCallbackInvoker { userId, jniParam, jniCallback ->
            traceSdk.events += "USB_StartStreamCallback_JNI:${jniParam.dwStreamType}"
            observedJniUserId = userId
            observedJniStreamType = jniParam.dwStreamType
            observedJniSize = jniParam.dwSize
            observedJniCallback = jniCallback
            0
        }

        val startedAt = System.nanoTime()
        val result = helper.startStreamPreview(
            fStreamCallBack = callback,
            size = hostAndroidSize(HIKMICRO_PREVIEW_WIDTH, HIKMICRO_PREVIEW_HEIGHT),
            frameRate = HIKMICRO_FRAME_RATE,
            videoCodingType = HIKMICRO_THERMAL_VIDEO_CODING_TYPE,
            streamType = HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE,
            streamingNew = true,
        )
        val elapsedMs = TimeUnit.NANOSECONDS.toMillis(System.nanoTime() - startedAt)

        assertTrue(result.ok)
        assertTrue(result.waitingForFrame)
        assertEquals("F2StartResult.channel carries the production result code", 1, result.channel)
        assertEquals(0, F2UsbModuleHelper.channel)
        assertEquals(55, helper.activeSelectedFd())
        assertEquals(7, observedJniUserId)
        assertEquals(HIKMICRO_OFFICIAL_PRIMARY_STREAM_TYPE, observedJniStreamType)
        assertEquals(0, observedJniSize)
        assertNotSame(
            "each start must pass a registration-scoped JNI wrapper so a late callback cannot enter a replacement session",
            javaInterface.m_fnStreamCallBack_jni,
            observedJniCallback,
        )
        assertSame(callback, javaInterface.m_fnStreamCallBack[7])
        assertSame(callback, helperPrivateField("callbackKeepAlive"))
        assertEquals(
            listOf(
                "USB_SetDeviceConfig:3004",
                "USB_StartStreamCallback_JNI:103",
                "USB_SetDeviceConfig:2039",
                "USB_SetDeviceConfig:2111",
            ),
            traceSdk.events,
        )
        assertEquals(listOf(3004, 2039, 2111), traceSdk.setConfigCommands)
        assertTrue("thermal stream control must remain after the official 100ms wait", elapsedMs >= 90L)
        assertTrue(result.stageReport.contains("USB_StartStreamCallback=ok channel=0"))
        assertTrue(result.stageReport.contains("USB_SET_THERMAL_STREAM_PARAM=ok"))
        assertTrue(result.stageReport.contains("USB_SET_THERMAL_STREAM_CTRL=ok enable=true"))

        helper.closeSession()
        assertEquals(-1, helper.activeSelectedFd())
        assertEquals(-1, F2UsbModuleHelper.userId)
        assertEquals(-1, F2UsbModuleHelper.channel)
        assertEquals(null, javaInterface.m_fnStreamCallBack[7])
        assertEquals(null, helperPrivateField("callbackKeepAlive"))
    }

    private fun hostAndroidSize(width: Int, height: Int): Size {
        val root = Files.createTempDirectory("f2-host-size-")
        root.toFile().deleteOnExit()
        val source = root.resolve("HostAndroidSize.java")
        source.toFile().writeText(
            """
                package kr.auto.titration.mobile.thermal.host;

                public final class HostAndroidSize extends android.util.Size {
                    private final int hostWidth;
                    private final int hostHeight;

                    public HostAndroidSize(int width, int height) {
                        super(width, height);
                        this.hostWidth = width;
                        this.hostHeight = height;
                    }

                    @Override public int getWidth() { return hostWidth; }
                    @Override public int getHeight() { return hostHeight; }
                }
            """.trimIndent(),
        )
        val codeSource = requireNotNull(Size::class.java.protectionDomain?.codeSource) {
            "F2 behavior trace requires android.util.Size host class location"
        }
        val androidHostJar = File(codeSource.location.toURI())
        val javac = File(System.getProperty("java.home"), "bin/javac")
        require(javac.isFile) { "F2 behavior trace requires a JDK; javac missing at $javac" }
        val compiler = ProcessBuilder(
            javac.absolutePath,
            "-classpath",
            androidHostJar.absolutePath,
            "-d",
            root.toString(),
            source.toString(),
        ).redirectErrorStream(true).start()
        val compilerOutput = compiler.inputStream.bufferedReader().use { it.readText() }
        val compileExit = compiler.waitFor()
        require(compileExit == 0) {
            "Unable to compile host Android Size adapter (javac exit=$compileExit): $compilerOutput"
        }
        return URLClassLoader(arrayOf(root.toUri().toURL()), Size::class.java.classLoader).use { loader ->
            Class.forName("kr.auto.titration.mobile.thermal.host.HostAndroidSize", true, loader)
                .asSubclass(Size::class.java)
                .getConstructor(Int::class.javaPrimitiveType, Int::class.javaPrimitiveType)
                .newInstance(width, height)
        }
    }

    private fun setHelperProfile(profile: HikmicroF2ProfileResolution?) {
        val field = F2UsbModuleHelper::class.java.getDeclaredField("selectedProfileResolution")
        field.isAccessible = true
        field.set(helper, profile)
    }

    private fun setHelperField(name: String, value: Any?) {
        val field = F2UsbModuleHelper::class.java.getDeclaredField(name)
        field.isAccessible = true
        field.set(helper, value)
    }

    private fun helperPrivateField(name: String): Any? {
        val field = F2UsbModuleHelper::class.java.getDeclaredField(name)
        field.isAccessible = true
        return field.get(helper)
    }

    private fun setHcUsbSdkInstance(instance: HCUSBSDKByJNA?) {
        val field = HCUSBSDK::class.java.getDeclaredField("instance")
        field.isAccessible = true
        field.set(null, instance)
    }

    private fun installJnaDispatchForHostUnitTest() {
        if (!System.getProperty("jna.boot.library.path").isNullOrBlank()) return
        val archDirectory = when (System.getProperty("os.arch")) {
            "amd64", "x86_64" -> "linux-x86-64"
            else -> return
        }
        val resource = "/com/sun/jna/$archDirectory/libjnidispatch-$archDirectory.bin"
        val tempDirectory = Files.createTempDirectory("jna-host-unit-").toFile()
        tempDirectory.deleteOnExit()
        val tempFile = tempDirectory.resolve("libjnidispatch.so")
        tempFile.deleteOnExit()
        F2OfficialBehaviorTraceTest::class.java.getResourceAsStream(resource).use { input ->
            requireNotNull(input) { "Missing host JNA dispatch resource $resource" }
            tempFile.outputStream().use { output -> input.copyTo(output) }
        }
        System.setProperty("jna.boot.library.path", tempDirectory.absolutePath)
    }

    private class TraceHcUsbSdk : InvocationHandler {
        val events = mutableListOf<String>()
        val setConfigCommands = mutableListOf<Int>()
        val videoParams = mutableListOf<List<Int>>()
        val thermalCodingTypes = mutableListOf<Int>()
        val thermalCtrlValues = mutableListOf<Int>()
        val startStreamTypes = mutableListOf<Int>()

        fun proxy(): HCUSBSDKByJNA = Proxy.newProxyInstance(
            HCUSBSDKByJNA::class.java.classLoader,
            arrayOf(HCUSBSDKByJNA::class.java),
            this,
        ) as HCUSBSDKByJNA

        override fun invoke(proxy: Any, method: java.lang.reflect.Method, args: Array<out Any?>?): Any? {
            return when (method.name) {
                "USB_Init" -> {
                    events += "USB_Init"
                    true
                }
                "USB_Cleanup" -> true
                "USB_GetLastError" -> 0
                "USB_GetDeviceCount" -> 1
                "USB_EnumDevices" -> {
                    events += "USB_EnumDevices_C:${args?.get(0)}"
                    @Suppress("UNCHECKED_CAST")
                    val devices = args?.get(1) as Array<com.hcusbsdk.jna.USB_DEVICE_INFO>
                    devices[0].dwSize = devices[0].size()
                    devices[0].dwIndex = 1
                    devices[0].dwVID = 11231
                    devices[0].dwPID = 257
                    devices[0].szDeviceName.fillAscii("Mini2")
                    devices[0].write()
                    true
                }
                "USB_Login" -> {
                    events += "USB_Login"
                    7
                }
                "USB_SetDeviceConfig" -> {
                    val command = args?.get(1) as Int
                    setConfigCommands += command
                    events += "USB_SetDeviceConfig:$command"
                    recordConfig(command, args[2] as Pointer)
                    true
                }
                "USB_GetDeviceConfig" -> true
                "USB_StartStreamCallback" -> {
                    val callbackParam = Structure.newInstance(
                        JnaUSB_STREAM_CALLBACK_PARAM::class.java,
                        args?.get(1) as Pointer,
                    ).apply { read() }
                    startStreamTypes += callbackParam.dwStreamType
                    events += "USB_StartStreamCallback:${callbackParam.dwStreamType}"
                    3
                }
                "USB_StopChannel" -> true
                "USB_Logout" -> true
                "toString" -> "TraceHcUsbSdk"
                "hashCode" -> System.identityHashCode(proxy)
                "equals" -> proxy === args?.get(0)
                else -> error("Unexpected HCUSBSDK method ${method.name}")
            }
        }

        private fun recordConfig(command: Int, inputPointer: Pointer) {
            val input = Structure.newInstance(JnaUSB_CONFIG_INPUT_INFO::class.java, inputPointer).apply { read() }
            val payload = requireNotNull(input.lpInBuffer) { "USB_SetDeviceConfig command=$command missing payload" }
            when (command) {
                3004 -> {
                    val video = Structure.newInstance(JnaUSB_VIDEO_PARAM::class.java, payload).apply { read() }
                    videoParams += listOf(video.dwVideoFormat, video.dwWidth, video.dwHeight, video.dwFramerate)
                }
                2039 -> {
                    val thermal = Structure.newInstance(JnaUSB_THERMAL_STREAM_PARAM::class.java, payload).apply { read() }
                    thermalCodingTypes += thermal.byVideoCodingType.toInt()
                }
                2111 -> {
                    val control = Structure.newInstance(JnaUSB_CTRL_THERMAL_STREAM_PARAM::class.java, payload).apply { read() }
                    thermalCtrlValues += control.byEnable.toInt()
                }
            }
        }
    }
}

private fun ByteArray.fillAscii(value: String) {
    fill(0)
    value.encodeToByteArray().copyInto(this, endIndex = minOf(size, value.length))
}
