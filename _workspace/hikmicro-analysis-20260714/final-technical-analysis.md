# HIKMICRO Viewer 2.6.0 Mini2 Android 경로 역분석 및 현재 앱 비교

- 분석일: 2026-07-14
- 대상 공식 패키지: `com.hikvision.thermalGoogle`, HIKMICRO Viewer 2.6.0 (versionCode 142)
- 비교 대상: `/home/jio/code/auto_titration/mobile/android`
- 분석 성격: 정적 DEX/ELF/asset 분석과 저장된 실기기 오류 증거의 대조
- 실기기 검증 상태: 이 분석 세션에서는 새 Mini2 실기기 실행을 수행하지 못함

## 1. 결론

현재 Android 앱은 공식 앱의 핵심 F2 호출 이름과 일부 순서를 재현했지만, **공식 앱과 완전히 동일한 구현은 아니다.** 특히 다음 세 가지 차이가 실제 동작 실패와 직접 연결된다.

1. 공식 앱은 장치에서 읽은 **모듈 ID와 펌웨어 빌드 날짜로 F2 프로필을 선택**한다. 현재 앱은 `256x344`, 25 fps, thermal coding 12, streamingNew=true를 고정한다. 이 값은 공식 `f3.h`/`f3.j` 계열에는 맞지만 모든 Mini2 계열에 적용되는 값이 아니다.
2. 공식 앱은 콜백 패킷의 `dwBufSize`가 선택 프로필의 허용 크기 목록에 있는지 먼저 검사하고, coding 12의 특정 오프라인 패킷을 별도 경로로 분기한다. 현재 앱은 크기 목록을 선언해 놓고도 사실상 모든 비어 있지 않은 패킷을 전달한 뒤 **패킷 0번 바이트부터 16비트 raw 온도 행렬이라고 가정**한다. 이 가정은 공식 처리 구조와 다르며, 화면 왜곡·낮은 프레임·무의미한 raw 값의 가장 강한 원인이다.
3. 현재 앱은 `libMTlib`, `libMicroJITA`, `libMicroTA`, `lib_thermal_module`을 포함하지만 F2 실시간 패킷에서 영상·raw·append/측온 정보를 분리하여 섭씨로 변환하는 공식 체인을 완성하지 않았다. 실제 코드도 섭씨 출력을 차단한다.

공식 UI의 F2 기본 시작 경로는 **직접 JNA 콜백이 아니라 JNI 콜백**이다. `PreviewFragmentII.D9()`는 `F2ModuleStreamCallback(null, previewManager.R())`를 만들고, `F2UsbModuleApi.startStreamPreview()`가 `getFStreamCallBack()`을 꺼내 `F2UsbModuleHelper.startStreamPreview()`로 전달한다. 그 아래에서 `JavaInterface.USB_StartStreamCallback()` → 비공개 `USB_StartStreamCallback_jni()` → `HCUSBSDKByJNI.USB_StartStreamCallback()` → `libHCUSBSDK.so` JNI export로 내려간다. 현재 앱의 기본 경로도 이 방향으로 맞춰져 있다. 과거에 JNA 콜백을 기본으로 추정한 구현은 공식 UI 경로와 달랐다.

과거 오류 84에 관해서는 저장소 테스트와 당시 test-spec에 `256x392`로 `USB_SetVideoParam`이 성공한 뒤 `USB_StartStreamCallback`에서 error 84가 발생했다는 기대 문자열이 남아 있다. 다만 그 테스트가 읽던 `asdf.txt` 원문은 현재 작업공간과 git 이력에서 사라졌으므로 이는 1차 로그가 아니라 **2차 보존 증거**다. 그 기록이 정확하다는 조건에서, 공식 2.6.0 프로필에는 `256x392`가 없으므로 지원되지 않는 스트림 형상 또는 native UVC 실제 시작 단계 실패가 가장 강한 설명이다. 오류 29도 테스트 기대값에는 coding 8과 12 사례가 남지만 원문 `error6.txt`/`error8.txt`는 없다. 공식 앱이 `USB_SetThermalStreamParam` 실패를 비치명적으로 처리한다는 사실은 DEX로 별도 확정된다. 정적 바이너리에서 숫자 29의 공식 기호명을 복구하지 못했으므로 정확한 의미를 단정할 수 없다. 공식 코드와 현재 코드 모두 이 요청의 조건 채널을 1로 설정하므로 “콜백 반환 채널 0과 조건 채널 1의 불일치”를 원인으로 보는 주장은 근거가 없다.

## 2. 분석 대상과 무결성

원본 XAPK:

- 경로: `/mnt/c/Users/Jio/Downloads/HIKMICRO Viewer_2.6.0_APKPure.xapk`
- SHA-256: `019801077bb42ffb2d7ca4bda88a87f48324041366d5ade037b7f3bca3616958`
- 패키지: `com.hikvision.thermalGoogle`
- 버전: 2.6.0 / 142
- minSdk 24, targetSdk 35
- base APK 1개와 언어·밀도 split APK 18개

base APK:

- 보존 경로: `.omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/xapk/com.hikvision.thermalGoogle.apk`
- SHA-256: `6e8e22b70d460fa22767394cc1a16ccb794669238dd36dc657f7a8bef2c92e42`
- DEX: 4개
- ARM64 native library: 88개

해시 원문은 `evidence/hashes.txt`, 압축 해제 목록은 `evidence/extracted-inventory.txt`, 재현용 Androguard 대상 추출 코드는 `evidence/decompile_targets.py`에 저장했다. 분석에는 `/home/jio/code/sshs app/.venv/bin/python`에 이미 설치되어 있던 **Androguard 실행 환경만 사용**했으며, `sshs app`의 소스나 데이터는 대상에 포함하지 않았다.

## 3. USB 장치에서 F1/F2를 선택하는 공식 로직

공식 `Z2.g.a(boolean)`의 분기는 다음과 같다.

| Vendor ID | Product ID | 공식 분기 |
|---:|---:|---|
| 11231 (`0x2BDF`) | 320 | F1 |
| 11231 (`0x2BDF`) | 257 또는 258 | F2 |
| 8367 | 임의 | F2 |
| 그 외 | 그 외 | NONE |

근거: `evidence/dad/Z2_g.java:441-465`.

선택된 타입은 `Z2.j.e(UsbModuleType)`에서 실제 API 객체로 바뀐다.

- F1 → `com.hik.viewercommon.data.device.api.F1UsbModuleApi`
- F2 → `com.hik.viewercommon.data.device.api.F2UsbModuleApi`
- 나머지 → `NoneUsbModuleApi`

근거: `evidence/dad/Z2_j.java:29-48`.

저장된 오류 증거의 장치는 vendor 11231, product 258이므로 공식 분기상 F2가 맞다. 따라서 이 장치의 주 조사 대상은 F1 `_thermal_module` 경로가 아니라 F2 `HCUSBSDK` 경로다. F1 경로를 폴백으로 실행하는 것은 진단 목적일 수 있으나, 공식 라우팅을 그대로 복제한 기본 경로는 아니다.

## 4. 공식 USB 권한 획득과 F2 열기 호출 순서

### 4.1 권한 호출자와 승인 후 진입점

공식 앱은 `MainActivity`가 보유한 `MainActivity$r`을 `UsbPermissionManager`의 구체 구현으로 사용한다. `MainActivity.n2()`는 이 manager의 `c()`를 호출하고 (`evidence/dad/com_hikvision_thermal_MainActivity.java:1109-1112`), manager는 연결 장치가 있으면 CAMERA 권한을 먼저 확인한 뒤 USB 권한 확인으로 넘어간다 (`evidence/dad/com_hik_modulelib_manager_UsbPermissionManager.java:56-70,73-101`).

USB 권한 helper `n2.c.a(...)`의 실제 순서는 다음과 같다.

1. `UsbManager`와 연결 대상 `UsbDevice`를 얻는다.
2. `UsbManager.hasPermission(device)`를 확인한다.
3. 권한이 이미 있으면 `hasPermission` callback을 즉시 실행한다.
4. 권한이 없으면 안내/거부 처리 callback을 준비한 뒤 `n2.c$b.invoke()`로 이동한다.
5. `com.hik.library.action.USB_PERMISSION` intent를 package-scoped `PendingIntent`로 만들고 `UsbManager.requestPermission(device, pendingIntent)`를 호출한다.

근거: `evidence/dad/n2_c.java:4-21`, `evidence/dad/n2_c__b.java:24-37`.

`UsbPermissionManager$usbBroadcastReceiver$1`은 위 action의 `permission` extra를 읽는다. 승인되면 manager의 `l()`을 호출하고, 거부면 수동 거부 여부를 판별하여 `k(boolean)`을 호출한다 (`evidence/dad/com_hik_modulelib_manager_UsbPermissionManager__usbBroadcastReceiver__1.java:11-50`). 공식 `MainActivity$r.l()`은 승인 로그를 남긴 뒤 F1이면 USB module view model의 open을, F2이면 sensor/module 쪽 open 진입점을 호출한다 (`evidence/dad/com_hikvision_thermal_MainActivity__r.java:179-214`). 따라서 **승인 broadcast 이후에 openUsbModule 계층으로 진입**하는 것이 공식 상위 lifecycle이다.

그 아래 `JavaInterface.USB_GetDeviceCount(Context)`도 방어적으로 Android enumeration을 수행한다. `EnumerateDevice.EnumDevice(Context)`는 각 장치에 대해 다시 `hasPermission()`을 확인하고 없으면 `com.android.example.USB_PERMISSION` pending intent로 `requestPermission()`을 호출하며, 권한이 있는 경우 `openDevice()`의 fd를 저장한다 (`evidence/dad/com_hcusbsdk_Interface_EnumerateDevice.java:217-262`). 이 내부 요청은 비동기 승인 전에 즉시 open을 시도할 수 있으므로, 안정적인 공식 정상 경로는 상위 `UsbPermissionManager`가 승인을 받은 뒤 F2 open으로 진입하는 경로다.

현재 앱은 `Mini2UsbProbe.kt:275-348`에서 `hasPermission`을 확인하고 앱 전용 pending intent로 `requestPermission`한 뒤 broadcast 결과를 처리한다. 이 설계는 공식 상위 lifecycle과 같은 Android 권한 모델을 사용한다.

### 4.2 F2 open

공식 `F2UsbModuleApi.openUsbModule()`은 `F2UsbModuleHelper.openUsbDevice(Context)`를 호출하며 실패 시 최대 5회 범위에서 재시도하고, 재시도 번호에 비례해 500 ms 단위로 대기한다. 근거는 `evidence/dad/com_hik_viewercommon_data_device_api_F2UsbModuleApi.java:466-495`이다.

`F2UsbModuleHelper.openUsbDevice(Context)` 내부의 확인된 순서는 다음과 같다.

1. `USB_GetSDKVersion()`
2. `USB_Init()`
3. `USB_GetDeviceCount(Context)`
4. `USB_EnumDevices(count)`
5. 이전 user/channel이 남아 있으면 `USB_StopChannel()`
6. 이전 user가 남아 있으면 `USB_Logout()`
7. 열거된 `deviceInfoList[0]`으로 `USB_Login(...)`
8. 로그인 실패 시 상태 정리

근거: `evidence/dad/com_hik_f2module_F2UsbModuleHelper.java:2874-2930`.

여기서 `USB_GetDeviceCount(Context)`가 중요하다. 공식 `JavaInterface`는 Android `Context`를 받은 열거 모드를 통해 `UsbManager.openDevice()`로 확보한 file descriptor가 `USB_DEVICE_INFO.dwFd`에 반영되도록 한다. 단순 native `USB_GetDeviceCount()`만 호출하는 경로와 같지 않다. 현재 앱도 `F2UsbModuleHelper.kt:109-116`에서 context-aware count와 enum을 먼저 수행하므로 이 부분은 방향이 맞다.

공식 로그인 구조체의 주요 필드는 `byLoginMode`, `dwDevIndex`, `dwFd`, `dwPID`, `dwTimeout`, `dwVID`, serial/user/password 문자열이다. 근거: `evidence/dad/com_hcusbsdk_Interface_USB_USER_LOGIN_INFO.java:1-16`. 장치 구조체는 `dwFd`, `dwIndex`, `dwPID`, `dwVID`, 제조사·제품·일련번호와 오디오 유무를 가진다. 근거: `evidence/dad/com_hcusbsdk_Interface_USB_DEVICE_INFO.java:1-16`.

## 5. 공식 F2 스트림 시작 경로: JNI가 기본

### 5.1 실제 UI 호출자

공식 `PreviewFragmentII.D9()`는 다음 의미의 객체를 만든다.

```text
F2ModuleStreamCallback(
  fStreamCallBackJNA = null,
  fStreamCallBack = previewManager.R()
)
```

근거: `evidence/dad/PreviewFragmentII_C9_D9.java:25-49`. 즉 공식 UI는 JNA 콜백 슬롯을 비우고 interface/JNI 콜백만 넣는다.

`F2ModuleStreamCallback`에는 `getFStreamCallBack()`과 `getFStreamCallBackJNA()`가 모두 있지만, UI가 넘긴 값 때문에 기본 화면 경로는 전자를 사용한다. 근거: `evidence/dad/com_hik_viewercommon_data_device_api_callback_F2ModuleStreamCallback.java:13-22`.

### 5.2 API와 helper의 정확한 순서

`F2UsbModuleApi.startStreamPreview(m2.a)`는 콜백을 `F2ModuleStreamCallback`으로 캐스팅하고 `getFStreamCallBack()`을 꺼낸 다음 현재 선택된 프로필에서 다음 값을 읽는다.

- `p().a()` → stream preview size
- `p().l()` → frame rate
- `p().k()` → thermal video coding type
- `p().m()` → streamingNew

그 후:

1. 기존 `stopStreamPreview(Context, streamingNew)` 실행
2. `startStreamPreview(callback, size, fps, coding, 103, streamingNew)` 실행

근거: `evidence/dad/com_hik_viewercommon_data_device_api_F2UsbModuleApi.java:835-900`.

helper 내부 순서는 다음과 같다.

1. `USB_SetVideoParam(size, fps, streamType=103)`
2. `USB_STREAM_CALLBACK_PARAM.dwStreamType = 103`
3. `USB_StartStreamCallback(callbackParam)`
4. 성공 시 `USB_SetThermalStreamParam(coding)`
5. `Thread.sleep(100)`
6. `USB_SetThermalStreamCtrl(true)`

근거: `evidence/dad/com_hik_f2module_F2UsbModuleHelper.java:2933-2971`.

공식 앱에서는 `dwVideoFormat`과 콜백 `dwStreamType` 모두 103이다. 둘을 임의로 분리해 101/102/104/201 계열을 순차 시도하는 ladder는 공식 UI 흐름에 없다. 또한 공식 `USB_SetVideoParam` helper는 반환값을 상위 시작 성공 여부로 사용하지 않고 실패를 로그로 남긴 뒤 callback 시작을 계속 시도한다. 현재 앱은 `F2UsbModuleHelper.kt:311-327` 및 `440-456`에서 SetVideo 실패 시 즉시 중단하므로 더 안전한 진단 동작이지만 공식 동작과 1:1은 아니다.

### 5.3 JNI 전달 경로

공식 기본 경로의 실제 계층은 다음과 같다.

```text
PreviewFragmentII.D9
  → F2ModuleStreamCallback(null, PreviewManagerII.R())
  → F2UsbModuleApi.startStreamPreview
  → F2UsbModuleHelper.startStreamPreview
  → JavaInterface.USB_StartStreamCallback
  → JavaInterface.USB_StartStreamCallback_jni
  → HCUSBSDKByJNI.USB_StartStreamCallback
  → Java_com_hcusbsdk_jni_HCUSBSDKByJNI_USB_1StartStreamCallback
  → libHCUSBSDK.so / libuvc
```

`USB_StartStreamCallback_jni`이라는 정확한 메서드는 `evidence/dad/com_hcusbsdk_Interface_JavaInterface.java:806` 부근에서 확인되며, JNI export는 `evidence/native-dynamic-and-target-symbols.txt`에 저장되어 있다.

직접 JNA용 `F2UsbModuleHelper.startStreamPreviewJNA()`도 공식 APK 안에 존재한다. 그러나 복구한 호출 참조에서는 synthetic default wrapper 외에 공식 UI 호출자가 없었고, `D9()`의 생성 인자도 JNA 슬롯을 null로 만든다. 따라서 “JNA가 존재한다”와 “JNA가 공식 기본 경로다”는 구분해야 한다.

## 6. 공식 F2 프로필 선택

`d3.l`은 모듈 ID 집합을 정의하고, 장치 격리 정보의 module ID와 firmware 문자열 마지막 날짜를 읽어 `Z2.a.p`에 프로필 객체를 저장한다. 근거: `evidence/dad/d3_l.java:13-24,114-203`.

| 모듈 ID 집합 | 펌웨어 날짜 조건 | 프로필 | preview size | fps | thermal coding | streamingNew | 대표 허용 패킷 크기 |
|---|---:|---|---:|---:|---:|---|---|
| 0953560101, 0953560104, 0953560105 | ≤ 20221121 | `f3.i` | 192x520 | 25 | 8 | false | 102944 등 |
| 동일 | 20221122–20231115 | `f3.f` | 192x520 | 25 | 11 | false | 206392 등 |
| 동일 | 20231116–20231229 | `f3.g` | 256x344 | 25 | 12 | false | 101320, 183496, 98304 |
| 동일 | > 20231229 | `f3.h` | 256x344 | 25 | 12 | true | `f3.g` 계승 |
| 0953510000, 0953510100 | ≤ 20231116 | `f3.c` | 288x776 | 50 | 11 | false | 453688 등 |
| 동일 | 20231117–20231229 | `f3.d` | 384x512 | 50 | 12 | false | 193480, 400584, 221184 |
| 동일 | > 20231229 | `f3.e` | 384x512 | 50 | 12 | true | `f3.d` 계승 |
| 0953060001, 0953060002 | 전체 | `f3.j` | 256x344 | 25 | 12 | true | 203720, 183496 |
| 0953080000 | 전체 | `f3.b` | 96x176 | 25 | 12 | true | 61384, 41160 |

크기 상수는 `evidence/dad/Z2_a.java:25-47`, 프로필별 값은 `evidence/dad/f3_b.java`부터 `f3_j.java`, 선택 경계는 `evidence/dad/d3_l.java:164-198`에 있다.

현재 앱의 `F2UsbModuleHelper.kt:22-28`은 256x344, 25, coding 12를 고정하고 `F2UsbModuleApi.kt:54,69`에서 streamingNew 기본값을 true로 둔다. 그러므로 실제 연결 장치가 `f3.h` 또는 `f3.j`로 선택되는 모듈/펌웨어라면 시작 인자는 공식 값과 맞는다. 실제 module ID와 firmware 날짜가 로그에 없으므로 **해당 실기기에서 이 프로필이 맞다고 확정할 수는 없다.** 장치 정보 명령으로 두 값을 읽고 동일 selector를 구현해야 한다.

## 7. 콜백 구조체와 패킷 전달

### 7.1 공식 callback DTO

공식 public `com.hcusbsdk.Interface.USB_FRAME_INFO`에는 다음이 있다.

- `nStamp`
- `dwStreamType`
- `dwWidth`, `dwHeight`
- `dwFrameRate`
- `dwFrameType`, `dwDataType`
- `nFrameNum`
- `pBuf` 10,485,760 bytes
- `dwBufSize`

근거: `evidence/dad/com_hcusbsdk_Interface_USB_FRAME_INFO.java:1-19`.

공식 JNI `com.hcusbsdk.jni.USB_FRAME_INFO`는 `USB_CONFIG`를 상속하고, 같은 메타데이터 외에 `pBuf` 8,294,400 bytes 및 `byRes` 128 bytes를 가진다. 근거: `evidence/dad/com_hcusbsdk_jni_USB_FRAME_INFO.java:1-22`.

공식 public callback param은 `dwStreamType`과 `FStreamCallBack` **두 필드뿐**이고, JNI param은 `USB_CONFIG`를 상속한 뒤 `dwSize`, `dwStreamType`, `byRes[128]`을 가진다. 근거: `evidence/dad/com_hcusbsdk_Interface_USB_STREAM_CALLBACK_PARAM.java:1-9`와 `com_hcusbsdk_jni_USB_STREAM_CALLBACK_PARAM.java:1-12`.

현재 public callback param은 `Interface/USB_STREAM_CALLBACK_PARAM.kt:3-7`에서 공식 두 필드 외에 `dwSize`와 `byRes[128]`을 추가한다. 현재 JNI callback param은 `jni/USB_STREAM_CALLBACK_PARAM.kt:3-6`에서 세 필드 자체는 공식과 같지만 `USB_CONFIG` 상속을 생략한다. 즉 native에 직접 전달되는 JNI param의 주요 값은 맞아도 Java 클래스 구조는 1:1이 아니며, public DTO는 명백히 필드 집합이 다르다.

현재 앱의 JNI DTO는 `mobile/android/app/src/main/java/com/hcusbsdk/jni/USB_FRAME_INFO.kt:3-16`에서 pBuf를 10 MiB로 만들고 `USB_CONFIG` 상속을 생략했다. public DTO에는 공식 public 클래스에는 없는 `byRes[128]`도 추가했다 (`Interface/USB_FRAME_INFO.kt:12-23`). 필드의 의미는 유사하지만 바이너리·클래스 구조가 완전히 동일하지 않다. JNI가 native 객체의 Java 필드를 이름으로 채우는 형태라면 일부 차이는 허용될 수 있지만, 정확한 ABI 호환은 실기기 callback으로 확인해야 한다.

### 7.2 공식 `PreviewManagerII`의 size gate

공식 `PreviewManagerII$d.invoke()`는 다음을 수행한다.

1. `dwBufSize`만큼 `pBuf`를 정확히 복사한다.
2. 현재 프로필 `Z2.a.p().e()`가 그 크기를 포함하는지 검사한다.
3. 허용되지 않은 크기는 폐기한다.
4. `183496`, `400584`, `183496`, `41160`은 별도 “offline stream info” 크기로 본다.
5. thermal coding이 12이고 offline 크기이면 `r0` 버퍼 경로, 아니면 `s0` 버퍼 경로로 보낸다.
6. 40초 이상 유효 프레임이 없으면 상위 재시도 callback을 호출한다.

근거: `evidence/dad/com_hik_viewer_manager_PreviewManagerII__d.java:12-65`.

`PreviewManagerII`는 20 ms 주기의 작업에서 두 버퍼를 소비한다. 일반 `s0` 패킷은 `G(byte[])`로 처리하고, offline `r0` 패킷도 별도로 `G(byte[])`에 넣은 뒤 비운다. 근거: `evidence/dad/com_hik_viewer_manager_PreviewManagerII.java:831-895`. 즉 callback은 단순히 “raw 행렬을 받은 것”이 아니라 **프로필별 컨테이너 패킷을 player/decoder 계층에 넘기는 입구**다.

현재 `PreviewManagerII.kt:45-68`은 허용 크기 여부를 계산하지만 `bytes = if (acceptedByOfficialShape || copied.isNotEmpty()) copied ...`로 작성되어 있어 비어 있지 않은 모든 패킷을 통과시킨다. 따라서 공식 size gate가 실질적으로 작동하지 않는다.

그 다음 `HikmicroJnaMini2Stream.kt:381-441`은 전달받은 bytes의 시작부터 little-endian 16비트 값을 읽어 최대 256x192 행렬로 간주한다. 공식 패킷에는 영상, 부가정보, 측온 구조, CRC, 헤더가 섞일 수 있으므로 이 파서는 공식 구조와 호환되지 않는다. 이 차이는 콜백 성공 후에도 화면이 비정상이고 온도가 나오지 않는 현상을 설명한다.

### 7.3 F2 thermal 패킷 구조의 존재

DEX에는 다음 계열 구조가 존재한다.

- `USB_THERMAL_STREAM_REALTIME`
- `USB_THERMAL_STREAM_TEMP_S`
- `USB_THERMAL_STREAM_TEMP_HOT` / `_OLD`
- `USB_THERMAL_STREAM_TEMP_YUV`
- `USB_THERMAL_STREAM_TEMP_YUV_OFFLINE`
- `USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_LITE`
- `USB_THERMAL_STREAM_TEMP_YUV_OFFLINE_12_LITE`

공통적으로 magic, stream type/length, CRC/header, 실시간 측온 결과, RT YUV 정보, 보충 정보, offline 측정 설정 같은 필드가 확인된다. `_12_LITE`에는 `res0[20]`, stream 보충 정보 일부 `[12]`, realtime data `[48]`, RT YUV `[36]`, CRC `[4]`, tempMeasureCfg `[2072]`, extendGeneralInfo `[656]`가 있다. 근거 파일은 `evidence/dad/com_hik_f2module_IFR_INFO__USB_THERMAL_STREAM_*.java`다.

Androguard DAD가 일부 JNA `getFieldOrder()`를 불완전하게 복원했으므로 이 문서는 해당 decompile만으로 C 메모리 오프셋 전체를 확정하지 않는다. 다만 “콜백 payload 전체가 곧 256x192 raw 행렬”이라는 현재 가정이 공식 클래스 설계와 맞지 않는다는 사실은 충분히 확정된다.

## 8. APK fixture가 보여 주는 영상·raw·append 구성

공식 APK assets에는 다음 fixture가 있다.

| fixture | raw | yuv | append | 산술 검증 |
|---|---:|---:|---:|---|
| `F2V2179` | 98,304 | 73,728 | 2,048 | raw = 256×192×2, YUV420 = 256×192×3/2 |
| `F0364` | 18,432 | 13,824 | 768 | raw = 96×96×2, YUV420 = 96×96×3/2 |

특히 `F2V2179.raw`는 정확히 256×192개의 16비트 샘플이고, `F2V2179.yuv`는 같은 해상도의 YUV420 한 프레임이다. `F0364.raw`와 `.yuv`도 96×96에 정확히 맞는다. 원본 크기는 `evidence/extracted-inventory.txt:1-6`에 있다.

이 결과는 공식 처리 체인이 영상 plane, 16비트 raw plane, append metadata를 구분한다는 강한 증거다. 그러나 이 세 asset이 실시간 callback packet에서 단순히 `raw || yuv || append` 순으로 이어진다고 단정할 수는 없다. 실제 callback 허용 크기 101,320·183,496·203,720 등은 fixture 각 파일의 단순 합과 항상 일치하지 않으며, 앞 절의 구조체 헤더·variant 분기가 존재한다. 따라서 fixture는 **컴포넌트 형상 검증 자료**로 사용하고, 실시간 패킷 오프셋은 device profile별 parser 또는 동적 trace로 확정해야 한다.

## 9. 온도 변환 체인

### 9.1 native export로 확정된 기능

- `libMTlib.so`: `MT_Gray2Temp`, `MT_Gray2Temp_INT`, `MT_Grayrange_INT`
- `libMicroJITA_Release_v8a.so`: exported `MicroSDK::grayToTemperature`, `MicroSDK::temperatureToGray`, `MicroSDK::getTemperatureMark`; `TempAnalyzer` 관련 undefined imports
- `libMicroTA_Release_v8a.so`: `MicroSDK::TempAnalyzer` 생성자, `calculate`, `temperatureTable`, `getTemperatureMark`, 측정 환경/모델 설정 계열 exports
- `lib_thermal_module.so`: `thermal_function_stream_realtime_init`, `thermal_init_thermal_module`, `thermal_function_get_msg`, `thermal_function_set_msg`

근거: 원시/기본 export는 `evidence/native-dynamic-and-target-symbols.txt`, `readelf -Ws | c++filt`로 다시 생성한 demangled 증거는 `evidence/native-temperature-symbols-demangled.txt`에 있다. 이 파일은 정의된 심볼과 `UND` import를 구분해 보존한다.

### 9.2 근거 수준별 판단

**확정:** F1 live 경로는 `_thermal_module`을 초기화하고 realtime callback으로 `THERMAL_DATA_INFO` 계열 구조를 받는다. 공식 callback은 내부 YUV pointer/length를 읽고 회전·변환한 뒤 전체 구조를 player로 전달한다. 근거: `evidence/dad/com_hik_viewer_manager_PreviewManagerII__e.java` 및 F1 helper.

**확정:** F2 live callback은 선택 profile의 허용 packet size와 thermal coding에 따라 패킷 variant를 분기한 뒤 player/decoder 계층으로 넘긴다. 단순 raw offset 0 처리가 아니다.

**강한 추론:** F2의 섭씨 계산은 packet에서 raw/append/측온 설정을 분리한 뒤 MTlib 또는 MicroTA/JITA 계열을 사용하거나, 패킷에 이미 포함된 realtime 측온 결과를 해석한다. 구조체와 export가 이를 지지한다.

**미확정:** Viewer 2.6.0에서 모든 F2 live frame마다 정확히 어느 Java 메서드가 `MT_Gray2Temp`를 직접 호출하는지, profile별 packet 내부 raw 시작 오프셋과 계수, 오류 29의 공식 enum 이름은 정적 분석만으로 완전히 복구되지 않았다. 이 부분은 Frida/JNI trace 또는 실기기 메모리 dump가 필요하다.

현재 앱은 `HikmicroTemperatureConversionAttempt.kt:42-72`에서 `fixtureCompared=false`, `liveStreamObserved=false`로 고정하고 `celsiusAllowed=false`를 만든다. 따라서 native library를 포함해도 Android 섭씨 출력은 현재 구현상 차단된다. 이는 웹 UI의 온도가 0 또는 미출력인 현상과 일치한다.

## 10. native library 비교

공식 base APK의 ARM64 `.so`는 88개이고 현재 Android 소스의 jniLibs에는 38개가 있다. 공통 38개는 모두 바이트 단위 SHA-256이 동일하다. 전체 표는 `evidence/native-hash-comparison.tsv`에 있다.

핵심 동일 파일:

| 라이브러리 | SHA-256 |
|---|---|
| `libHCUSBSDK.so` | `7c7efac3fbdc7db3cb07b6602c1b0df8e7ecca7c4636f9fffb17e0791f8c34bd` |
| `libMTlib.so` | `9d49df15bdb19341c2b6b3f44557ce4791b60abd63ac019dbea4b0842c839798` |
| `libMicroJITA_Release_v8a.so` | `beb3db1ed3d6b14e42e8572e8d60a341f9761ea3289d094acc76cdaaead42ea2` |
| `libMicroTA_Release_v8a.so` | `59e43b832fbdbb09dc840d3d4905fb13968d05f692512ef0dccd8420337d67d8` |
| `lib_thermal_module.so` | `c9c879dab64c43426c150cd9a3eabf8e89170a7fe2f5881b8c99ecf6b13aed9e` |
| `libusbCam_host.so` | `61a58d58bee20c88d79107ef15639251384f7c98df70207f76c29db8de327c5c` |

`libHCUSBSDK.so`의 ELF NEEDED 항목은 `libusb1.0.so`, `libuvc.so`, `libdl.so`, `liblog.so`, `libstdc++.so`, `libm.so`, `libc.so`다. F2 핵심 직접 의존 라이브러리는 현재 패키지에 포함되어 있다. 공식에만 있는 50개는 네트워크 카메라, Flutter, crash reporting, playback 등 전체 Viewer 기능도 포함하므로 “50개가 없어서 Mini2가 반드시 실패한다”고 볼 근거는 없다.

현재 Gradle은 `net.java.dev.jna:jna:5.18.1@aar`을 명시하며 (`app/build.gradle.kts:59-73`), `dist/auto_titrator-debug.apk` 안에도 ARM64 `libjnidispatch.so`가 실제 포함되어 있다. 따라서 과거 `NoClassDefFoundError: com.sun.jna...`는 현재 소스의 필연적 상태가 아니라 JNA dependency를 넣기 전 APK 또는 stale APK 설치 가능성이 높다. 이 판단의 신뢰도는 높지만, 해당 오류가 발생한 APK 자체의 해시가 보존되지 않아 100% 특정할 수는 없다.

## 11. F1 경로 비교

공식 F1 open 순서는 Android `UsbManager.openDevice()` → usbfs/bus/dev/fd 파싱 → cacheDir 기반 ISP 주소 설정 → `_thermal_module` open-device 메시지 → `thermal_function_alarm_init` → `thermal_function_stream_realtime_init` → `thermal_init_thermal_module` → alarm enable이다. start는 preview enable 메시지, stop은 preview disable 메시지, close는 detach/open-device 정리 메시지를 사용한다. 근거: `evidence/dad/com_hik_f1module_F1UsbModuleHelper.java` 및 `com_hik_viewercommon_data_device_api_F1UsbModuleApi.java`.

현재 `HikmicroF1Mini2Stream.kt:110-196`은 open, ISP, alarm/stream init, thermal init, alarm/preview enable까지 best-effort로 구현했다. 그러나 `stopCurrentSession()`은 `HikmicroF1Mini2Stream.kt:335-339`에서 connection만 닫고 공식 preview disable/detach 메시지를 보내지 않는다. callback도 공식 전체 `THERMAL_DATA_INFO`가 아니라 `THERMAL_DATA_INFO_MINI` 안의 `YUV_INFO`만 가정한다 (`302-329`, `497-500`). 따라서 F1도 완전 복제가 아니다. 다만 연결 장치 VID/PID 11231:258은 공식 분기상 F2이므로, 이 차이는 현재 장치의 첫 번째 원인으로 보지 않는다.

## 12. 현재 앱 불일치와 우선순위

### P0 — 실제 프레임 해석을 막는 차이

1. **동적 profile selector 부재**  
   현재: `F2UsbModuleHelper.kt:22-28`, `F2UsbModuleApi.kt:66-90`에서 256x344/25/coding12/streamingNew=true 고정.  
   공식: module ID와 firmware 날짜로 `f3.b`~`f3.j` 선택.  
   영향: 실제 장치가 다른 프로필이면 error 84, frame-size reject, thermal param reject가 반복될 수 있다.

2. **공식 packet size gate가 선언만 되고 무력화됨**  
   현재: `PreviewManagerII.kt:54-65`에서 `acceptedByOfficialShape || copied.isNotEmpty()` 때문에 모든 non-empty packet 통과.  
   공식: 선택 profile의 `e()` 목록과 정확히 일치하지 않으면 drop.  
   영향: 다른 구조/깨진 packet도 raw parser로 들어간다.

3. **payload offset 0을 16비트 raw로 오인**  
   현재: `HikmicroJnaMini2Stream.kt:381-441`.  
   공식: packet variant와 offline 여부를 나눈 뒤 decoder/player에서 처리.  
   영향: 왜곡·회전 문제와 별개로 영상 내용 자체가 비정상, raw min/max/평균 무의미, ROI 온도 계산 불가능.

4. **섭씨 변환 미구현**  
   현재: `HikmicroTemperatureConversionAttempt.kt:42-72`가 영구적으로 미검증 상태를 생성.  
   영향: native library 로드 성공과 무관하게 온도는 나오지 않는다.

### P1 — 장치 상태와 재시도 안정성 차이

5. **공식 stop lifecycle보다 짧은 확인 횟수**  
   현재: `F2UsbModuleHelper.kt:29`, `644-656`에서 최대 8 retry.  
   공식: thermal ctrl off를 poll하고 context-aware 재열거 후 다시 disable하며 약 100회 범위까지 확인한 뒤 StopChannel.  
   영향: 버튼을 여러 번 눌렀을 때 이전 channel/thermal ctrl 상태가 남아 다음 시작을 방해할 수 있다.

6. **SetVideo 실패 처리 차이**  
   현재: 실패 즉시 중단 (`311-327`, `440-456`).  
   공식: 실패 로그 후 StartStreamCallback까지 진행.  
   영향: 안전성에는 유리하지만 1:1 복제는 아니며, 오류 비교 로그의 단계가 달라진다.

7. **공식 API 클래스의 패키지·signature 불일치**  
   공식: `com.hik.viewercommon.data.device.api.F2UsbModuleApi`, 공통 `ApiResult`, `init/close` lifecycle.  
   현재: `com.hik.f2module.F2UsbModuleApi`, 프로젝트 전용 결과 타입과 인자.  
   영향: native ABI 직접 문제라기보다 공식 상위 lifecycle을 일부 빠뜨릴 위험.

### P2 — 완전성·진단 차이

8. **JNI wrapper 불완전**  
   현재 `HCUSBSDKByJNI.kt:8-16`에는 Start/Stop만 있고 공식 export에 존재하는 `USB_GetDeviceConfig`가 없다. 또한 JNI DTO 상속/버퍼 크기가 다르다.

9. **F1 stop/detach 및 전체 callback 구조 미복제**  
   F2 장치에는 2차 우선순위지만 완전한 공식 구조라는 주장은 불가능하다.

10. **안전장치와 진단 메시지는 프로젝트 고유 기능**  
    passive peek, crash guard, stale-session reset, 사용자용 blocked 상태는 공식 Viewer와 다르지만 자동 적정 앱에는 유지할 가치가 있다. “공식과 동일한 호출 핵심”과 “우리 앱의 안전장치”를 코드에서 분리해야 한다.

## 13. 과거 오류의 원인 판정

### 오류 84 — `USB_StartStreamCallback`

원문 `asdf.txt`는 현재 존재하지 않는다. 남아 있는 것은 `tests/test_android_webview_mini2.py:839-855`의 replay 기대값과 당시 `.omx/plans/test-spec-mini2-official-exact-clone-asdf-error84-20260531T013416Z.md`다. 두 파일의 SHA-256과 해당 내용을 `evidence/historical-error-secondary-evidence.txt`에 복사해 보존했다. 이 2차 증거에는 `USB_SET_VIDEO_PARAM=ok videoFormat=103 size=256x392 fps=25` 다음 `startStream=failed error=84`가 기록되어 있다. 이 기록이 원래 로그를 정확히 전사했다는 조건에서, 공식 프로필 상수에는 256x392가 없고 `libHCUSBSDK`는 SetVideo 설정 후 실제 UVC stream control/start 단계로 내려가므로 다음과 같이 판정한다.

- **중간 신뢰도(2차 로그 조건부):** 256x392가 실제 장치 profile과 맞지 않아 native UVC start에서 실패했다.
- **중간 신뢰도:** 이전 channel/USB 상태가 완전히 정리되지 않은 lifecycle 문제도 오류를 강화했을 수 있다.
- **미확정:** 숫자 84의 공식 enum 명칭과 사라진 원문 로그의 완전한 문맥.

현재 256x344로 바꾼 것은 `f3.h/j` 장치에는 올바른 수정이다. 그러나 실제 module ID/firmware를 읽지 않는 한 모든 기기에 대한 해결이라고 할 수 없다.

### 오류 29 — `USB_SetThermalStreamParam`

원문 `error6.txt`와 `error8.txt`도 현재 존재하지 않는다. 테스트에 남은 기대값은 coding 8과 coding 12 모두 error 29가 있었다고 기록한다 (`tests/test_android_webview_mini2.py:573-580,625-650,922-932`; 복사본 `evidence/historical-error-secondary-evidence.txt`). 이 관찰 자체는 2차 증거다. 반면 공식 helper가 `USB_SetThermalStreamParam` 결과와 무관하게 StartStreamCallback 성공 후 100 ms 대기와 thermal ctrl enable을 계속한다는 것은 DEX 1차 증거로 확정된다. 현재 앱도 최근 코드에서 `failed_nonfatal`로 처리한다 (`F2UsbModuleHelper.kt:358-374`, `486-502`).

- **높은 신뢰도:** error 29만으로 전체 callback 시작을 실패 처리하는 것은 공식 동작과 다르다.
- **중간 신뢰도:** 선택 profile의 coding 또는 장치 상태/firmware가 해당 요청을 거절했을 가능성.
- **배제:** callback channel 0인데 thermal param condition channel이 1이라서 실패했다는 설명. 공식 `JavaInterface.USB_SetThermalStreamParam`도 condition channel을 1로 만든다.
- **미확정:** error 29의 공식 enum 명칭과 장치별 허용 조건.

### JNA class crash

현재 Gradle과 debug APK에는 JNA/JNI dispatch가 존재하므로 같은 현재 APK에서 `com.sun.jna` class가 없어서 죽는 상태는 재현되지 않는다. 과거 APK 잔존 또는 설치 파일 혼동 가능성이 가장 높다. 최종 배포 전에는 APK SHA-256과 versionName/versionCode를 화면·로그에 표시해 stale APK 여부를 제거해야 한다.

### callback은 왔지만 화면·온도가 이상함

이 문제는 start parameter보다 뒤 단계다. 공식 packet container를 파싱하지 않고 payload 첫 바이트부터 raw로 읽는 현재 코드가 직접 원인이다. frame rotation 버튼은 표시 방향만 바꾸며 packet layout 오류를 고치지 못한다. 온도 0은 raw 저장 방식 때문만이 아니라 섭씨 converter가 실제로 호출되지 않고 gate에서 차단되기 때문이다.

## 14. 구현 가능한 수정 사양

1. **공식 profile selector를 먼저 구현한다.** 장치 로그인 후 공식과 같은 device isolation/system info 명령으로 module ID와 firmware version을 읽고, `d3.l`의 경계와 `f3.*` 값을 프로젝트 타입으로 옮긴다. 선택 결과, 입력 문자열, profile name, size/fps/coding/streamingNew/allowedSizes를 로그와 CSV metadata에 남긴다. 값이 없으면 임의 hardcode로 스트림을 시작하지 말고 “profile unresolved” 진단을 표시한다.
2. **공식 JNI callback을 유일한 기본 경로로 유지한다.** `F2ModuleStreamCallback(null, interfaceCallback)` 형태를 보장한다. JNA callback은 수동 진단 빌드에만 남기고 자동 fallback으로 실행하지 않는다.
3. **`PreviewManagerII`의 exact size gate를 복원한다.** 현재 profile의 allowed size에 없는 packet을 drop하고, 40초 무유효-frame watchdog을 둔다. accepted 여부가 false인데 non-empty라는 이유로 통과시키는 조건을 제거한다.
4. **packet variant parser를 구현한다.** coding 8/11/12 및 일반/offline packet을 분리하고, magic/header/stream length/CRC/RT YUV/realtime outcome/temp config를 구조체 길이에 맞춰 검증한다. 검증 전에는 payload를 raw 행렬로 보지 않는다.
5. **fixture 기반 decoder 단위 테스트를 만든다.** `F2V2179.raw`는 256x192×16-bit, `.yuv`는 256x192 YUV420, `.append`는 2048 bytes임을 검증한다. `F0364`도 96x96로 같은 검증을 한다. fixture를 합성 packet parser의 기대 plane과 비교하되, live packet offset은 동적 trace로 확인될 때까지 별도 상태로 둔다.
6. **온도 변환 adapter를 분리한다.** raw plane + append/config를 입력으로 받고 MTlib/MicroTA/JITA 중 공식 호출 trace로 확인된 함수만 호출한다. 중앙/ROI/전체 행렬의 섭씨 결과를 공식 앱과 같은 장면에서 비교해 평균·최대 오차를 기록한다. 검증 통과 전 raw를 섭씨로 이름 붙이지 않는다.
7. **stop lifecycle을 공식 수준으로 복원한다.** `USB_SetThermalStreamCtrl(false)` → `USB_GetThermalStreamCtrl` poll → context-aware count/enum → 필요 시 disable 재시도 → `USB_StopChannel` → `USB_Logout` → connection close 순서를 직렬화한다. 확인 버튼 중복 클릭은 같은 mutex/state machine에 합쳐 중첩 open/start를 막는다.
8. **ABI facade를 공식 클래스 구조에 더 가깝게 맞춘다.** JNI `USB_CONFIG` 상속, 공식 pBuf 크기, `USB_GetDeviceConfig`, callback param 필드를 일치시키고 reflection 테스트로 field name/type/default size를 검증한다.
9. **남은 미확정 값은 실기기 trace로 닫는다.** ADB logcat과 Frida로 `USB_SetVideoParam`, JNI Start callback, thermal param/ctrl, callback `dwBufSize`, packet 첫 64 bytes, selected module profile, decoder 함수 호출을 기록한다. 오류 29/84가 나면 같은 시점의 `USB_GetLastError`, profile, fd/user/channel을 단일 trace ID로 묶는다.

## 15. 재현 절차

분석 산출물 루트:

```text
.omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/
```

주요 파일:

- `decompile_targets.py`: 지정 클래스 DAD decompile
- `dad/*.java`: 호출 경로와 구조체 근거
- `profile-xrefs.txt`: profile/호출 참조
- `usb-permission-callers.txt`, `dad/n2_c*.java`, `dad/com_hikvision_thermal_MainActivity__r.java`: 공식 USB 권한 호출자와 승인 후 open 진입
- `native-hash-comparison.tsv`: 공식/현재 `.so` SHA-256 비교
- `native-dynamic-and-target-symbols.txt`: ELF export와 온도 관련 심볼
- `native-temperature-symbols-demangled.txt`: MTlib/MicroJITA/MicroTA/_thermal_module demangled export/import 증거
- `historical-error-secondary-evidence.txt`: 사라진 오류 원문 대신 남은 테스트 기대값, test-spec, 원본 파일 부재 상태와 해시
- `extracted-inventory.txt`: fixture/DEX/native 파일 크기
- `hashes.txt`: XAPK/base APK 무결성

재검증 예시:

```bash
sha256sum '/mnt/c/Users/Jio/Downloads/HIKMICRO Viewer_2.6.0_APKPure.xapk'
sha256sum .omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/xapk/com.hikvision.thermalGoogle.apk
python .omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/decompile_targets.py
readelf -d .omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/apk/lib/arm64-v8a/libHCUSBSDK.so
readelf -Ws .omx/goals/autoresearch/hikmicro-viewer-2-6-0-xapk-mini2-android-auto-ti/evidence/apk/lib/arm64-v8a/libMTlib.so
unzip -l dist/auto_titrator-debug.apk | grep -E 'libjnidispatch|libHCUSBSDK|libMTlib|lib_thermal_module'
```

## 16. 신뢰도와 최종 판정

| 판단 | 신뢰도 | 근거/한계 |
|---|---|---|
| 11231:258은 공식 F2 분기 | 높음 | `Z2.g.a()` 직접 decompile |
| 공식 UI F2 기본 callback은 JNI | 높음 | `PreviewFragmentII.D9()`의 JNA null + `getFStreamCallBack()` 호출 |
| 공식 시작 인자는 profile size/fps/coding + stream type 103 | 높음 | API/helper 직접 decompile |
| 256x344/25/coding12/streamingNew=true는 일부 최신 profile에 맞음 | 높음 | `f3.h/j`, `Z2.a` |
| 현재 hardcode가 실제 사용 Mini2 V2에 맞음 | 중간 이하 | 실기기 module ID/firmware 미수집 |
| 과거 error 84 기록의 주원인은 256x392/실제 UVC start 형상 | 중간 | 공식 profile에 256x392 없음. 단, 오류 원문이 사라져 test-embedded 2차 증거만 존재 |
| error 29는 channel 0/1 불일치 | 낮음/배제 | 공식도 thermal condition channel 1 사용 |
| error 29가 coding 8/12에서 관찰됨 | 중간 이하 | 원문이 사라져 test-embedded 2차 증거만 존재 |
| error 29의 정확한 enum 의미 | 미확정 | 정적 심볼에서 숫자 매핑 미복구 |
| callback payload offset 0이 raw 행렬 | 낮음/배제 | 공식 size gate와 여러 packet structure 존재 |
| 현재 앱에서 섭씨 온도가 실제 계산됨 | 낮음/배제 | 코드가 celsiusAllowed=false로 차단 |
| 공통 native 38개가 공식 파일과 동일 | 높음 | SHA-256 전수 비교 |
| 현재 앱이 공식 앱 전체 구조와 완전히 동일 | 낮음/배제 | profile/parser/converter/lifecycle/API 구조 차이 |

최종적으로, 반복 오류를 끝내기 위해 가장 먼저 바꿔야 할 것은 또 다른 stream format ladder가 아니다. **실제 장치의 module ID/firmware로 공식 profile을 선택하고, 그 profile의 허용 packet 크기와 packet variant parser를 복원하는 것**이다. JNI 시작 경로 자체는 현재 방향이 맞다. 다음 병목은 callback 이후 패킷 해석과 섭씨 변환 체인이다.
