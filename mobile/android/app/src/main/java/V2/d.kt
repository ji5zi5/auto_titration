package V2

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.RectF
import android.util.Size
import android.view.SurfaceView
import com.hik.f1module.helper.ThermalInfoHelper
import com.hik.library.player.b
import h3.b as PrivateStreamInfo
import h3.c as UploadStreamInfo
import hik.common.yyrj.uicommon.data.ModuleTypeF2ModuleType

/** Official M4 F2 renderer: packets are packed as ThermalPlayer private/YUV frames. */
class d(private val surfaceView: SurfaceView) : f {
    private val player = com.hik.thermalplayer.ThermalPlayer(surfaceView.context, surfaceView.holder, 25_000L)
    override fun a(): Boolean = player.stopRecord()
    override fun b(listener: b) = player.addPlayListener(listener)
    override fun c() = player.removeAllPlayListener()
    override fun d(picSize: Size, filePath: String): Boolean = player.startRecord(filePath, picSize, l2.k.e("RECORD_CODEC_TYPE", 0))
    override fun e(picSize: Size): ByteArray? = player.takePhoto(picSize).b()
    override fun f(picSize: Size): com.hik.library.player.d = player.takePhoto(picSize)
    override fun g(first: Boolean, second: Boolean, third: Boolean, fourth: Boolean, mode: Int, firstScale: Float, secondScale: Float) {
        val osdBitmap = surfaceView.context.assets.open("osd_bg.png").use(BitmapFactory::decodeStream)
        val temperatureRows = (if (second) 1 else 0) + (if (third) 1 else 0) + (if (fourth) 1 else 0)
        val landscape = Z2.g.a.E().width > Z2.g.a.E().height
        var right = if (landscape) 0.11f + 0.007f * firstScale + 0.004f else 0.116f + 0.028f * firstScale + 0.01f
        if (d3.c.a.a(Z2.g.a.U().getModuleID()) == ModuleTypeF2ModuleType.F0) right *= 0.8f
        val firstHeight = when (temperatureRows) { 1 -> 0.046f; 2 -> 0.084f; 3 -> 0.12f; else -> 0f }
        val firstRect = RectF(0.01f, 0.008f, right, 0.008f + firstHeight)
        val firstVisible = temperatureRows > 0
        player.setOsdBgPicAddInfo00(osdBitmap, firstRect, 0.55f, first && firstVisible)

        val rows = Array(4) { index ->
            val top = (if (firstVisible) firstRect.bottom + 0.008f else firstRect.bottom) + index * (0.0405f + 0.008f)
            RectF(firstRect.left, top, right, top + 0.0405f)
        }
        val devSupportsRows = Z2.g.a.U().getDevType() == 1 && first
        player.setOsdBgPicAddInfo01(osdBitmap, rows[0], 0.55f, devSupportsRows && mode >= 1)
        player.setOsdBgPicAddInfo02(osdBitmap, rows[1], 0.55f, devSupportsRows && mode >= 2)
        player.setOsdBgPicAddInfo03(osdBitmap, rows[2], 0.55f, devSupportsRows && mode >= 3)
        player.setOsdBgPicAddInfo04(osdBitmap, rows[3], 0.55f, devSupportsRows && mode >= 4)
    }
    override fun h(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int) {
        if (!Z2.a.a.i()) {
            ThermalInfoHelper.INSTANCE.getYuvThermalDataInfo(nv12Data, yuvImgSize)?.let(player::updateFrameData)
            return
        }

        val state = Z2.g.a
        val moduleType = d3.c.a.a(state.U().getModuleID())
        val serialNumber = state.U().getSerialNumber()
        val privateBytes = when (val streamInfo = state.o()) {
            is PrivateStreamInfo -> {
                val info = d3.i.a.m(
                    streamInfo.a(),
                    state.v(),
                    state.i(serialNumber, if (state.f()) 1 else 0),
                    state.g(serialNumber, state.e()),
                    state.h(serialNumber),
                    state.u(),
                    state.w(serialNumber),
                )
                info.privateInfo_header.dsp_std_stamp = frameNumStamp
                k3.b.b(k3.b.a, info, null, 2, null)
            }
            is UploadStreamInfo -> {
                if (state.n() == 98_304 || state.n() == 221_184) {
                    ThermalInfoHelper.INSTANCE.getYuvThermalDataInfo(state.j(), yuvImgSize)?.let(player::updateFrameData)
                    return
                }
                val basic = state.K()
                val info = d3.i.a.k(
                    streamInfo.a(),
                    basic.getEnableCenterTem(),
                    basic.getEnableHighTem(),
                    basic.getEnableLowTem(),
                    state.L(),
                    true,
                    state.i(serialNumber, if (state.f()) 1 else 0),
                    state.g(serialNumber, state.e()),
                    state.h(serialNumber),
                    state.u(),
                    state.M(),
                    moduleType,
                    state.w(serialNumber),
                )
                info.privateInfo_header.dsp_std_stamp = frameNumStamp
                k3.b.b(k3.b.a, info, null, 2, null)
            }
            else -> null
        }
        val totalLength = if (moduleType == ModuleTypeF2ModuleType.F0) 27_640 else 0
        val packed = privateBytes?.let {
            ThermalInfoHelper.INSTANCE.getThermalDataInfo(it, nv12Data, yuvImgSize, totalLength)
        }
        packed?.let(player::updateFrameData)
    }
    override fun i(showSize: Size) {
        val bitmap = surfaceView.context.assets.open("logo_hik_w.png").use(BitmapFactory::decodeStream)
        val scale = 0.06f / (bitmap.height.toFloat() / showSize.height)
        val top = if (Z2.g.a.s()) 0f else 0.94f
        player.setLogoPicAddInfo(
            bitmap,
            RectF(0.008f, top, bitmap.width.toFloat() / showSize.width * scale, top + 0.06f),
        )
    }
    override fun j(rawData: ByteArray?, nv12Data: ByteArray, yuvImgSize: Size, frameNumStamp: Int, overlays: List<*>?, overlayBitmap: Bitmap?) = Unit
    override fun k(value: Int) = player.setPseudoPicAddInfo(value, Size(12, 83))
    override fun release() { player.release(); ThermalInfoHelper.INSTANCE.release() }
    override fun start() = player.start()
    override fun stop() = player.stop()
}
