package g007

import android.content.Context
import android.util.Size
import android.view.SurfaceHolder
import android.view.SurfaceView
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy
import com.hik.thermalplayer.ThermalPlayer
import com.hikmicro.pm_hrl_bussinesscmp.model.FrameInfo
import org.Thermal.PlayM4.Player
import org.Thermal.PlayM4.PlayerCallBack
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.lang.reflect.Modifier

class G007V2RendererClosureTest {
    @Test
    fun rendererClassesKeepTheirOfficialPerClassBackends() {
        assertEquals(
            mapOf("holder" to SurfaceHolder::class.java, "drawer" to W2.a::class.java),
            V2.a::class.java.declaredFields.associate { it.name to it.type },
        )
        assertEquals(
            mapOf("holder" to SurfaceHolder::class.java, "drawer" to W2.a::class.java),
            V2.c::class.java.declaredFields.associate { it.name to it.type },
        )
        assertEquals(SurfaceView::class.java, V2.b::class.java.getDeclaredField("a").type)
        assertEquals(ThermalPlayer::class.java, V2.b::class.java.getDeclaredField("b").type)
        assertEquals("V2.b\$a", V2.b::class.java.getDeclaredField("c").type.name)
        assertEquals(SurfaceView::class.java, V2.d::class.java.getDeclaredField("a").type)
        assertEquals(ThermalPlayer::class.java, V2.d::class.java.getDeclaredField("b").type)
        assertEquals("V2.d\$a", V2.d::class.java.getDeclaredField("c").type.name)
        assertEquals(
            mapOf("surfaceView" to SurfaceView::class.java),
            V2.e::class.java.declaredFields.associate { it.name to it.type },
        )
        assertTrue(runCatching { Class.forName("V2.SurfaceHolderRenderer") }.isFailure)
    }

    @Test
    fun rendererAbiKeepsVoidJAndOfficialFrameInfoShape() {
        listOf(V2.a::class.java, V2.b::class.java, V2.c::class.java, V2.d::class.java, V2.e::class.java).forEach { type ->
            val method = type.getDeclaredMethod(
                "j",
                ByteArray::class.java,
                ByteArray::class.java,
                Size::class.java,
                Int::class.javaPrimitiveType,
                List::class.java,
                android.graphics.Bitmap::class.java,
            )
            assertEquals(Void.TYPE, method.returnType)
        }
        assertTrue(
            FrameInfo::class.java.declaredConstructors.any {
                it.parameterTypes.contentEquals(
                    arrayOf(
                        ByteArray::class.java,
                        Size::class.java,
                        Int::class.javaPrimitiveType,
                        HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO::class.java,
                        Int::class.javaPrimitiveType,
                        Int::class.javaPrimitiveType,
                    ),
                )
            },
        )
    }

    @Test
    fun playerNativeDescriptorsMatchTheOfficialBoundary() {
        val expected = mapOf(
            "AddPicInfo" to listOf(Int::class.javaPrimitiveType, ByteArray::class.java, Int::class.javaPrimitiveType),
            "FreePort" to listOf(Int::class.javaPrimitiveType),
            "GetJPG" to listOf(Int::class.javaPrimitiveType, ByteArray::class.java, Int::class.javaPrimitiveType, Player.MPInteger::class.java),
            "GetJPGEx" to listOf(Int::class.javaPrimitiveType, ByteArray::class.java, Int::class.javaPrimitiveType, Player.MPInteger::class.java, Player.MPInteger::class.java),
            "GetJPGExWithWH" to listOf(Int::class.javaPrimitiveType, ByteArray::class.java, Int::class.javaPrimitiveType, Player.MPInteger::class.java, Player.MPInteger::class.java, Int::class.javaPrimitiveType, Int::class.javaPrimitiveType),
            "GetLastError" to listOf(Int::class.javaPrimitiveType),
            "GetPort" to emptyList(),
            "GetSDKVersion" to emptyList(),
            "InputData" to listOf(Int::class.javaPrimitiveType, ByteArray::class.java, Int::class.javaPrimitiveType),
            "Play" to listOf(Int::class.javaPrimitiveType, android.view.Surface::class.java),
            "SetAddPicInfo" to listOf(Int::class.javaPrimitiveType, Player.PIC_ADD_INFO::class.java),
            "SetAddPicInfoEx" to listOf(Int::class.javaPrimitiveType, Player.PIC_ADD_INFO_EX::class.java),
            "SetDisplayRegion" to listOf(Int::class.javaPrimitiveType, Player.THERMAL_RECT::class.java),
            "SetFontPath" to listOf(Int::class.javaPrimitiveType, ByteArray::class.java),
            "SetFontSize" to listOf(Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, Int::class.javaPrimitiveType),
            "SetImagePostProcessParameter" to listOf(Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, Float::class.javaPrimitiveType),
            "SetPrivateDataType" to listOf(Int::class.javaPrimitiveType, Int::class.javaPrimitiveType),
            "SetVidRecordResolution" to listOf(Int::class.javaPrimitiveType, Int::class.javaPrimitiveType, Int::class.javaPrimitiveType),
            "SetVidRecordSourceType" to listOf(Int::class.javaPrimitiveType, Int::class.javaPrimitiveType),
            "SetVideoFrameCB" to listOf(Int::class.javaPrimitiveType, PlayerCallBack.IHWVideoFrameCB::class.java),
            "StartRecord" to listOf(Int::class.javaPrimitiveType, ByteArray::class.java),
            "Stop" to listOf(Int::class.javaPrimitiveType),
            "StopRecord" to listOf(Int::class.javaPrimitiveType),
            "VerticalFlip" to listOf(Int::class.javaPrimitiveType, Int::class.javaPrimitiveType),
        )
        val nativeMethods = Player::class.java.declaredMethods.filter { Modifier.isNative(it.modifiers) }
        assertEquals(expected.keys, nativeMethods.map { it.name }.toSet())
        nativeMethods.forEach { method ->
            assertTrue(Modifier.isPrivate(method.modifiers))
            assertEquals(Int::class.javaPrimitiveType, method.returnType)
            assertEquals(expected.getValue(method.name), method.parameterTypes.toList())
        }
    }

    @Test
    fun playerConstructorKeepsOfficialNativeLoadOrder() {
        val classBytes = Player::class.java.getResourceAsStream("Player.class")!!.use { it.readBytes() }
        val thermal = classBytes.indexOf("ThermalPlayCtrl".toByteArray())
        val format = classBytes.indexOf("FormatConversion".toByteArray())
        val hardware = classBytes.indexOf("HwCodecer".toByteArray())
        assertTrue(thermal >= 0)
        assertTrue(format > thermal)
        assertTrue(hardware > format)
        assertFalse(Modifier.isStatic(Player::class.java.getDeclaredConstructor().modifiers))
    }

    @Test
    fun thermalPlayerExposesOfficialConstructorsAndCallbackDescriptor() {
        assertTrue(
            ThermalPlayer::class.java.declaredConstructors.any {
                it.parameterTypes.contentEquals(arrayOf(Context::class.java, SurfaceHolder::class.java, Long::class.javaPrimitiveType))
            },
        )
        assertEquals(
            Void.TYPE,
            PlayerCallBack.IHWVideoFrameCB::class.java.getDeclaredMethod(
                "onHWVideoFrame",
                Int::class.javaPrimitiveType,
                Int::class.javaPrimitiveType,
                java.nio.ByteBuffer::class.java,
                Int::class.javaPrimitiveType,
                Int::class.javaPrimitiveType,
                Long::class.javaPrimitiveType,
            ).returnType,
        )
    }

    private fun ByteArray.indexOf(needle: ByteArray): Int {
        outer@ for (index in 0..size - needle.size) {
            for (offset in needle.indices) if (this[index + offset] != needle[offset]) continue@outer
            return index
        }
        return -1
    }
}
