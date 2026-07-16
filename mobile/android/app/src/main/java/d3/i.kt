package d3

import hik.common.yyrj.uicommon.data.ModuleType
import hik.common.yyrj.uicommon.data.ModuleTypeF2ModuleType
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy
import com.hik.f2module.IFR_INFO

/** Official d3.i unit mapping/conversion subset used by i3.b callbacks. */
class i private constructor() {
    fun d(value: Float, unit: Int): Float = when (unit) {
        1 -> p2.a.a.d(value) // Kelvin -> Celsius
        2 -> p2.a.a.c(value) // Fahrenheit -> Celsius
        else -> value
    }

    fun i(value: Float, unit: Int): Float = when (unit) {
        1 -> p2.a.a.b(value) // Celsius -> Kelvin
        2 -> p2.a.a.a(value) // Celsius -> Fahrenheit
        else -> value
    }

    fun j(unit: Int, moduleType: ModuleType): Int =
        if (moduleType != ModuleTypeF2ModuleType.F23 && Z2.a.a.p().k() != 12) {
            when (unit) { 1 -> 0; 2 -> 1; 3 -> 2; else -> unit }
        } else unit

    fun k(
        uploadInfo: IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO,
        enableCenter: Boolean,
        enableHigh: Boolean,
        enableLow: Boolean,
        thermometryRegionExperts: List<*>,
        overlayEnabled: Boolean,
        alarmStatus: Int,
        alarmTempHighC: String,
        alarmTempLowC: String,
        osdPosition: Int,
        displayMode: Int,
        moduleType: ModuleType,
        degree: Int,
    ): HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO {
        val result = HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO()
        initializeHeader(result)
        val unit = j(uploadInfo.enumTempUnit, moduleType)
        result.temp_Info.GlobalInfo.apply {
            tempUnit = unit
            refTempkey = uploadInfo.byRefTempkey
            f32Distance = uploadInfo.fDistance
            refTemp = uploadInfo.fRefTemp
            emissionRate = uploadInfo.fEmissionRate
            centerTmp = i(uploadInfo.fAvrTmp, unit)
            minTmp = i(uploadInfo.fMinTmp, unit)
            maxTmp = i(uploadInfo.fMaxTmp, unit)
            uploadInfo.ifrPointArr.take(2).forEachIndexed { index, point ->
                points[index].x = point.x
                points[index].y = point.y
            }
        }
        result.temp_Info.Upload.apply {
            tempUnit = unit
            bShowMaxTemp = if (enableHigh) 1 else 0
            bShowMinTemp = if (enableLow) 1 else 0
            bShowAvgTemp = if (enableCenter) 1 else 0
            ifrOutcomeList.regionNum.apply {
                pointNum = uploadInfo.pointNum
                boxNum = uploadInfo.boxNum
                lineNum = uploadInfo.lineNum
                total = uploadInfo.total
            }
            uploadInfo.ifrOutcomeInfoArr.forEachIndexed { index, source ->
                val target = ifrOutcomeList.ifrOutcome[index]
                target.enable = source.enable
                target.regionId = source.regionld
                target.regiontype = source.regiontype
                target.name = source.name.copyOf()
                target.emissionRate = source.emissionRate
                target.minTmp = i(source.minTmp, unit)
                target.maxTmp = i(source.maxTmp, unit)
                target.avrTmp = i(source.avrTmp, unit)
                target.diffTmp = i(source.diffTmp, unit)
                source.points.take(2).forEachIndexed { pointIndex, point ->
                    target.points[pointIndex].x = point.x
                    target.points[pointIndex].y = point.y
                }
            }
        }
        return result
    }

    fun m(
        thermalPrivateInfo: HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO,
        overlayEnabled: Boolean,
        alarmStatus: Int,
        alarmTempHighC: String,
        alarmTempLowC: String,
        osdPosition: Int,
        degree: Int,
    ): HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO {
        thermalPrivateInfo.temp_Info.Upload.u8TMInfoPosition = osdPosition.toByte()
        if (!overlayEnabled) {
            thermalPrivateInfo.temp_show.Global_SC.tempListSC.lefTopSC.tempSC.forEach { it.bShow = 0 }
        }
        return thermalPrivateInfo
    }

    private fun initializeHeader(info: HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO) {
        info.privateInfo_header.apply {
            private_data_info_head = 1_346_652_488
            private_data_type = 0
            private_data_version = 0
            has_ext = 0
            total_len = 27_592
            lib_version = 0
            dsp_std_stamp = 1_760
            st_temp_param_info.data_len = 8_764
            st_temp_param_info.data_offset = 120
            st_temp_show_control.data_len = 18_708
            st_temp_show_control.data_offset = 8_884
        }
    }

    companion object { @JvmField val a: i = i() }
}
