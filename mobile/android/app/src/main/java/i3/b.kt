package i3

import L5.d as LimitHelper
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy
import com.hik.f2module.IFR_INFO
import com.hik.viewercommon.data.bean.OsdBgCallbackBean
import com.hik.viewercommon.data.bean.PreviewInfoDataBean
import h3.a as StreamInfo
import h3.b as PrivateStreamInfo
import h3.c as UploadStreamInfo

/** Official i3.b callback semantics subset recovered from Viewer 2.6.0 DEX. */
class b : a {
    private var a: Boolean = false
    private var b: Int = 0
    private var c: Long = System.currentTimeMillis()

    override fun a(isFreezeData: Boolean, freezeCallback: ((Boolean) -> Unit)?, thawCallback: ((Boolean) -> Unit)?) {
        if (isFreezeData != a) {
            if (!isFreezeData) {
                when {
                    b == 1 -> thawCallback?.invoke(true)
                    b > 1 -> thawCallback?.invoke(false)
                }
            } else {
                b += 1
            }
            freezeCallback?.invoke(isFreezeData)
            a = isFreezeData
        }
    }

    override fun b(streamInfo: StreamInfo?, previewInfoData: PreviewInfoDataBean, metadataCallback: ((Any?) -> Unit)?, overlayCallback: ((Any?, Any?, Any?, Any?, Any?) -> Unit)?) {
        when (streamInfo) {
            is PrivateStreamInfo -> f(streamInfo.a(), previewInfoData, metadataCallback, overlayCallback)
            is UploadStreamInfo -> g(streamInfo.a(), previewInfoData, metadataCallback, overlayCallback)
        }
    }

    override fun c(streamInfo: StreamInfo?, rawAppendData: ByteArray, callback: ((ByteArray) -> Unit)?) {
        when (streamInfo) {
            is PrivateStreamInfo -> d(streamInfo.a(), callback)
            is UploadStreamInfo -> e(streamInfo.a(), callback)
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun invokeOsd(callback: ((ByteArray) -> Unit)?, bean: OsdBgCallbackBean) {
        (callback as? (Any?) -> Unit)?.invoke(bean)
    }

    private fun d(privateInfo: HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO, callback: ((ByteArray) -> Unit)?) {
        val globals = Z2.g.a
        val osdBg = globals.v()
        val bgMode = globals.M()
        val moduleType = d3.c.a.a(globals.U().getModuleID())
        val tempInfo = privateInfo.temp_Info
        val show = privateInfo.temp_show
        val globalTempSc = show.Global_SC.tempListSC.lefTopSC.tempSC
        val enableCenter = globalTempSc.getOrNull(0)?.bShow == 1.toByte()
        val enableHigh = globalTempSc.getOrNull(1)?.bShow == 1.toByte()
        val enableLow = globalTempSc.getOrNull(2)?.bShow == 1.toByte()
        val uploadUnit = tempInfo.Upload.tempUnit
        val globalUnit = tempInfo.GlobalInfo.tempUnit
        val converter = d3.i.a
        val limiter = LimitHelper.a
        val max = converter.i(limiter.c(converter.d(tempInfo.GlobalInfo.maxTmp, globalUnit), bgMode, moduleType), uploadUnit)
        val min = converter.i(limiter.c(converter.d(tempInfo.GlobalInfo.minTmp, globalUnit), bgMode, moduleType), uploadUnit)
        val cen = converter.i(limiter.c(converter.d(tempInfo.GlobalInfo.centerTmp, globalUnit), bgMode, moduleType), uploadUnit)
        val globalAcc = show.Global_SC.tempListSC.ruleAroundSC.tempSC
        val longest = textBoxSize(uploadUnit, max, min, cen, globalAcc.getOrNull(1)?.temperature_accuracy, globalAcc.getOrNull(2)?.temperature_accuracy, globalAcc.getOrNull(0)?.temperature_accuracy)
        val outcomes = tempInfo.Upload.ifrOutcomeList.ifrOutcome
        val outcomeShow = show.Upload_SC.ifrOutcomeList_SC.ifrOutcome_SC
        var visibleRectCount = 0
        var longestKChars = 0
        outcomes.forEachIndexed { idx, outcome ->
            if (outcome.enable == 1.toByte() && (outcome.regiontype == 1 || outcome.regiontype == 2)) {
                val sc = outcomeShow.getOrNull(idx)?.tempListSC?.lefTopSC
                if (sc?.bShow == 1.toByte()) visibleRectCount += 1
                val tempSc = sc?.tempSC ?: emptyArray()
                val kMax = converter.i(limiter.c(converter.d(outcome.maxTmp, uploadUnit), bgMode, moduleType), uploadUnit)
                val kMin = converter.i(limiter.c(converter.d(outcome.minTmp, uploadUnit), bgMode, moduleType), uploadUnit)
                val kAvg = converter.i(limiter.c(converter.d(outcome.avrTmp, uploadUnit), bgMode, moduleType), uploadUnit)
                longestKChars = maxOf(longestKChars, textChars(kMax, tempSc.getOrNull(1)?.temperature_accuracy), textChars(kMin, tempSc.getOrNull(2)?.temperature_accuracy), textChars(kAvg, tempSc.getOrNull(3)?.temperature_accuracy))
            }
        }
        val kLongest = if (uploadUnit != 2) longestKChars + 0.1f else longestKChars - 0.5f
        invokeOsd(callback, OsdBgCallbackBean(osdBg, enableCenter, enableHigh, enableLow, visibleRectCount, longest, kLongest))
    }

    private fun e(uploadInfo: IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO, callback: ((ByteArray) -> Unit)?) {
        val globals = Z2.g.a
        val basic = globals.K()
        val bgMode = globals.M()
        val moduleType = d3.c.a.a(globals.U().getModuleID())
        val unit = d3.i.a.j(uploadInfo.enumTempUnit, moduleType)
        val max = d3.i.a.i(LimitHelper.a.c(uploadInfo.fMaxTmp, bgMode, moduleType), unit)
        val min = d3.i.a.i(LimitHelper.a.c(uploadInfo.fMinTmp, bgMode, moduleType), unit)
        val cen = d3.i.a.i(LimitHelper.a.c(uploadInfo.fAvrTmp, bgMode, moduleType), unit)
        val maxMarker = LimitHelper.a.b(uploadInfo.fMaxTmp, bgMode, moduleType)
        val minMarker = LimitHelper.a.b(uploadInfo.fMinTmp, bgMode, moduleType)
        val cenMarker = LimitHelper.a.b(uploadInfo.fAvrTmp, bgMode, moduleType)
        val longest = textBoxSize(unit, max, min, cen, maxMarker, minMarker, cenMarker)
        var longestKChars = 0
        uploadInfo.ifrOutcomeInfoArr.forEach { outcome ->
            if (outcome.enable == 1.toByte() && (outcome.regiontype == 1 || outcome.regiontype == 2)) {
                longestKChars = maxOf(
                    longestKChars,
                    textChars(d3.i.a.i(LimitHelper.a.c(outcome.maxTmp, bgMode, moduleType), unit), LimitHelper.a.b(outcome.maxTmp, bgMode, moduleType)),
                    textChars(d3.i.a.i(LimitHelper.a.c(outcome.minTmp, bgMode, moduleType), unit), LimitHelper.a.b(outcome.minTmp, bgMode, moduleType)),
                    textChars(d3.i.a.i(LimitHelper.a.c(outcome.avrTmp, bgMode, moduleType), unit), LimitHelper.a.b(outcome.avrTmp, bgMode, moduleType)),
                )
            }
        }
        val kLongest = if (unit != 2) longestKChars + 0.1f else longestKChars - 0.5f
        val packageCount = uploadInfo.lineNum.toInt() + uploadInfo.boxNum.toInt()
        invokeOsd(callback, OsdBgCallbackBean(globals.v(), basic.getEnableCenterTem(), basic.getEnableHighTem(), basic.getEnableLowTem(), packageCount, longest, kLongest))
    }

    private fun f(privateInfo: HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO, previewInfoData: PreviewInfoDataBean, metadataCallback: ((Any?) -> Unit)?, overlayCallback: ((Any?, Any?, Any?, Any?, Any?) -> Unit)?) {
        val tempInfo = privateInfo.temp_Info
        val global = tempInfo.GlobalInfo
        val sourceUnit = global.tempUnit
        val upload = tempInfo.Upload
        val unit = upload.tempUnit
        var center = d3.i.a.d(global.centerTmp, sourceUnit)
        var max = d3.i.a.d(global.maxTmp, sourceUnit)
        var min = d3.i.a.d(global.minTmp, sourceUnit)
        val accuracy = privateInfo.temp_show.Global_SC.tempListSC.ruleAroundSC.tempSC
        val bean = d3.b.a.a(upload.tmProssMode.toInt(), max, center, min, accuracy.getOrNull(1)?.temperature_accuracy?.toInt()?.toChar() ?: 0.toChar(), accuracy.getOrNull(0)?.temperature_accuracy?.toInt()?.toChar() ?: 0.toChar(), accuracy.getOrNull(2)?.temperature_accuracy?.toInt()?.toChar() ?: 0.toChar(), previewInfoData, Z2.a.a.p().g().width)
        metadataCallback?.invoke(bean)
        if (upload.ifrOutcomeList.regionNum.boxNum > 0) {
            upload.ifrOutcomeList.ifrOutcome.firstOrNull { it.enable == 1.toByte() && it.regiontype == 1 }?.let {
                center = d3.i.a.d(10f, unit)
                max = d3.i.a.d(it.maxTmp, unit)
                min = d3.i.a.d(it.minTmp, unit)
            }
        }
        maybeInvokeOverlay(upload.tmProssMode.toInt(), unit, center, max, min, overlayCallback)
    }

    private fun g(uploadInfo: IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO, previewInfoData: PreviewInfoDataBean, metadataCallback: ((Any?) -> Unit)?, overlayCallback: ((Any?, Any?, Any?, Any?, Any?) -> Unit)?) {
        var center = uploadInfo.fAvrTmp
        var max = uploadInfo.fMaxTmp
        var min = uploadInfo.fMinTmp
        val globals = Z2.g.a
        val moduleType = d3.c.a.a(globals.U().getModuleID())
        val mode = globals.M()
        val maxChar = LimitHelper.a.b(max, mode, moduleType)
        val minChar = LimitHelper.a.b(min, mode, moduleType)
        val cenChar = LimitHelper.a.b(center, mode, moduleType)
        val tempMode = uploadInfo.u32TempMode
        val unit = d3.i.a.j(uploadInfo.enumTempUnit, moduleType)
        val bean = d3.b.a.a(tempMode, max, center, min, maxChar, cenChar, minChar, previewInfoData, Z2.a.a.p().g().width)
        metadataCallback?.invoke(bean)
        if (uploadInfo.boxNum > 0) {
            uploadInfo.ifrOutcomeInfoArr.firstOrNull { it.enable == 1.toByte() && it.regiontype == 1 }?.let {
                center = 10f
                max = it.maxTmp
                min = it.minTmp
            }
        }
        maybeInvokeOverlay(tempMode, unit, center, max, min, overlayCallback)
    }

    private fun maybeInvokeOverlay(tempMode: Int, unit: Int, center: Float, max: Float, min: Float, overlayCallback: ((Any?, Any?, Any?, Any?, Any?) -> Unit)?) {
        if (System.currentTimeMillis() - c > 3000) {
            overlayCallback?.invoke(tempMode, unit, center, max, min)
            c = System.currentTimeMillis()
        }
    }

    private fun textBoxSize(unit: Int, max: Float, min: Float, cen: Float, maxAcc: Byte?, minAcc: Byte?, cenAcc: Byte?): Float {
        val chars = maxOf(textChars(max, maxAcc), textChars(min, minAcc), textChars(cen, cenAcc))
        return if (unit != 2) chars + 0.1f else chars - 0.5f
    }

    private fun textBoxSize(unit: Int, max: Float, min: Float, cen: Float, maxMarker: Char, minMarker: Char, cenMarker: Char): Float {
        val chars = maxOf(textChars(max, maxMarker), textChars(min, minMarker), textChars(cen, cenMarker))
        return if (unit != 2) chars + 0.1f else chars - 0.5f
    }

    private fun textChars(value: Float, accuracy: Byte?): Int = d3.b.a.b(value).length + if (accuracy == 43.toByte()) 0 else 1

    private fun textChars(value: Float, marker: Char): Int = d3.b.a.b(value).length + if (marker == '+') 0 else 1
}
