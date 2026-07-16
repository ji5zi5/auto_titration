package org.Thermal.PlayM4

import android.graphics.SurfaceTexture
import android.view.Surface
import android.view.SurfaceHolder
import java.nio.ByteBuffer

/** Exact Java/JNI surface recovered from Viewer 2.6.0. */
class Player {
    init {
        System.loadLibrary("ThermalPlayCtrl")
        System.loadLibrary("FormatConversion")
        System.loadLibrary("HwCodecer")
    }

    private external fun AddPicInfo(port: Int, data: ByteArray?, size: Int): Int
    private external fun FreePort(port: Int): Int
    private external fun GetJPG(port: Int, buffer: ByteArray?, size: Int, outSize: MPInteger): Int
    private external fun GetJPGEx(
        port: Int,
        buffer: ByteArray?,
        size: Int,
        outSize: MPInteger,
        frameTime: MPInteger,
    ): Int
    private external fun GetJPGExWithWH(
        port: Int,
        buffer: ByteArray?,
        size: Int,
        outSize: MPInteger,
        frameTime: MPInteger,
        width: Int,
        height: Int,
    ): Int
    private external fun GetLastError(port: Int): Int
    private external fun GetPort(): Int
    private external fun GetSDKVersion(): Int
    private external fun InputData(port: Int, data: ByteArray, size: Int): Int
    private external fun Play(port: Int, surface: Surface?): Int
    private external fun SetAddPicInfo(port: Int, info: PIC_ADD_INFO): Int
    private external fun SetAddPicInfoEx(port: Int, info: PIC_ADD_INFO_EX): Int
    private external fun SetDisplayRegion(port: Int, rect: THERMAL_RECT): Int
    private external fun SetFontPath(port: Int, path: ByteArray?): Int
    private external fun SetFontSize(port: Int, width: Int, height: Int): Int
    private external fun SetImagePostProcessParameter(port: Int, type: Int, value: Float): Int
    private external fun SetPrivateDataType(port: Int, type: Int): Int
    private external fun SetVidRecordResolution(port: Int, width: Int, height: Int): Int
    private external fun SetVidRecordSourceType(port: Int, type: Int): Int
    private external fun SetVideoFrameCB(port: Int, callback: PlayerCallBack.IHWVideoFrameCB?): Int
    private external fun StartRecord(port: Int, path: ByteArray?): Int
    private external fun Stop(port: Int): Int
    private external fun StopRecord(port: Int): Int
    private external fun VerticalFlip(port: Int, enabled: Int): Int

    fun addPicInfo(port: Int, data: ByteArray?, size: Int): Boolean = AddPicInfo(port, data, size) != PLAYM4_FAIL
    fun freePort(port: Int): Boolean = FreePort(port) != PLAYM4_FAIL
    fun getJPG(port: Int, buffer: ByteArray?, size: Int, outSize: MPInteger): Boolean =
        GetJPG(port, buffer, size, outSize) != PLAYM4_FAIL
    fun getJPGEx(port: Int, buffer: ByteArray?, size: Int, outSize: MPInteger, frameTime: MPInteger): Boolean =
        GetJPGEx(port, buffer, size, outSize, frameTime) != PLAYM4_FAIL
    fun getJPGExWithWH(
        port: Int,
        buffer: ByteArray?,
        size: Int,
        outSize: MPInteger,
        frameTime: MPInteger,
        width: Int,
        height: Int,
    ): Boolean = GetJPGExWithWH(port, buffer, size, outSize, frameTime, width, height) != PLAYM4_FAIL
    fun getLastError(port: Int): Int = GetLastError(port)
    fun getPort(): Int = GetPort()
    fun getSDKVersion(): Int = GetSDKVersion()
    fun inputData(port: Int, data: ByteArray, size: Int): Boolean = InputData(port, data, size) != PLAYM4_FAIL

    fun play(port: Int, holder: SurfaceHolder?): Boolean {
        val surface = holder?.surface
        if (holder != null && (surface == null || !surface.isValid)) return false
        return Play(port, surface) != PLAYM4_FAIL
    }

    fun playEx(port: Int, surfaceTexture: SurfaceTexture?): Boolean {
        val surface = surfaceTexture?.let(::Surface)
        if (surface != null && !surface.isValid) return false
        return Play(port, surface) != PLAYM4_FAIL
    }

    fun setAddPicInfo(port: Int, info: PIC_ADD_INFO): Boolean = SetAddPicInfo(port, info) != PLAYM4_FAIL
    fun setAddPicInfoEx(port: Int, info: PIC_ADD_INFO_EX): Boolean = SetAddPicInfoEx(port, info) == PLAYM4_OK
    fun setDisplayRegion(port: Int, rect: THERMAL_RECT): Boolean = SetDisplayRegion(port, rect) == PLAYM4_OK
    fun setFontPath(port: Int, path: String?): Boolean = SetFontPath(port, path.nullTerminatedBytes()) != PLAYM4_FAIL
    fun setFontSize(port: Int, width: Int, height: Int): Boolean = SetFontSize(port, width, height) != PLAYM4_FAIL
    fun setImagePostProcessParameter(port: Int, type: Int, value: Float): Boolean =
        SetImagePostProcessParameter(port, type, value) == PLAYM4_OK
    fun setPrivateDataType(port: Int, type: Int): Boolean = SetPrivateDataType(port, type) != PLAYM4_FAIL
    fun setVidRecordResolution(port: Int, width: Int, height: Int): Boolean =
        SetVidRecordResolution(port, width, height) != PLAYM4_FAIL
    fun setVidRecordSourceType(port: Int, type: Int): Boolean = SetVidRecordSourceType(port, type) != PLAYM4_FAIL
    fun setVideoFrameCB(port: Int, callback: PlayerCallBack.IHWVideoFrameCB?): Boolean =
        SetVideoFrameCB(port, callback) != PLAYM4_FAIL
    fun startRecord(port: Int, path: String?): Boolean = StartRecord(port, path.nullTerminatedBytes()) != PLAYM4_FAIL
    fun stop(port: Int): Boolean = Stop(port) != PLAYM4_FAIL
    fun stopRecord(port: Int): Boolean = StopRecord(port) != PLAYM4_FAIL
    fun verticalFlip(port: Int, enabled: Int): Boolean = VerticalFlip(port, enabled) != PLAYM4_FAIL

    class MPInteger {
        @JvmField var value: Int = 0
    }

    class IMAGE_POST_PROCESS_TYPE {
        companion object {
            @JvmField var IMAGE_POST_PROCESS_TYPE_NONE = 0
            @JvmField var IMAGE_POST_PROCESS_TYPE_BRIGHTNESS = 1
            @JvmField var IMAGE_POST_PROCESS_TYPE_HUE = 2
            @JvmField var IMAGE_POST_PROCESS_TYPE_SATURATION = 3
            @JvmField var IMAGE_POST_PROCESS_TYPE_CONTRAST = 4
            @JvmField var IMAGE_POST_PROCESS_TYPE_SHARPNESS = 5
            @JvmField var IMAGE_POST_PROCESS_TYPE_DILATE = 6
            @JvmField var IMAGE_POST_PROCESS_TYPE_WHITEN = 7
            @JvmField var IMAGE_POST_PROCESS_TYPE_RUDDY = 8
            @JvmField var IMAGE_POST_PROCESS_TYPE_SMOOTH = 9
        }
    }

    class PIC_ADD_LEVEL {
        companion object {
            @JvmField var PIC_ADD_LEVEL_1 = 0
            @JvmField var PIC_ADD_LEVEL_2 = 1
        }
    }

    class PIC_ADD_TYPE {
        companion object {
            @JvmField var PIC_ADD_TYPE_JPEG = 1
            @JvmField var PIC_ADD_RGBA32_TYPE = 2
            @JvmField var PIC_ADD_RGB565_TYPE = 3
            @JvmField var PIC_ADD_YV12_TYPE = 4
            @JvmField var PIC_ADD_NV12_TYPE = 5
        }
    }

    class PIC_TYPE {
        companion object {
            @JvmField var PIC_TYPE_EZVIZ_LOGO = 1
            @JvmField var PIC_TYPE_PSEUDO_COLOR = 2
            @JvmField var PIC_TYPE_RETICLE = 3
            @JvmField var PIC_TYPE_TextOSD = 4
        }
    }

    class RECORD_SOURCE_TYPE {
        companion object {
            @JvmField var RECORD_SOURCE_NV12 = 1
            @JvmField var RECORD_SOURCE_I420 = 2
        }
    }

    class VRRECTF {
        @JvmField var fBottom = 0f
        @JvmField var fLeft = 0f
        @JvmField var fRight = 0f
        @JvmField var fTop = 0f
    }

    class THERMAL_RECT {
        @JvmField var bottom = 0
        @JvmField var left = 0
        @JvmField var right = 0
        @JvmField var top = 0
    }

    class PIC_ADD_INFO {
        @JvmField var bPicAdd = 0
        @JvmField var bypDataBuf: ByteArray? = null
        @JvmField var nDataLen = 0
        @JvmField var nPicHeight = 0
        @JvmField var nPicWidth = 0
        @JvmField var pic_add_type = 0
        @JvmField var pic_type = 0
        @JvmField var stMaxtemRect: VRRECTF? = null
        @JvmField var stMintemRect: VRRECTF? = null
        @JvmField var stPicRect: VRRECTF? = null
    }

    class PIC_ADD_INFO_EX {
        @JvmField var bPicAdd = false
        @JvmField var bypDataBuf: ByteArray? = null
        @JvmField var fAlpha = 0f
        @JvmField var nDataLen = 0
        @JvmField var nPicHeight = 0
        @JvmField var nPicWidth = 0
        @JvmField var pic_add_level = 0
        @JvmField var pic_add_type = 0
        @JvmField var pic_id = 0
        @JvmField var pic_type = 0
        @JvmField var stPicRect: VRRECTF? = null
    }

    companion object {
        const val PLAYM4_FAIL = 0
        const val PLAYM4_OK = 1
        private var mPlayer: Player? = null

        @JvmStatic
        fun getInstance(): Player {
            if (mPlayer == null) mPlayer = Player()
            return mPlayer!!
        }
    }
}

class PlayerCallBack {
    interface IHWVideoFrameCB {
        fun onHWVideoFrame(port: Int, type: Int, byteBuffer: ByteBuffer, width: Int, height: Int, timestamp: Long)
    }
}

private fun String?.nullTerminatedBytes(): ByteArray? = this?.toByteArray()?.let { it.copyOf(it.size + 1) }
