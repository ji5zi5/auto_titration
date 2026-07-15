package com.hik.viewercommon.data.bean

import com.hik.viewercommon.data.device.api.callback.F2ModuleStreamCallback
import m2.a
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class OfficialPreviewAbiTest {
    @Test
    fun previewInfoDataBeanExposesOfficialMutableDataClassApi() {
        val bean = PreviewInfoDataBean()
        val replacement = byteArrayOf(1, 2, 3)

        bean.byteArrSrc = replacement

        assertArrayEquals(replacement, bean.byteArrSrc)
        assertArrayEquals(replacement, bean.getByteArrSrc())
        assertEquals(replacement, bean.component1())
        assertEquals(replacement, bean.copy().byteArrSrc)
        assertEquals(
            setOf(
                "byteArrSrc",
                "byteArrDst",
                "byteArrHead",
                "byteArrRawData",
                "byteArrRawAppendData",
                "byteArrYuvAppendData",
                "byteArrRawAppendLine2",
                "offByteArrRawData",
                "offByteArrRawAppendData",
            ),
            PreviewInfoDataBean::class.java.declaredFields.map { it.name }.toSet(),
        )
        assertTrue(PreviewInfoDataBean::class.java.methods.any { it.name == "setByteArrSrc" })
        assertEquals(
            "byteArrSrc 3 \n byteArrDst 0 \n byteArrHead 0 \n byteArrRawData 0 " +
                "\n byteArrRawAppendData 0 \n byteArrYuvAppendData 0 " +
                "\n byteArrRawAppendLine2 0 \n offByteArrRawData 0 " +
                "\n offByteArrRawAppendData 0 \n ",
            bean.toString(),
        )
    }

    @Test
    fun previewStreamInfoExposesOfficialMutableProperties() {
        val original = PreviewInfoDataBean(byteArrSrc = byteArrayOf(1))
        val replacement = PreviewInfoDataBean(byteArrSrc = byteArrayOf(2))
        val streamInfo = PreviewStreamInfo(original)

        streamInfo.previewInfoData = replacement
        streamInfo.iStreamInfo = null

        assertEquals(replacement, streamInfo.previewInfoData)
        assertEquals(replacement, streamInfo.getPreviewInfoData())
        assertNull(streamInfo.iStreamInfo)
        assertNull(streamInfo.getIStreamInfo())
        assertEquals(
            setOf("previewInfoData", "iStreamInfo"),
            PreviewStreamInfo::class.java.declaredFields.map { it.name }.toSet(),
        )
        assertTrue(PreviewStreamInfo::class.java.methods.any { it.name == "setPreviewInfoData" })
        assertTrue(PreviewStreamInfo::class.java.methods.any { it.name == "setIStreamInfo" })
    }

    @Test
    fun f2CallbackUsesOfficialMarkerAndFieldNames() {
        val callback = F2ModuleStreamCallback(null, null)
        val fieldNames = F2ModuleStreamCallback::class.java.declaredFields.map { it.name }.toSet()

        assertTrue(a::class.java.isAssignableFrom(callback.javaClass))
        assertEquals(setOf("fStreamCallBack", "fStreamCallBackJNA"), fieldNames)
        assertNull(callback.getFStreamCallBack())
        assertNull(callback.getFStreamCallBackJNA())
    }
}
