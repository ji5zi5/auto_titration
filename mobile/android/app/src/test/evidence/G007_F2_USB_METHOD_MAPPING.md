# G007 F2 USB strict parity method mapping

Official evidence source:
`.omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/dad/`

## Method mapping after strict-parity follow-up

| Repo method | Official DAD method | Current behavior |
| --- | --- | --- |
| `JavaInterface.USB_StartStreamCallback` | `com_hcusbsdk_Interface_JavaInterface.java:7122` | Null-param/callback guard, then direct `USB_StartStreamCallback_jni` call; no catch(Throwable)->-1 wrapper. |
| `JavaInterface.USB_StartStreamCallback_jni` | `com_hcusbsdk_Interface_JavaInterface.java:806` | Writes `dwSize=0`, sets `dwStreamType`, calls `HCUSBSDKByJNI.getInstance().USB_StartStreamCallback(...)`, returns raw channel. |
| `JavaInterface.USB_StartStreamCallback_jna` | `com_hcusbsdk_Interface_JavaInterface.java:774` | Writes JNA param with `dwSize=size()`, `pUser=Pointer.NULL`, direct `HCUSBSDK.getInstance().USB_StartStreamCallback(...)`, returns raw channel. |
| `F2UsbModuleApi.startStreamPreview` | `com_hik_viewercommon_data_device_api_F2UsbModuleApi.java:835` | Calls `helper.stopStreamPreview(...)`, then direct `streamCallback.getFStreamCallBack()`, then `helper.startStreamPreview(...)`; repo callback prefetch wrapper removed. |
| `F2UsbModuleApi.startStreamPreviewJNA` | `com_hik_viewercommon_data_device_api_F2UsbModuleApi.java:835` / helper JNA route | Calls `helper.stopStreamPreview(...)`, direct `streamCallback.getFStreamCallBackJNA()`, then `helper.startStreamPreviewJNA(...)`; repo callback prefetch wrapper removed. |
| `F2UsbModuleHelper.openUsbDevice` | `com_hik_f2module_F2UsbModuleHelper.java:2874` | SDK init, context count/enum, previous stop/logout before login, `deviceInfoList[0]` login, cleanup on login failure; no outer fail-soft catch. |
| `F2UsbModuleHelper.startStreamPreview` | `com_hik_f2module_F2UsbModuleHelper.java:2933` | Direct official order: `USB_SetVideoParam`, build `USB_STREAM_CALLBACK_PARAM`, `USB_StartStreamCallback`, if start ok optionally `USB_SetThermalStreamParam`, `Thread.sleep(100)`, `USB_SetThermalStreamCtrl(true)`, return result code semantics. |
| `F2UsbModuleHelper.startStreamPreviewJNA` | `com_hik_f2module_F2UsbModuleHelper.java:2974` | Direct official order with JNA callback param and compatibility interface slot; no candidate ladder or catch wrapper. |
| `F2UsbModuleHelper.stopStreamPreview` | `com_hik_f2module_F2UsbModuleHelper.java:3014` | Thermal ctrl disable/poll/re-enumerate retry, then `USB_StopChannel`; only `InterruptedException` handling remains for official sleep shape. |
| `USB_DEVICE_INFO.closeConnection` | repo Android fd ownership shim | Direct close then null; removed `runCatching` fail-soft wrapper. |

## Removed production seams / wrappers

- Removed `F2UsbModuleApi.wrapCalibrationPrefetchCallbacks` and all API callback-time command-2054 prefetch wrapping.
- Removed `F2UsbModuleApi.setJnaFrameNumberReaderForTest`.
- Removed `F2UsbModuleHelper.resetCalibrationPrefetchForTest`, `setCalibrationPrefetchSchedulerForTest`, and `setCalibrationSessionForTest`.
- Removed `F2StreamFormatCandidate`, `F2StreamStartMode`, `F2ResetMode`, and `formatAttempts` start-candidate machinery from production start routes.
- Remaining `F2StreamAttemptDiagnostic` is an empty ABI compatibility DTO for out-of-scope app-shell callers; start hot paths no longer populate it.

## Remaining unavoidable divergence

- Public Kotlin return types (`F2StartResult`, `F2OpenResult`) remain repo DTOs because out-of-scope callers already compile against them. The hot path now follows official order and result-code semantics inside those DTOs.
- `F2UsbModuleHelper.onPreviewFrameForCalibrationPrefetch(...)` remains as a no-op compatibility method because out-of-scope app-shell code still references it; it does not issue command 2054.
