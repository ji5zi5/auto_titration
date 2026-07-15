package com.hik.viewercommon.data.device.api.callback

import com.hcusbsdk.Interface.FStreamCallBack
import com.hcusbsdk.jna.HCUSBSDKByJNA
import m2.a

/**
 * Official-package callback holder mirrored from HIKMICRO Viewer:
 * F2ModuleStreamCallback(HCUSBSDKByJNA.FStreamCallBack, FStreamCallBack).
 *
 * Production F2 preview passes a null JNA callback and uses the interface/JNI
 * callback. A non-null JNA callback is reserved for explicit manual diagnostics.
 */
class F2ModuleStreamCallback(
    private var fStreamCallBackJNA: HCUSBSDKByJNA.FStreamCallBack?,
    private var fStreamCallBack: FStreamCallBack?,
) : a {
    fun getFStreamCallBackJNA(): HCUSBSDKByJNA.FStreamCallBack? = fStreamCallBackJNA
    fun setFStreamCallBackJNA(value: HCUSBSDKByJNA.FStreamCallBack?) { fStreamCallBackJNA = value }
    fun getFStreamCallBack(): FStreamCallBack? = fStreamCallBack
    fun setFStreamCallBack(value: FStreamCallBack?) { fStreamCallBack = value }
}
