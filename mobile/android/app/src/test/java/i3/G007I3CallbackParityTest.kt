package i3

import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy
import com.hik.f2module.IFR_INFO
import com.hik.viewercommon.data.bean.OsdBgCallbackBean
import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import com.hik.viewercommon.data.bean.TempCallbackBean
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Ignore
import org.junit.Test

class G007I3CallbackParityTest {
    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; keep this for Android/instrumented coverage.")
    @Test
    fun private203720HeaderProducesOfficialTempBeanOsdAndThreeSecondSummary() {
        val deal = b().forceThreeSecondCallbackDue()
        val preview = previewWithAppendMetadata()
        val privateInfo = HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO().apply {
            temp_Info.GlobalInfo.tempUnit = 1
            temp_Info.GlobalInfo.centerTmp = 300.15f
            temp_Info.GlobalInfo.maxTmp = 310.15f
            temp_Info.GlobalInfo.minTmp = 290.15f
            temp_Info.Upload.tempUnit = 0
            temp_Info.Upload.tmProssMode = 7
            temp_Info.Upload.ifrOutcomeList.regionNum.boxNum = 1
            temp_Info.Upload.ifrOutcomeList.ifrOutcome[0].enable = 1
            temp_Info.Upload.ifrOutcomeList.ifrOutcome[0].regiontype = 1
            temp_Info.Upload.ifrOutcomeList.ifrOutcome[0].maxTmp = 50f
            temp_Info.Upload.ifrOutcomeList.ifrOutcome[0].minTmp = 20f
            temp_show.Global_SC.tempListSC.lefTopSC.tempSC[0].bShow = 1
            temp_show.Global_SC.tempListSC.lefTopSC.tempSC[1].bShow = 1
            temp_show.Global_SC.tempListSC.lefTopSC.tempSC[2].bShow = 1
            temp_show.Upload_SC.ifrOutcomeList_SC.ifrOutcome_SC[0].tempListSC.lefTopSC.bShow = 1
        }

        var bean: TempCallbackBean? = null
        var summary: List<Any?>? = null
        deal.b(h3.b(privateInfo), preview, { bean = it as TempCallbackBean }) { mode, unit, center, max, min ->
            summary = listOf(mode, unit, center, max, min)
        }

        assertTempBean(bean!!, tempMode = 7, max = 37f, cen = 27f, min = 17f)
        assertAppendMetadata(bean!!)
        assertEquals(listOf(7, 0, 10f, 50f, 20f), summary)

        var osd: Any? = null
        val anyCallback: (Any?) -> Unit = { osd = it }
        @Suppress("UNCHECKED_CAST")
        deal.c(h3.b(privateInfo), preview.getByteArrRawAppendData(), anyCallback as (ByteArray) -> Unit)
        val osdBean = osd as OsdBgCallbackBean
        assertTrue(osdBean.getEnableOsdBg())
        assertTrue(osdBean.getEnableCenterTem())
        assertTrue(osdBean.getEnableHighTem())
        assertTrue(osdBean.getEnableLowTem())
        assertEquals(1, osdBean.getOsdBgRectNum())
    }

    @Ignore("Local JVM stubs cannot execute production android.util.Size.getWidth() path; keep this for Android/instrumented coverage.")
    @Test
    fun upload183496HeaderProducesOfficialTempBeanOsdAndThreeSecondSummary() {
        val deal = b().forceThreeSecondCallbackDue()
        val preview = previewWithAppendMetadata()
        val upload = IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO().apply {
            enumTempUnit = 0
            u32TempMode = 5
            fAvrTmp = 25f
            fMaxTmp = 35f
            fMinTmp = 15f
            boxNum = 1
            ifrOutcomeInfoArr[0].enable = 1
            ifrOutcomeInfoArr[0].regiontype = 1
            ifrOutcomeInfoArr[0].maxTmp = 45f
            ifrOutcomeInfoArr[0].minTmp = 12f
            ifrOutcomeInfoArr[0].avrTmp = 22f
        }

        var bean: TempCallbackBean? = null
        var summary: List<Any?>? = null
        deal.b(h3.c(upload), preview, { bean = it as TempCallbackBean }) { mode, unit, center, max, min ->
            summary = listOf(mode, unit, center, max, min)
        }

        assertTempBean(bean!!, tempMode = 5, max = 35f, cen = 25f, min = 15f)
        assertAppendMetadata(bean!!)
        assertEquals(listOf(5, 0, 10f, 45f, 12f), summary)

        var osd: Any? = null
        val anyCallback: (Any?) -> Unit = { osd = it }
        @Suppress("UNCHECKED_CAST")
        deal.c(h3.c(upload), preview.getByteArrRawAppendData(), anyCallback as (ByteArray) -> Unit)
        val osdBean = osd as OsdBgCallbackBean
        assertEquals(1, osdBean.getOsdBgRectNum())
        assertTrue(osdBean.getEnableCenterTem())
        assertTrue(osdBean.getEnableHighTem())
        assertTrue(osdBean.getEnableLowTem())
    }

    @Test
    fun uploadOsdUsesHeaderPackageCount() {
        assertEquals(5, b().uploadPackageCount(3, 2))
    }

    @Test
    fun uploadOsdUsesGlobalAndOutcomeMarkerWidths() {
        val deal = b()

        assertEquals(4, deal.textChars(35f, '+'))
        assertEquals(5, deal.textChars(35f, '~'))
        assertEquals(4.1f, deal.textBoxSize(0, 35f, 15f, 25f, '+', '+', '+'), 0.0001f)
    }

    @Test
    fun officialUnitMappingConvertsOnlyViaD3iRules() {
        val previousProfile = Z2.a.a.p()
        try {
            Z2.a.a.u(f3.j())
            assertEquals(27f, d3.i.a.d(300.15f, 1), 0.0001f)
            assertEquals(37.77778f, d3.i.a.d(100f, 2), 0.0001f)
            assertEquals(300.15f, d3.i.a.i(27f, 1), 0.0001f)
            assertEquals(98.6f, d3.i.a.i(37f, 2), 0.0001f)
            assertEquals(3, d3.i.a.j(3, d3.c.a.a("F2")))
        } finally {
            Z2.a.a.u(previousProfile)
        }
    }

    private fun b.forceThreeSecondCallbackDue(): b = apply {
        val field = b::class.java.getDeclaredField("c")
        field.isAccessible = true
        field.setLong(this, System.currentTimeMillis() - 3001L)
    }

    private fun assertTempBean(bean: TempCallbackBean, tempMode: Int, max: Float, cen: Float, min: Float) {
        assertEquals(tempMode, bean.getTempMode())
        assertEquals(max, bean.getMax(), 0.0001f)
        assertEquals(cen, bean.getCen(), 0.0001f)
        assertEquals(min, bean.getMin(), 0.0001f)
    }

    private fun assertAppendMetadata(bean: TempCallbackBean) {
        assertEquals(1111, bean.getMaxGrey())
        assertEquals(2222, bean.getCenGrey())
        assertEquals(333, bean.getCAV())
        assertEquals(444, bean.getShutterCav())
        assertEquals(555, bean.getTec())
        assertEquals(666, bean.getSens())
        assertEquals(777777, bean.getEnv())
        assertArrayEquals((rawBytes() + appendBytes()), bean.getRawWithAppendData())
    }

    private fun previewWithAppendMetadata(): PreviewInfoDataBean = PreviewInfoDataBean(
        byteArrRawData = rawBytes(),
        byteArrRawAppendData = appendBytes(),
    )

    private fun rawBytes(): ByteArray = byteArrayOf(1, 2, 3, 4)

    private fun appendBytes(): ByteArray = ByteArray(192 * 4).apply {
        putShortLe(262, 1111)
        putShortLe(264, 2222)
        putShortLe(2, 333)
        putShortLe(40, 444)
        putShortLe(10, 555)
        putShortLe(26, 666)
        putIntLe(192 * 2 + 16, 777777)
    }

    private fun ByteArray.putShortLe(offset: Int, value: Int) {
        ByteBuffer.wrap(this, offset, 2).order(ByteOrder.LITTLE_ENDIAN).putShort(value.toShort())
    }

    private fun ByteArray.putIntLe(offset: Int, value: Int) {
        ByteBuffer.wrap(this, offset, 4).order(ByteOrder.LITTLE_ENDIAN).putInt(value)
    }
}
