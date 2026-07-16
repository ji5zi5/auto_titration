package com.hik.f2module

import U4.f
import U4.i

class IFR_INFO {
    @f
    class IFR_POINT {
        @JvmField @field:i(0) var x: Int = 0
        @JvmField @field:i(1) var y: Int = 0
    }

    @f
    class IFR_OUTCOME_INFO {
        @JvmField @field:i(0) var avrTmp: Float = 0f
        @JvmField @field:i(1) var byRes = ByteArray(2)
        @JvmField @field:i(2) var diffTmp: Float = 0f
        @JvmField @field:i(3) var emissionRate: Float = 0f
        @JvmField @field:i(4) var enable: Byte = 0
        @JvmField @field:i(5) var f32Distance: Float = 0f
        @JvmField @field:i(6) var maxTmp: Float = 0f
        @JvmField @field:i(7) var minTmp: Float = 0f
        @JvmField @field:i(8) var name = ByteArray(32)
        @JvmField @field:i(9) var pointNum: Int = 0
        @JvmField @field:i(10) var points = Array(2) { IFR_POINT() }
        @JvmField @field:i(11) var recod = Array(12) { IFR_POINT() }
        @JvmField @field:i(12) var reftemp: Int = 0
        @JvmField @field:i(13) var regionld: Byte = 0
        @JvmField @field:i(14) var regiontype: Int = 0
        @JvmField @field:i(15) var reservedex = ByteArray(20)
        @JvmField @field:i(16) var u8avgTmpStat: Byte = 0
        @JvmField @field:i(17) var u8maxTmpStat: Byte = 0
        @JvmField @field:i(18) var u8minTmpStat: Byte = 0
        @JvmField @field:i(19) var u8res = ByteArray(1)
    }

    @f
    class IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO {
        @JvmField @field:i(0) var enumTempUnit: Int = 0
        @JvmField @field:i(1) var byRefTempkey: Byte = 0
        @JvmField @field:i(2) var byRes1 = ByteArray(3)
        @JvmField @field:i(3) var fDistance: Float = 0f
        @JvmField @field:i(4) var fRefTemp: Float = 0f
        @JvmField @field:i(5) var fEmissionRate: Float = 0f
        @JvmField @field:i(6) var fEnvTemp: Float = 0f
        @JvmField @field:i(7) var fMinTmp: Float = 0f
        @JvmField @field:i(8) var fMaxTmp: Float = 0f
        @JvmField @field:i(9) var fAvrTmp: Float = 0f
        @JvmField @field:i(10) var ifrPointArr = Array(3) { IFR_POINT() }
        @JvmField @field:i(11) var u32TempMode: Int = 0
        @JvmField @field:i(12) var byRes = IntArray(5)
        @JvmField @field:i(13) var pointNum: Byte = 0
        @JvmField @field:i(14) var boxNum: Byte = 0
        @JvmField @field:i(15) var lineNum: Byte = 0
        @JvmField @field:i(16) var total: Byte = 0
        @JvmField @field:i(17) var byReserved = ByteArray(8)
        @JvmField @field:i(18) var ifrOutcomeInfoArr = Array(21) { IFR_OUTCOME_INFO() }
        @JvmField @field:i(19) var res = IntArray(11)
        @JvmField @field:i(20) var uploadType: Int = 0
        @JvmField @field:i(21) var u32CrcVal: Int = 0
    }

    @f
    open class USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE {
        @JvmField @field:i(0) var res0 = ByteArray(20)
        @JvmField @field:i(1) var streamFsSuppleInfoTemp_without_dwIsFreezedata = ByteArray(12)
        @JvmField @field:i(2) var streamRtDataInfoS = ByteArray(48)
        @JvmField @field:i(3) var rtYuvDataInfoS = ByteArray(36)
        @JvmField @field:i(4) var dwIsFreezedata: Int = 0
        @JvmField @field:i(5) var ifrRealtimeTmOutcomeUploadInfo = IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO()
        @JvmField @field:i(6) var crcVal = ByteArray(4)
        @JvmField @field:i(7) var tempMeasureCfg = ByteArray(2072)
    }

    @f
    class USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_12_LITE {
        @JvmField @field:i(0) var res0 = ByteArray(20)
        @JvmField @field:i(1) var streamFsSuppleInfoTemp_without_dwIsFreezedata = ByteArray(12)
        @JvmField @field:i(2) var streamRtDataInfoS = ByteArray(48)
        @JvmField @field:i(3) var rtYuvDataInfoS = ByteArray(36)
        @JvmField @field:i(4) var dwIsFreezedata: Int = 0
        @JvmField @field:i(5) var ifrRealtimeTmOutcomeUploadInfo = IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO()
        @JvmField @field:i(6) var crcVal = ByteArray(4)
        @JvmField @field:i(7) var tempMeasureCfg = ByteArray(2072)
        @JvmField @field:i(8) var extendGeneralInto = ByteArray(656)
    }

    @f
    class USB_THERMAL_STREAM_TEMP_YUV : USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE()

    @f
    class USB_THERMAL_STREAM_YUV : USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE()
}
