package h3

import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy
import com.hik.f2module.IFR_INFO

/** Official h3 marker interface. */
interface a

data class b(private val privateInfo: HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO) : a {
    fun a(): HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO = privateInfo
}

data class c(private val uploadInfo: IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO) : a {
    fun a(): IFR_INFO.IFR_REALTIME_TM_OUTCOME_UPLOAD_INFO = uploadInfo
}
