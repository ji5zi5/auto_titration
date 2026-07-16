package V2

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.RectF
import android.util.Size
import android.view.SurfaceView
import com.hik.library.player.b
import com.hik.library.player.d

/** Official M4 F1 renderer: raw/private frames are sent to ThermalPlayer. */
class b(private val surfaceView: SurfaceView) : f {
    private val player = com.hik.thermalplayer.ThermalPlayer(surfaceView.context, surfaceView.holder)
    override fun a(): Boolean { player.stopRecord(); return true }
    override fun b(listener: b) = Unit
    override fun c() = Unit
    override fun d(picSize: Size, filePath: String): Boolean = player.startRecord(filePath, picSize, l2.k.e("RECORD_CODEC_TYPE", 0))
    override fun e(picSize: Size): ByteArray? = player.takePhoto(picSize).b()
    override fun f(picSize: Size): d = player.takePhoto(picSize)
    override fun g(first: Boolean, second: Boolean, third: Boolean, fourth: Boolean, mode: Int, firstScale: Float, secondScale: Float) {
        val osdBitmap = surfaceView.context.assets.open("osd_bg.png").use(BitmapFactory::decodeStream)
        val temperatureRows = (if (second) 1 else 0) + (if (third) 1 else 0) + (if (fourth) 1 else 0)
        val firstRect = RectF(
            0.005f,
            0.067f,
            0.16f + 0.021f * firstScale,
            0.122f + (temperatureRows - 1) * 0.04f,
        )
        val firstVisible = temperatureRows > 0
        player.setOsdBgPicAddInfo00(osdBitmap, firstRect, 0.55f, firstVisible)

        val right = 0.11f + 0.015f * secondScale
        val base = if (firstVisible) 0.262f else 0.067f
        val row1 = RectF(0.005f, base, right, base + 0.125f)
        val row2Top = if (firstVisible) 0.432f else 0.237f
        val row2 = RectF(0.005f, row2Top, right, row2Top + 0.125f)
        val row3Top = base + 0.34f
        val row3 = RectF(0.005f, row3Top, right, row3Top + 0.125f)
        if (Z2.g.a.U().getDevType() == 1) {
            player.setOsdBgPicAddInfo01(osdBitmap, row1, 0.55f, mode >= 1)
            player.setOsdBgPicAddInfo02(osdBitmap, row2, 0.55f, mode >= 2)
            player.setOsdBgPicAddInfo03(osdBitmap, row3, 0.55f, mode >= 3)
        }
    }
    override fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int) { rawData?.let(player::updateFrameData) }
    override fun i(showSize: Size) {
        val bitmap = surfaceView.context.assets.open("logo_hik_w.png").use(BitmapFactory::decodeStream)
        val scale = 0.06f / (bitmap.height.toFloat() / showSize.height)
        player.setLogoPicAddInfo(
            bitmap,
            RectF(0.007f, 0f, bitmap.width.toFloat() / showSize.width * scale, 0.06f),
        )
    }
    override fun j(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int, overlays: List<*>?, overlayBitmap: Bitmap?) = Unit
    override fun k(value: Int) = player.setPseudoPicAddInfo(value, Size(6, 83))
    override fun release() = Unit
    override fun start() { player.start(); com.hik.f1module.F1UsbModuleHelper.USB_SetPreviewEnable(true) }
    override fun stop() { player.stop(); com.hik.f1module.F1UsbModuleHelper.USB_SetPreviewEnable(false) }
}
