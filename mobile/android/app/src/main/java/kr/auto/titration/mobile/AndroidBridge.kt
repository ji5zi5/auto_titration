package kr.auto.titration.mobile

import android.webkit.JavascriptInterface
import org.json.JSONObject

/** JavaScript bridge exposed to the WebView as `window.AutoTitrationAndroid`. */
class AndroidBridge(private val activity: MainActivity) {
    @JavascriptInterface
    fun getStatusJson(): String = safeJson { activity.buildStatusJson() }

    @JavascriptInterface
    fun probeMini2(): String = safeJson { activity.probeMini2FromBridge() }

    @JavascriptInterface
    fun pumpStatus(): String = safeJson { activity.pumpStatusFromBridge() }

    @JavascriptInterface
    fun pumpDevices(): String = safeJson { activity.pumpDevicesFromBridge() }

    @JavascriptInterface
    fun connectPump(address: String): String = safeJson { activity.connectPumpFromBridge(address) }

    @JavascriptInterface
    fun disconnectPump(): String = safeJson { activity.disconnectPumpFromBridge() }

    @JavascriptInterface
    fun openBluetoothSettings(): String = safeJson { activity.openBluetoothSettingsFromBridge() }

    @JavascriptInterface
    fun sendPumpCommand(command: String): String = safeJson { activity.sendPumpCommandFromBridge(command) }

    @JavascriptInterface
    fun startNewRun(): String = safeJson { activity.startNewRunFromBridge() }

    @JavascriptInterface
    fun lockRoi(): String = safeJson { activity.lockRoiFromBridge() }

    @JavascriptInterface
    fun setVisibleRoi(payloadJson: String): String = safeJson { activity.setVisibleRoiFromBridge(payloadJson) }

    @JavascriptInterface
    fun requestAutoRoiCandidate(payloadJson: String): String = safeJson { activity.requestAutoRoiCandidateFromBridge(payloadJson) }

    @JavascriptInterface
    fun autoSetRoi(): String = safeJson { activity.autoSetRoiFromBridge() }

    @JavascriptInterface
    fun rotateThermalPreview(): String = safeJson { activity.rotateThermalPreviewFromBridge() }

    @JavascriptInterface
    fun startRecording(configJson: String): String = safeJson { activity.startRecordingFromBridge(configJson) }

    @JavascriptInterface
    fun stopRecording(): String = safeJson { activity.stopRecordingFromBridge() }

    @JavascriptInterface
    fun csvPreviewJson(): String = safeJson { activity.csvPreviewJsonFromBridge() }

    @JavascriptInterface
    fun saveCsvToDownloads(): String = safeJson { activity.saveCsvToDownloadsFromBridge() }

    @JavascriptInterface
    fun getCrashReport(): String = safeJson { activity.crashReportJsonFromBridge() }

    @JavascriptInterface
    fun clearCrashReport(): String = safeJson { activity.clearCrashReportFromBridge() }

    private fun safeJson(block: () -> JSONObject): String {
        return try {
            block().toString()
        } catch (error: Throwable) {
            JSONObject()
                .put("ok", false)
                .put("error", error.message ?: error.javaClass.simpleName)
                .put("mode", "android_webview")
                .toString()
        }
    }
}
