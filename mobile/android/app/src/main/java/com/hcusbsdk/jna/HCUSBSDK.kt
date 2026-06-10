package com.hcusbsdk.jna

import com.sun.jna.Native

/**
 * Official-shaped singleton facade for libHCUSBSDK.so. The Viewer APK exposes
 * HCUSBSDK.getInstance() before JavaInterface/F2UsbModuleHelper use the JNA
 * SDK; this repo-owned class keeps that same public shape.
 */
object HCUSBSDK {
    @Volatile
    private var instance: HCUSBSDKByJNA? = null

    @JvmStatic
    fun configureLibraryPath(nativeLibraryDir: String) {
        if (nativeLibraryDir.isNotBlank()) {
            System.setProperty("jna.library.path", nativeLibraryDir)
        }
    }

    @JvmStatic
    fun getInstance(): HCUSBSDKByJNA {
        return instance ?: synchronized(this) {
            instance ?: Native.load("HCUSBSDK", HCUSBSDKByJNA::class.java).also { instance = it }
        }
    }

    @JvmStatic
    fun resetForRetry() {
        synchronized(this) {
            instance = null
        }
    }
}
