package w3

import android.graphics.Bitmap
import com.hik.f1module.hcusbcamerasdk.jna.HCUSBCameraSDKBy
import com.hikmicro.pm_hrl_bussinesscmp.model.Frame
import com.hikmicro.pm_hrl_bussinesscmp.model.ThermalModel

/** Official drawer state dependency used by z3.c. */
class k : f {
    private var frame: Frame? = null
    private var frameNumStamp: Int = -1
    private var thermalModel: ThermalModel? = null

    fun m(
        privateInfo: HCUSBCameraSDKBy.THERMAL_PRIVATE_INFO,
        bitmap: Bitmap?,
        point: HCUSBCameraSDKBy.IFR_POINT?,
    ): Bitmap? = bitmap
    fun z(model: ThermalModel) {
        thermalModel = model
        frameNumStamp = model.getFrameNumStamp()
        frame = Frame(model.getNv12ByteArray(), model.getWidth(), model.getHeight(), model.getFrameNumStamp())
    }
    fun r(): Int = frameNumStamp
    fun q(): Frame = frame ?: Frame(frameNumStamp = frameNumStamp)
    fun y(value: Frame?) {
        frame = value
        frameNumStamp = value?.getFrameNumStamp() ?: -1
        if (value == null) thermalModel = null
    }
}
