package com.hik.viewercommon.data.device.api.callback

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.jna.FStreamCallBack_JNA

/**
 * Official-package callback holder mirrored from HIKMICRO Viewer:
 * F2ModuleStreamCallback(FStreamCallBack_JNA, FStreamCallBack).
 */
class F2ModuleStreamCallback(
    private var fStreamCallBackJNAValue: FStreamCallBack_JNA?,
    private var fStreamCallBackValue: FStreamCallBack?,
) {
    fun getFStreamCallBackJNA(): FStreamCallBack_JNA? = fStreamCallBackJNAValue

    fun getFStreamCallBack(): FStreamCallBack? = fStreamCallBackValue

    fun setFStreamCallBackJNA(callback: FStreamCallBack_JNA?) {
        fStreamCallBackJNAValue = callback
    }

    fun setFStreamCallBack(callback: FStreamCallBack?) {
        fStreamCallBackValue = callback
    }
}
