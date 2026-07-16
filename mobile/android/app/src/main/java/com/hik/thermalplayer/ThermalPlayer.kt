package com.hik.thermalplayer

import android.content.Context
import android.graphics.Bitmap
import android.graphics.RectF
import android.util.Size
import android.util.SparseArray
import android.view.SurfaceHolder
import com.hik.library.player.a
import com.hik.library.player.d
import org.Thermal.PlayM4.Player
import org.Thermal.PlayM4.PlayerCallBack
import java.io.File
import java.nio.ByteBuffer

/** Official ThermalPlayer Java-side port and JNI handoff. */
class ThermalPlayer @JvmOverloads constructor(
    private val context: Context,
    private val surfaceHolder: SurfaceHolder,
    private val timeoutInMillis: Long = 10_000L,
) : a(surfaceHolder, timeoutInMillis) {
    private val colorArray = SparseArray<String>()
    private val videoFrameCB = object : PlayerCallBack.IHWVideoFrameCB {
        override fun onHWVideoFrame(
            port: Int,
            type: Int,
            byteBuffer: ByteBuffer,
            width: Int,
            height: Int,
            timestamp: Long,
        ) {
            q2.b.a().g(byteBuffer, width, height, timestamp)
        }
    }

    private var logoPicAddInfo: Player.PIC_ADD_INFO? = null
    private var pseudoPicAddInfo: Player.PIC_ADD_INFO? = null
    private var osdBgPicAddInfo00: Player.PIC_ADD_INFO_EX? = null
    private var osdBgPicAddInfo01: Player.PIC_ADD_INFO_EX? = null
    private var osdBgPicAddInfo02: Player.PIC_ADD_INFO_EX? = null
    private var osdBgPicAddInfo03: Player.PIC_ADD_INFO_EX? = null
    private var osdBgPicAddInfo04: Player.PIC_ADD_INFO_EX? = null

    @Volatile
    private var playPort: Int = -1

    init {
        copyAsset("NotoSans-Regular.ttf", File(context.cacheDir, "NotoSans-Regular.ttf"))
        initPseudoColor()
    }

    fun getPlayPort(): Int = playPort
    fun setPlayPort(value: Int) { playPort = value }
    fun init() = Unit
    fun isPlaying(): Boolean = TODO("Not yet implemented")
    fun seekTo(position: Int) { throw NotImplementedError("Not yet implemented") }
    fun release() = Unit
    fun start() = start("", 0)

    override fun start(uri: String, mode: Int) {
        super.start(uri, mode)
        val player = Player.getInstance()
        playPort = player.getPort()
        if (playPort < 0) {
            playListeners.forEach { it.onError("start playPort is 负数") }
            return
        }

        player.setFontPath(playPort, File(context.cacheDir, "NotoSans-Regular.ttf").absolutePath)
        player.setFontSize(playPort, 50, 40)
        player.setPrivateDataType(playPort, PRIVATE_DATA_TYPE_EXTEND)
        player.setVideoFrameCB(playPort, videoFrameCB)
        if (player.play(playPort, surfaceHolder)) {
            resume()
        } else {
            val error = player.getLastError(playPort)
            playListeners.forEach { it.onError("start errorCode $error") }
            stop()
        }
    }

    override fun stop() {
        super.stop()
        pause()
        val player = Player.getInstance()
        player.setVideoFrameCB(playPort, null)
        player.stop(playPort)
        player.freePort(playPort)
    }

    @Synchronized
    fun updateFrameData(frameData: ByteArray): Boolean {
        if (playPort < 0) {
            playListeners.forEach { it.onError("updateFrameData playPort is -1") }
            return false
        }

        val player = Player.getInstance()
        val accepted = player.inputData(playPort, frameData, frameData.size)
        logoPicAddInfo?.let { player.setAddPicInfo(playPort, it) }
        pseudoPicAddInfo?.let { player.setAddPicInfo(playPort, it) }
        osdBgPicAddInfo00?.let { player.setAddPicInfoEx(playPort, it) }
        osdBgPicAddInfo01?.let { player.setAddPicInfoEx(playPort, it) }
        osdBgPicAddInfo02?.let { player.setAddPicInfoEx(playPort, it) }
        osdBgPicAddInfo03?.let { player.setAddPicInfoEx(playPort, it) }
        osdBgPicAddInfo04?.let { player.setAddPicInfoEx(playPort, it) }
        countDownTimer.cancel()
        return accepted
    }

    fun takePhoto(ratioSize: Size): d {
        val player = Player.getInstance()
        val frameTime = Player.MPInteger()
        val requestedSize = Player.MPInteger()
        if (!player.getJPG(playPort, null, 0, requestedSize)) return d(-1, null)

        val buffer = ByteArray(requestedSize.value)
        val actualSize = Player.MPInteger()
        return if (player.getJPGExWithWH(
                playPort,
                buffer,
                requestedSize.value,
                actualSize,
                frameTime,
                ratioSize.width,
                ratioSize.height,
            )
        ) {
            d(frameTime.value, buffer.copyOf(actualSize.value))
        } else {
            d(-1, null)
        }
    }

    @Synchronized
    fun startRecord(filePath: String, recordRatioSize: Size, codecType: Int): Boolean {
        File(filePath).parentFile?.let { if (!it.exists()) it.mkdirs() }
        q2.c.a(filePath)
        val player = Player.getInstance()
        player.setVidRecordResolution(playPort, recordRatioSize.width, recordRatioSize.height)
        val sourceType = if (codecType == Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_I420) {
            Player.RECORD_SOURCE_TYPE.RECORD_SOURCE_I420
        } else {
            codecType
        }
        if (sourceType > 0) player.setVidRecordSourceType(playPort, sourceType)
        return player.startRecord(playPort, null)
    }

    @Synchronized
    fun stopRecord(): Boolean {
        val transformed = q2.c.b()
        return if (transformed == 0) Player.getInstance().stopRecord(playPort) else false
    }

    fun setDisplayRegion(rect: Player.THERMAL_RECT): Boolean = Player.getInstance().setDisplayRegion(playPort, rect)
    fun setImagePostProcessParameter(type: Int = Player.IMAGE_POST_PROCESS_TYPE.IMAGE_POST_PROCESS_TYPE_NONE, value: Float): Boolean =
        Player.getInstance().setImagePostProcessParameter(playPort, type, value)

    fun setLogoPicAddInfo(bitmap: Bitmap, rectF: RectF) {
        logoPicAddInfo = setPicAddInfoByBitmap(bitmap, Player.PIC_TYPE.PIC_TYPE_EZVIZ_LOGO, rectF)
    }

    fun setPseudoPicAddInfo(pseudoColor: Int, pseudoPicSize: Size) {
        runCatching {
            val assetPath = colorArray[pseudoColor] ?: return
            val byteCount = pseudoPicSize.width * pseudoPicSize.height * 4
            val bytes = ByteArray(byteCount)
            val read = context.assets.open(assetPath).use { it.read(bytes, 0, byteCount) }
            if (read != byteCount) return
            pseudoPicAddInfo = Player.PIC_ADD_INFO().apply {
                bPicAdd = 1
                bypDataBuf = bytes
                nDataLen = byteCount
                pic_type = Player.PIC_TYPE.PIC_TYPE_PSEUDO_COLOR
                pic_add_type = Player.PIC_ADD_TYPE.PIC_ADD_RGBA32_TYPE
                nPicWidth = pseudoPicSize.width
                nPicHeight = pseudoPicSize.height
                stPicRect = vrRect(0.954f, 0.98f, 0.12f, 0.88f)
                stMintemRect = vrRect(0.9f, 0.98f, 0.9f, 0.96f)
                stMaxtemRect = vrRect(0.9f, 0.98f, 0.06f, 0.12f)
            }
        }
    }

    fun setOsdBgPicAddInfo00(bitmap: Bitmap, rect: RectF, alpha: Float = 1f, enabled: Boolean = true) {
        osdBgPicAddInfo00 = setOsdBgPicAddInfoEx(bitmap, rect, 0, enabled, alpha)
    }
    fun setOsdBgPicAddInfo01(bitmap: Bitmap, rect: RectF, alpha: Float = 1f, enabled: Boolean = true) {
        osdBgPicAddInfo01 = setOsdBgPicAddInfoEx(bitmap, rect, 1, enabled, alpha)
    }
    fun setOsdBgPicAddInfo02(bitmap: Bitmap, rect: RectF, alpha: Float = 1f, enabled: Boolean = true) {
        osdBgPicAddInfo02 = setOsdBgPicAddInfoEx(bitmap, rect, 2, enabled, alpha)
    }
    fun setOsdBgPicAddInfo03(bitmap: Bitmap, rect: RectF, alpha: Float = 1f, enabled: Boolean = true) {
        osdBgPicAddInfo03 = setOsdBgPicAddInfoEx(bitmap, rect, 3, enabled, alpha)
    }
    fun setOsdBgPicAddInfo04(bitmap: Bitmap, rect: RectF, alpha: Float = 1f, enabled: Boolean = true) {
        osdBgPicAddInfo04 = setOsdBgPicAddInfoEx(bitmap, rect, 4, enabled, alpha)
    }

    private fun setOsdBgPicAddInfoEx(
        bitmap: Bitmap,
        rect: RectF,
        id: Int,
        enabled: Boolean,
        alpha: Float,
    ): Player.PIC_ADD_INFO_EX {
        val bytes = getBytesFromBitmap(bitmap)
        return Player.PIC_ADD_INFO_EX().apply {
            pic_id = id
            bPicAdd = enabled
            pic_add_level = Player.PIC_ADD_LEVEL.PIC_ADD_LEVEL_2
            fAlpha = alpha
            bypDataBuf = bytes
            nDataLen = bytes.size
            pic_type = Player.PIC_TYPE.PIC_TYPE_TextOSD
            pic_add_type = Player.PIC_ADD_TYPE.PIC_ADD_RGBA32_TYPE
            nPicWidth = bitmap.width
            nPicHeight = bitmap.height
            stPicRect = vrRect(rect.left, rect.right, rect.top, rect.bottom)
        }
    }

    private fun setPicAddInfoByBitmap(bitmap: Bitmap, type: Int, rect: RectF): Player.PIC_ADD_INFO {
        val bytes = getBytesFromBitmap(bitmap)
        val nativeRect = vrRect(rect.left, rect.right, rect.top, rect.bottom)
        return Player.PIC_ADD_INFO().apply {
            bPicAdd = 1
            bypDataBuf = bytes
            nDataLen = bytes.size
            pic_type = type
            pic_add_type = Player.PIC_ADD_TYPE.PIC_ADD_RGBA32_TYPE
            nPicWidth = bitmap.width
            nPicHeight = bitmap.height
            stPicRect = nativeRect
            stMaxtemRect = nativeRect
            stMintemRect = nativeRect
        }
    }

    private fun getBytesFromBitmap(bitmap: Bitmap): ByteArray =
        ByteBuffer.allocate(bitmap.byteCount).also(bitmap::copyPixelsToBuffer).array()

    private fun initPseudoColor() {
        colorArray.put(0, "rgba/whitehot.rgba")
        colorArray.put(1, "rgba/blackhot.rgba")
        colorArray.put(9, "rgba/fusion.rgba")
        colorArray.put(10, "rgba/rainbow.rgba")
        colorArray.put(11, "rgba/glowbow.rgba")
        colorArray.put(12, "rgba/ironbow1.rgba")
        colorArray.put(13, "rgba/ironbow2.rgba")
        colorArray.put(14, "rgba/sepia.rgba")
        colorArray.put(15, "rgba/color1.rgba")
        colorArray.put(16, "rgba/color2.rgba")
        colorArray.put(17, "rgba/icefire.rgba")
        colorArray.put(18, "rgba/rain.rgba")
        colorArray.put(19, "rgba/redhot.rgba")
        colorArray.put(20, "rgba/greenhot.rgba")
        colorArray.put(21, "rgba/hotspot.rgba")
    }

    private fun copyAsset(name: String, destination: File) {
        context.assets.open(name).use { source -> destination.outputStream().use(source::copyTo) }
    }

    private fun vrRect(left: Float, right: Float, top: Float, bottom: Float) = Player.VRRECTF().apply {
        fLeft = left
        fRight = right
        fTop = top
        fBottom = bottom
    }

    companion object {
        const val PRIVATE_DATA_TYPE_EZVIZ = 1
        const val PRIVATE_DATA_TYPE_EXTEND = 2
    }
}
