package com.hik.f2module

import android.util.Size
import com.hik.modulelib.UsbModuleInfo
import com.hik.viewercommon.data.bean.UsbModuleType
import kr.auto.titration.mobile.thermal.HikmicroF2Profile
import kr.auto.titration.mobile.thermal.HikmicroF2ProfileResolution

/** Applies a resolved USB-login profile to the official Viewer runtime globals. */
internal object F2RuntimeProfile {
    fun apply(
        resolution: HikmicroF2ProfileResolution,
        systemInfo: com.hcusbsdk.Interface.USB_SYSTEM_DEVICE_INFO?,
    ): Boolean {
        val profile = resolution.profile ?: return false
        val moduleId = resolution.moduleId?.trim().orEmpty()
        if (moduleId.isEmpty()
            || profile.allowedPacketSizes.isEmpty()
            || profile.allowedPacketSizes.any { it <= 0 }
            || profile.fps <= 0
            || profile.thermalCoding !in setOf(8, 9, 11, 12)
        ) {
            return false
        }

        val candidate = createOfficialProfile(profile) ?: return false
        if (candidate.e().toSet() != profile.allowedPacketSizes
            || candidate.k() != profile.thermalCoding
            || candidate.l() != profile.fps
            || candidate.n() != profile.streamingNew
        ) {
            return false
        }
        val currentProfile = Z2.a.a.p()
        val runtimeProfile = if (equivalent(currentProfile, candidate)) currentProfile else candidate
        val currentIdentity = Z2.g.a.U()
        val nextIdentity = identity(currentIdentity, moduleId, systemInfo)

        Z2.a.a.u(runtimeProfile)
        Z2.g.a.c1(nextIdentity)
        Z2.g.a.d1(UsbModuleType.F2)
        Z2.g.a.D0(UsbModuleType.F2)
        return true
    }

    private fun createOfficialProfile(profile: HikmicroF2Profile): f3.k? = when (profile.officialClassName) {
        "f3.i" -> f3.i()
        "f3.f" -> f3.f()
        "f3.g" -> f3.g()
        "f3.h" -> f3.h()
        "f3.j" -> f3.j()
        "f3.b" -> ResolvedRuntimeProfile(profile, Size(96, 96))
        "f3.c", "f3.d", "f3.e" -> ResolvedRuntimeProfile(profile, Size(288, 384))
        else -> null
    }

    private fun identity(
        current: UsbModuleInfo,
        moduleId: String,
        systemInfo: com.hcusbsdk.Interface.USB_SYSTEM_DEVICE_INFO?,
    ): UsbModuleInfo = if (systemInfo == null) {
        current.copy(moduleID = moduleId)
    } else {
        current.copy(
            firmwareVersion = systemInfo.byFirmwareVersion.ifBlank { current.getFirmwareVersion() },
            hardwareVersion = systemInfo.byHardwareVersion.ifBlank { current.getHardwareVersion() },
            deviceType = systemInfo.byDeviceType.ifBlank { current.getDeviceType() },
            serialNumber = systemInfo.bySerialNumber.ifBlank { current.getSerialNumber() },
            secondHardwareVersion = systemInfo.bySecondHardwareVersion.ifBlank {
                current.getSecondHardwareVersion()
            },
            moduleID = moduleId,
            deviceID = systemInfo.byDeviceID.ifBlank { current.getDeviceID() },
            deviceAssembleType = systemInfo.byDeviceAssembleType.toInt(),
            manufacturer = systemInfo.byManufacturer.toInt(),
            languageType = systemInfo.byLanguageType.toInt(),
            deviceClass = systemInfo.byDeviceClass.toInt(),
        )
    }

    private fun equivalent(left: f3.k, right: f3.k): Boolean =
        left.e() == right.e() &&
            left.i() == right.i() &&
            left.k() == right.k() &&
            left.l() == right.l() &&
            left.m() == right.m() &&
            left.n() == right.n()

    private class ResolvedRuntimeProfile(
        profile: HikmicroF2Profile,
        private val processedSize: Size,
    ) : f3.k {
        private var packetSize = profile.allowedPacketSizes.first()
        private var coding = profile.thermalCoding
        private var frameRate = profile.fps
        private var streamingNew = profile.streamingNew
        private val allowedPacketSizes = profile.allowedPacketSizes.toList()

        override fun a(): Size = processedSize
        override fun b(value: Int) { packetSize = value }
        override fun c(): Size = processedSize
        override fun d(value: Int) { coding = value }
        override fun e(): List<Int> = allowedPacketSizes
        override fun f(): Int = packetSize
        override fun g(): Size = processedSize
        override fun h(value: Boolean) { streamingNew = value }
        override fun i(): Boolean = false
        override fun j(): Size = processedSize
        override fun k(): Int = coding
        override fun l(): Int = frameRate
        override fun m(): Boolean = false
        override fun n(): Boolean = streamingNew
        override fun o(value: Int) { frameRate = value }
    }
}
