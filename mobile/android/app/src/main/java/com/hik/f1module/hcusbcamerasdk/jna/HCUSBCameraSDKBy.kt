package com.hik.f1module.hcusbcamerasdk.jna

import U4.f
import U4.i

class HCUSBCameraSDKBy {
    @f class IFR_POINT { @JvmField @field:i(0) var x: Int = 0; @JvmField @field:i(1) var y: Int = 0 }

    @f class ST_PRIVATE_LINE_DATA_INFO {
        @JvmField @field:i(0) var data_len: Int = 0
        @JvmField @field:i(1) var data_offset: Int = 0
    }

    @f class PRIVATE_DATA_INFO_HEADER {
        @JvmField @field:i(0) var private_data_info_head: Int = 0
        @JvmField @field:i(1) var total_len: Int = 0
        @JvmField @field:i(2) var has_ext: Byte = 0
        @JvmField @field:i(3) var private_data_type: Int = 0
        @JvmField @field:i(4) var private_data_version: Byte = 0
        @JvmField @field:i(5) var res = ByteArray(8)
        @JvmField @field:i(6) var lib_version: Short = 0
        @JvmField @field:i(7) var dsp_std_stamp: Int = 0
        @JvmField @field:i(8) var st_temp_param_info = ST_PRIVATE_LINE_DATA_INFO()
        @JvmField @field:i(9) var st_temp_show_control = ST_PRIVATE_LINE_DATA_INFO()
        @JvmField @field:i(10) var res1 = ByteArray(68)
    }

    @f class IFR_POLYGON { @JvmField @field:i(0) var pointNum = 0; @JvmField @field:i(1) var pointList = Array(12) { IFR_POINT() } }

    @f class IFR_GLOBLE_OUTCOME_INFO {
        @JvmField @field:i(0) var tempUnit = 0
        @JvmField @field:i(1) var res = ByteArray(19)
        @JvmField @field:i(2) var u8minTmpStat: Byte = 0
        @JvmField @field:i(3) var u8maxTmpStat: Byte = 0
        @JvmField @field:i(4) var u8avrTmpStat: Byte = 0
        @JvmField @field:i(5) var u8cenTmpStat: Byte = 0
        @JvmField @field:i(6) var refTempkey: Byte = 0
        @JvmField @field:i(7) var f32Distance = 0f
        @JvmField @field:i(8) var refTemp = 0f
        @JvmField @field:i(9) var emissionRate = 0f
        @JvmField @field:i(10) var minTmp = 0f
        @JvmField @field:i(11) var maxTmp = 0f
        @JvmField @field:i(12) var avrTmp = 0f
        @JvmField @field:i(13) var centerTmp = 0f
        @JvmField @field:i(14) var diffTmp = 0f
        @JvmField @field:i(15) var points = Array(2) { IFR_POINT() }
        @JvmField @field:i(16) var res1 = ByteArray(100)
    }

    @f class IFR_OUTCOME_INFO {
        @JvmField @field:i(0) var enable: Byte = 0
        @JvmField @field:i(1) var regionId: Byte = 0
        @JvmField @field:i(2) var reserved = ByteArray(31)
        @JvmField @field:i(3) var u8minTmpStat: Byte = 0
        @JvmField @field:i(4) var u8maxTmpStat: Byte = 0
        @JvmField @field:i(5) var u8avgTmpStat: Byte = 0
        @JvmField @field:i(6) var regiontype = 0
        @JvmField @field:i(7) var name = ByteArray(32)
        @JvmField @field:i(8) var emissionRate = 0f
        @JvmField @field:i(9) var minTmp = 0f
        @JvmField @field:i(10) var maxTmp = 0f
        @JvmField @field:i(11) var avrTmp = 0f
        @JvmField @field:i(12) var diffTmp = 0f
        @JvmField @field:i(13) var points = Array(2) { IFR_POINT() }
        @JvmField @field:i(14) var polygon = IFR_POLYGON()
    }

    @f class IFR_TM_REGION_NUM { @JvmField @field:i(0) var pointNum: Byte = 0; @JvmField @field:i(1) var boxNum: Byte = 0; @JvmField @field:i(2) var lineNum: Byte = 0; @JvmField @field:i(3) var total: Byte = 0 }

    @f class IFR_OUTCOME_LIST {
        @JvmField @field:i(0) var regionNum = IFR_TM_REGION_NUM()
        @JvmField @field:i(1) var reserved = ByteArray(8)
        @JvmField @field:i(2) var ifrOutcome = Array(21) { IFR_OUTCOME_INFO() }
    }

    @f class PTZ_INFO_PARAM {
        @JvmField @field:i(0) var p = 0; @JvmField @field:i(1) var t = 0; @JvmField @field:i(2) var z = 0
        @JvmField @field:i(3) var ptz_state: Byte = 0; @JvmField @field:i(4) var focus_state: Byte = 0; @JvmField @field:i(5) var track_state: Byte = 0
        @JvmField @field:i(6) var reserved = ByteArray(1); @JvmField @field:i(7) var rawTilt: Short = 0; @JvmField @field:i(8) var h_inspect_angle: Short = 0
        @JvmField @field:i(9) var v_inspect_angle: Short = 0; @JvmField @field:i(10) var reserved2 = ByteArray(2)
    }

    @f class IFR_ALARM_INFO {
        @JvmField @field:i(0) var alarmRule: Byte = 0; @JvmField @field:i(1) var regionId: Byte = 0; @JvmField @field:i(2) var regiontype = 0
        @JvmField @field:i(3) var alarmType = 0; @JvmField @field:i(4) var alarmLevel = 0; @JvmField @field:i(5) var alarmkey: Byte = 0
        @JvmField @field:i(6) var u8IsFaceRegion: Byte = 0; @JvmField @field:i(7) var ruleTmpData = 0f; @JvmField @field:i(8) var measureTmpData = 0f
        @JvmField @field:i(9) var toleranceTmp = 0f; @JvmField @field:i(10) var points = Array(2) { IFR_POINT() }; @JvmField @field:i(11) var polygon = IFR_POLYGON()
        @JvmField @field:i(12) var AlarmTime = 0; @JvmField @field:i(13) var preAlarmTime = 0; @JvmField @field:i(14) var reserved = ByteArray(4)
    }

    @f class IFR_DIFF_ALARM_INFO {
        @JvmField @field:i(0) var regionSet = ByteArray(2); @JvmField @field:i(1) var alarmRule: Byte = 0; @JvmField @field:i(2) var alarmType = 0
        @JvmField @field:i(3) var reserved = ByteArray(2); @JvmField @field:i(4) var reserved1 = ByteArray(3); @JvmField @field:i(5) var alarmLevel = 0
        @JvmField @field:i(6) var measureTmpData = 0f; @JvmField @field:i(7) var ruleTmpData = 0f; @JvmField @field:i(8) var toleranceTmp = 0f
    }

    @f class IFR_LINE_NORM_INFO {
        @JvmField @field:i(0) var start = IFR_POINT(); @JvmField @field:i(1) var end = IFR_POINT(); @JvmField @field:i(2) var num = 0
        @JvmField @field:i(3) var pseudonum = 0; @JvmField @field:i(4) var digitalZoomRatio = 0; @JvmField @field:i(5) var res = ByteArray(36)
        @JvmField @field:i(6) var norma = ByteArray(640)
    }

    @f class IFR_UPLOAD_INFO {
        @JvmField @field:i(0) var reserved = ByteArray(11); @JvmField @field:i(1) var version: Short = 0; @JvmField @field:i(2) var update_enable: Byte = 0
        @JvmField @field:i(3) var bFreez = 0; @JvmField @field:i(4) var tmProssMode: Byte = 0; @JvmField @field:i(5) var tempUnit = 0
        @JvmField @field:i(6) var u8TMInfoPosition: Byte = 0; @JvmField @field:i(7) var fontSize: Byte = 0; @JvmField @field:i(8) var digitalZoomRatio = 0
        @JvmField @field:i(9) var zoomRatio: Short = 0; @JvmField @field:i(10) var presetId: Short = 0; @JvmField @field:i(11) var normalRGB: Short = 0
        @JvmField @field:i(12) var preAlarmRGB: Short = 0; @JvmField @field:i(13) var alarmRGB: Short = 0; @JvmField @field:i(14) var res = ByteArray(2)
        @JvmField @field:i(15) var bShowMaxTemp: Byte = 0; @JvmField @field:i(16) var bShowMinTemp: Byte = 0; @JvmField @field:i(17) var bShowAvgTemp: Byte = 0
        @JvmField @field:i(18) var ptzInfo = PTZ_INFO_PARAM(); @JvmField @field:i(19) var ifrOutcomeList = IFR_OUTCOME_LIST(); @JvmField @field:i(20) var alarmOutcome = Array(21) { IFR_ALARM_INFO() }
        @JvmField @field:i(21) var alarmDiffOutcome = Array(4) { IFR_DIFF_ALARM_INFO() }; @JvmField @field:i(22) var normaInfo = IFR_LINE_NORM_INFO()
    }

    @f class PRIVATE_TEMP_INFO { @JvmField @field:i(0) var GlobalInfo = IFR_GLOBLE_OUTCOME_INFO(); @JvmField @field:i(1) var Upload = IFR_UPLOAD_INFO(); @JvmField @field:i(2) var enable = IntArray(3); @JvmField @field:i(3) var enableCnt = 0; @JvmField @field:i(4) var res = ByteArray(32) }

    @f class FONT_PRE_BUF { @JvmField @field:i(0) var data = ByteArray(32) }
    @f class FONT_BACKGROUND { @JvmField @field:i(0) var bShow: Byte = 0; @JvmField @field:i(1) var res0 = ByteArray(3); @JvmField @field:i(2) var colorRGBA = 0; @JvmField @field:i(3) var fAlpha = 0f }
    @f class FONT_SHOW_CONTROL { @JvmField @field:i(0) var bShow: Byte = 0; @JvmField @field:i(1) var temperature_accuracy: Byte = 0; @JvmField @field:i(2) var res0 = ByteArray(2); @JvmField @field:i(3) var fontSize = 0; @JvmField @field:i(4) var colorRGBA = 0; @JvmField @field:i(5) var preBuf = FONT_PRE_BUF(); @JvmField @field:i(6) var background = FONT_BACKGROUND(); @JvmField @field:i(7) var res = IntArray(2) }
    @f class SHAPE_SHOW_CONTROL { @JvmField @field:i(0) var bShow: Byte = 0; @JvmField @field:i(1) var res0 = ByteArray(3); @JvmField @field:i(2) var type = 0; @JvmField @field:i(3) var size = 0; @JvmField @field:i(4) var colorRGBA = 0; @JvmField @field:i(5) var res = IntArray(2) }
    @f class TEMP_INFO_SHOW_CONTROL { @JvmField @field:i(0) var bShow: Byte = 0; @JvmField @field:i(1) var res0 = ByteArray(3); @JvmField @field:i(2) var nameSC = FONT_SHOW_CONTROL(); @JvmField @field:i(3) var tempSC = Array(4) { FONT_SHOW_CONTROL() }; @JvmField @field:i(4) var pos = IFR_POINT(); @JvmField @field:i(5) var res = IntArray(4) }
    @f class TEMP_INFO_SINGLE_SHOW_CONTROL { @JvmField @field:i(0) var tempSC = FONT_SHOW_CONTROL(); @JvmField @field:i(1) var pos = IFR_POINT(); @JvmField @field:i(2) var res = IntArray(4) }
    @f class TEMP_LIST_SHOW_CONTROL { @JvmField @field:i(0) var lefTopSC = TEMP_INFO_SHOW_CONTROL(); @JvmField @field:i(1) var ruleAroundSC = TEMP_INFO_SHOW_CONTROL(); @JvmField @field:i(2) var res = IntArray(4) }
    @f class IFR_GLOBLE_INFO_SHOW_CONTROL { @JvmField @field:i(0) var tempListSC = TEMP_LIST_SHOW_CONTROL(); @JvmField @field:i(1) var cursorSC = Array(3) { SHAPE_SHOW_CONTROL() }; @JvmField @field:i(2) var pseudoSC = Array(2) { TEMP_INFO_SINGLE_SHOW_CONTROL() }; @JvmField @field:i(3) var res = ByteArray(16) }
    @f class IFR_OUTCOME_INFO_SHOW_CONTROL { @JvmField @field:i(0) var tempListSC = TEMP_LIST_SHOW_CONTROL(); @JvmField @field:i(1) var cursorSC = Array(2) { SHAPE_SHOW_CONTROL() }; @JvmField @field:i(2) var ruleSC = SHAPE_SHOW_CONTROL(); @JvmField @field:i(3) var res = ByteArray(16) }
    @f class IFR_OUTCOME_LIST_SHOW_CONTROL { @JvmField @field:i(0) var regionNum = 0; @JvmField @field:i(1) var ifrOutcome_SC = Array(21) { IFR_OUTCOME_INFO_SHOW_CONTROL() }; @JvmField @field:i(2) var res = IntArray(2) }
    @f class IFR_UPLOAD_INFO_SHOW_CONTROL { @JvmField @field:i(0) var ifrOutcomeList_SC = IFR_OUTCOME_LIST_SHOW_CONTROL() }
    @f class PRIVATE_TEMP_INFO_SHOW_CONTROL { @JvmField @field:i(0) var Global_SC = IFR_GLOBLE_INFO_SHOW_CONTROL(); @JvmField @field:i(1) var Upload_SC = IFR_UPLOAD_INFO_SHOW_CONTROL(); @JvmField @field:i(2) var res = ByteArray(32) }
    @f class THERMAL_PRIVATE_INFO { @JvmField @field:i(0) var privateInfo_header = PRIVATE_DATA_INFO_HEADER(); @JvmField @field:i(1) var temp_Info = PRIVATE_TEMP_INFO(); @JvmField @field:i(2) var temp_show = PRIVATE_TEMP_INFO_SHOW_CONTROL() }
}
