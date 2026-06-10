(() => {
  const bridge = window.AutoTitrationAndroid;
  if (!bridge) return;

  const $android = (id) => document.getElementById(id);
  const ANDROID_LABEL = 'Android WebView';
  const MAX_VISIBLE_MINI2_DIAGNOSTIC_CHARS = 420;
  const MINI2_OFFICIAL_PRIMARY_MODE = 'OFFICIAL_PRIMARY';
  const MINI2_MANUAL_PROBE_MIN_INTERVAL_MS = 10000;
  let mini2ManualProbePromptShown = false;
  let mini2ManualProbeInFlight = false;
  let lastMini2ManualProbeAt = 0;
  let latestAndroidPreviewFrameId = 0;
  let latestAndroidThermalFrameId = 0;
  let latestAndroidRoiRevision = 0;
  let latestMini2DiagnosticExport = null;
  window.AutoTitrationRoiDraftActive = false;

  function setAndroidText(id, value) {
    const element = $android(id);
    if (element) element.textContent = value;
  }

  function escapeSvgText(value) {
    return String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;');
  }

  function splitSvgLines(value, maxChars, maxLines) {
    const raw = String(value ?? '').replace(/\s+/g, ' ').trim();
    if (!raw) return [];
    const lines = [];
    let remaining = raw;
    while (remaining && lines.length < maxLines) {
      if (remaining.length <= maxChars) {
        lines.push(remaining);
        break;
      }
      const boundary = Math.max(
        remaining.lastIndexOf(' ', maxChars),
        remaining.lastIndexOf(';', maxChars),
        remaining.lastIndexOf('·', maxChars),
      );
      const cut = boundary > Math.floor(maxChars * 0.45) ? boundary + 1 : maxChars;
      lines.push(remaining.slice(0, cut).trim());
      remaining = remaining.slice(cut).trim();
    }
    if (remaining && lines.length === maxLines) {
      lines[lines.length - 1] = `${lines[lines.length - 1].replace(/[.…]+$/, '')}…`;
    }
    return lines;
  }

  function truncateMini2DiagnosticText(value, maxChars = MAX_VISIBLE_MINI2_DIAGNOSTIC_CHARS) {
    const text = String(value ?? '').replace(/\s+/g, ' ').trim();
    if (text.length <= maxChars) return text;
    return `${text.slice(0, Math.max(0, maxChars - 1)).trim()}…`;
  }

  function classifyMini2StageReport(stageReport, reason = '') {
    const text = `${stageReport || ''} ${reason || ''}`;
    if (/USB permission denied|mini2_usb_permission["']?\\s*[:=]\\s*false|permission_state["']?\\s*[:=]\\s*denied/i.test(text)) {
      return 'usb_permission_denied_before_native_stream';
    }
    if (/USB permission requested|USB permission pending|waiting for Android grant/i.test(text)) {
      return 'usb_permission_pending_before_native_stream';
    }
    if (/passive status polling|official HCUSBSDK\/JNI stream is not started/i.test(text)) {
      return 'manual_probe_not_run_passive_status_guard';
    }
    if (/USB_SET_THERMAL_STREAM_PARAM=failed_nonfatal.*official_continue_after_thermal_param_result/i.test(text)) {
      return 'thermal_stream_param_nonfatal_waiting_for_frame';
    }
    if (/USB_StartStreamCallback=ok.*USB_SET_THERMAL_STREAM_PARAM=failed.*error=29|USB_SetThermalStreamParam failed error=29/i.test(text)) {
      return 'thermal_stream_param_failed_error29_after_callback_ok';
    }
    if (/USB_GetDeviceCount\\(context\\)=\\d+.*USB_EnumDevices=true.*nativeEnum=count=0/i.test(text)) {
      return 'context_enum_login_ok_native_enum_secondary';
    }
    if (/USB_SET_VIDEO_PARAM=ok.*(?:startStream=failed|USB_StartStreamCallback failed).*error=84/i.test(text)) {
      return 'callback_start_failed_error84_after_video_ok';
    }
    if (/USB_SET_VIDEO_PARAM=failed.*error=21|command=3004 error=21/i.test(text)) {
      return 'video_param_failed_error21';
    }
    if (/all_start_paths_failed|blocked_native_stream/i.test(text)) {
      return 'all_start_paths_failed_blocked_no_celsius';
    }
    if (/converter|MTlib|MicroTA|temperature/i.test(text)) {
      return 'converter_status_secondary_not_raw_stream_blocker';
    }
    return 'mini2_diagnostic_unclassified';
  }

  function buildMini2DiagnosticExport(payload = {}) {
    const mini2 = payload.mini2 || {};
    const live = payload.live || {};
    const rawStream = mini2.raw_stream || {};
    const lastAttempt = mini2.last_stream_attempt || rawStream;
    const currentPresence = mini2.current_usb_presence || {};
    const stageReport = lastAttempt.stage_report || rawStream.stage_report || live.mini2_stage_report || '';
    const attempt = lastAttempt.attempt_diagnostics?.[0]
      || lastAttempt.stream_diagnostics?.attempt_diagnostics?.[0]
      || rawStream.attempt_diagnostics?.[0]
      || rawStream.stream_diagnostics?.attempt_diagnostics?.[0]
      || {};
    const route = lastAttempt.device_route || rawStream.device_route || live.mini2_device_route || mini2.mini2_route_reason || currentPresence.route_reason || '';
    const routeMatch = String(route).match(/(\\d+)\\s*[:/]\\s*(\\d+)/);
    const classification = classifyMini2StageReport(stageReport, lastAttempt.reason || rawStream.reason || mini2.mini2_reason || live.mini2_reason);
    const summary = {
      classification,
      route,
      vid: mini2.vid || mini2.vendor_id || routeMatch?.[1] || '',
      pid: mini2.pid || mini2.product_id || routeMatch?.[2] || '',
      fd: attempt.fd ?? lastAttempt.fd ?? rawStream.fd ?? '',
      userId: attempt.userId ?? lastAttempt.userId ?? rawStream.userId ?? '',
      channel: attempt.channel ?? lastAttempt.channel ?? rawStream.channel ?? '',
      startMode: attempt.startMode || attempt.start_mode || '',
      videoFormat: attempt.videoFormat ?? attempt.video_format ?? '',
      callbackStreamType: attempt.callbackStreamType ?? attempt.callback_stream_type ?? '',
      setVideoStatus: attempt.setVideoStatus || attempt.set_video_status || '',
      startStatus: attempt.startStatus || attempt.start_status || lastAttempt.raw_stream_status || rawStream.raw_stream_status || '',
      lastError: attempt.lastError ?? attempt.last_error ?? '',
      error84_after_video_ok: Boolean(lastAttempt.error84_after_video_ok || lastAttempt.stream_diagnostics?.error84_after_video_ok || classification === 'callback_start_failed_error84_after_video_ok'),
      official_wrapper_parity_ok: lastAttempt.official_wrapper_parity_ok ?? lastAttempt.stream_diagnostics?.official_wrapper_parity_ok ?? false,
      official_wrapper_parity: lastAttempt.official_wrapper_parity || lastAttempt.stream_diagnostics?.official_wrapper_parity || {},
      converterStatus: lastAttempt.converter_status || lastAttempt.stream_diagnostics?.converter_status || rawStream.converter_status || rawStream.stream_diagnostics?.converter_status || 'converter_status_secondary_not_raw_stream_blocker',
      rawStageReport: stageReport,
      currentUsbPresence: currentPresence,
      lastStreamAttempt: lastAttempt,
      runtimeMode: mini2.mini2_last_stream_probe_mode || mini2.mini2_runtime_mode || MINI2_OFFICIAL_PRIMARY_MODE,
    };
    return {
      ...summary,
      mini2,
      live,
      generatedAt: new Date().toISOString(),
    };
  }

  function updateMini2DiagnosticExport(payload) {
    const exportPayload = buildMini2DiagnosticExport(payload);
    latestMini2DiagnosticExport = exportPayload;
    const text = JSON.stringify(exportPayload, null, 2);
    const full = $android('mini2FullDiagnosticText');
    if (full) full.value = text;
    const visible = truncateMini2DiagnosticText(`${exportPayload.classification} · ${exportPayload.rawStageReport || exportPayload.converterStatus}`);
    setAndroidText('mini2DebugLabel', visible || '-');
    return text;
  }

  function shouldRunMini2ProbeBeforeDiagnosticCopy(exportPayload) {
    if (!exportPayload) return false;
    const reason = [
      exportPayload.lastStreamAttempt?.reason,
      exportPayload.mini2?.raw_stream?.reason,
      exportPayload.mini2?.mini2_reason,
    ].filter(Boolean).join(' · ');
    const raw = exportPayload.startStatus
      || exportPayload.lastStreamAttempt?.raw_stream_status
      || exportPayload.mini2?.raw_stream_status
      || '';
    const mode = exportPayload.mini2?.mini2_last_stream_probe_mode || exportPayload.runtimeMode || '';
    return exportPayload.classification === 'manual_probe_not_run_passive_status_guard'
      && raw === 'blocked_native_stream'
      && !String(mode).includes('native_stream_manual_one_shot')
      && /passive status polling|official HCUSBSDK\/JNI stream is not started/i.test(reason);
  }

  function readBridgeJson(method, ...args) {
    try {
      const raw = bridge[method](...args);
      return typeof raw === 'string' ? JSON.parse(raw) : raw;
    } catch (error) {
      return { ok: false, error: error.message || String(error), mode: 'android_webview' };
    }
  }

  function runManualMini2Probe(source = 'button') {
    const now = Date.now();
    if (mini2ManualProbeInFlight) {
      setAndroidText('mobilePairStatus', 'Mini2 USB 확인 연타 차단 · 이전 probe 실행 중');
      setAndroidText('previewStatus', 'Mini2 native stream probe가 이미 실행 중입니다. 잠시 기다리세요.');
      return null;
    }
    const elapsed = now - lastMini2ManualProbeAt;
    if (elapsed > 0 && elapsed < MINI2_MANUAL_PROBE_MIN_INTERVAL_MS) {
      const waitMs = Math.ceil((MINI2_MANUAL_PROBE_MIN_INTERVAL_MS - elapsed) / 1000);
      setAndroidText('mobilePairStatus', `Mini2 USB 확인 연타 차단 · ${waitMs}초 뒤 재시도`);
      setAndroidText('previewStatus', 'Mini2 네이티브 세션 정리/재시작 보호 중입니다. 버튼을 연속으로 누르지 않아도 됩니다.');
      return null;
    }
    mini2ManualProbeInFlight = true;
    lastMini2ManualProbeAt = now;
    setAndroidText('mobilePairStatus', `Mini2 확인 중 · ${MINI2_OFFICIAL_PRIMARY_MODE} native_stream_manual_one_shot · ${source}`);
    try {
      const payload = readBridgeJson('probeMini2');
      applyBridgePayload(payload);
      return payload;
    } finally {
      mini2ManualProbeInFlight = false;
    }
  }

  function requireAndroidNonBlank(value, label) {
    const text = String(value ?? '').trim();
    if (!text) throw new Error(`${label}은 비어 있을 수 없습니다`);
    return text;
  }

  function requireAndroidPositiveNumber(value, label) {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) {
      throw new Error(`${label}은 0보다 큰 숫자여야 합니다`);
    }
    return number;
  }

  function buildAndroidRecordingConfig() {
    const payload = typeof buildPumpTimelineStartPayload === 'function'
      ? buildPumpTimelineStartPayload()
      : {
          titration_type: $android('titrationTypeSelect')?.value,
          sample_name: $android('sampleSubstanceInput')?.value,
          sample_concentration_M: $android('sampleConcentrationInput')?.value,
          sample_volume_ml: $android('sampleVolumeInput')?.value,
          titrant_name: $android('standardSolutionNameInput')?.value,
          titrant_concentration_M: $android('standardConcentrationInput')?.value,
          theoretical_equivalence_volume_ml: $android('theoryEquivalenceInput')?.value,
          pump_rate_ml_per_s: $android('pumpRateInput')?.value,
        };
    const config = {
      ...payload,
      titration_type: requireAndroidNonBlank(payload.titration_type, '적정 종류'),
      sample_name: requireAndroidNonBlank(payload.sample_name, '시료 물질'),
      sample_concentration_M: requireAndroidPositiveNumber(payload.sample_concentration_M, '시료 농도'),
      sample_volume_ml: requireAndroidPositiveNumber(payload.sample_volume_ml, '시료 부피'),
      sample_valence: requireAndroidPositiveNumber(payload.sample_valence ?? 1, '시료 반응가수'),
      titrant_name: requireAndroidNonBlank(payload.titrant_name, '표준용액 이름'),
      titrant_concentration_M: requireAndroidPositiveNumber(payload.titrant_concentration_M, '표준용액 농도'),
      titrant_valence: requireAndroidPositiveNumber(payload.titrant_valence ?? 1, '표준용액 반응가수'),
      theoretical_equivalence_volume_ml: requireAndroidPositiveNumber(payload.theoretical_equivalence_volume_ml, '이론 당량점'),
      pump_rate_ml_per_s: requireAndroidPositiveNumber(payload.pump_rate_ml_per_s, '펌프 유량'),
      equivalence_formula: payload.equivalence_formula || "nMV=n'M'V'",
    };
    if (payload.calculated_theoretical_equivalence_volume_ml !== undefined) {
      config.calculated_theoretical_equivalence_volume_ml = requireAndroidPositiveNumber(
        payload.calculated_theoretical_equivalence_volume_ml,
        '계산 이론 당량점',
      );
    }
    if (payload.sample_concentration_from_theoretical_equivalence_M !== undefined) {
      config.sample_concentration_from_theoretical_equivalence_M = requireAndroidPositiveNumber(
        payload.sample_concentration_from_theoretical_equivalence_M,
        '이론 당량점 기준 시료 농도',
      );
    }
    return config;
  }

  function startAndroidRecordingWithConfig() {
    let config;
    try {
      config = buildAndroidRecordingConfig();
    } catch (error) {
      setAndroidText('previewStatus', `녹화 시작 차단 · ${error.message}`);
      setAndroidText('csvStateLabel', '시작 실패');
      return;
    }
    applyBridgePayload(readBridgeJson('startRecording', JSON.stringify(config)));
  }

  function saveAndroidCsvToDownloads({ auto = false } = {}) {
    setAndroidText('csvStateLabel', auto ? 'CSV 자동 저장 중' : 'CSV 저장 중');
    if (typeof bridge.saveCsvToDownloads !== 'function') {
      setAndroidText('csvStateLabel', 'CSV 저장 미지원 APK');
      setAndroidText('previewStatus', '이 APK에는 Android CSV 저장 브리지가 없습니다.');
      return null;
    }
    const payload = readBridgeJson('saveCsvToDownloads');
    if (!payload || payload.ok === false) {
      showAndroidError('CSV 저장 실패', payload);
      return null;
    }
    applyBridgePayload(payload);
    const saved = payload.csv_export || {};
    const rows = saved.row_count ?? payload.csv?.row_count ?? 0;
    const path = saved.path || saved.display_name || payload.csv?.path || 'Downloads';
    setAndroidText('csvStateLabel', `CSV 저장 완료 · ${rows}행`);
    setAndroidText('csvPathLabel', path);
    setAndroidText('previewStatus', `CSV 저장 완료 · ${path}`);
    return payload;
  }

  function attachAndroidCsvDownloadHandler() {
    ['csvDownloadLink', 'calcCsvDownloadLink'].forEach((id) => {
      const link = $android(id);
      if (!link) return;
      link.href = '#';
      link.download = 'auto-titration-android-run.csv';
      link.addEventListener('click', (event) => {
        event.preventDefault();
        saveAndroidCsvToDownloads({ auto: false });
      });
    });
  }

  function showAndroidError(prefix, payload) {
    const message = payload?.error || payload?.message || 'unknown error';
    setAndroidText('previewStatus', `${prefix} · ${message}`);
    setAndroidText('mobilePairStatus', `오류 · ${message}`);
  }

  function setPreviewFrameAspect(image, width, height) {
    const frame = image?.closest('.camera-frame');
    const numericWidth = Number(width);
    const numericHeight = Number(height);
    if (!frame || !Number.isFinite(numericWidth) || !Number.isFinite(numericHeight) || numericWidth <= 0 || numericHeight <= 0) return;
    frame.style.aspectRatio = `${numericWidth} / ${numericHeight}`;
  }

  function simplifyAndroidRoiControls() {
    const lockButton = $android('roiLockButton');
    if (lockButton) {
      lockButton.hidden = true;
      lockButton.disabled = true;
    }
    const candidateButton = $android('roiCandidateButton');
    if (candidateButton) candidateButton.textContent = 'ROI 후보 요청';
    const setupButton = $android('roiSetupButton');
    if (setupButton) setupButton.textContent = '새 실험';
    setAndroidText('roiSettingsStatus', 'Android ROI 후보 모드 · YOLO 후보 또는 직접 ROI 지정 후 녹화 가능');
  }

  function enableAndroidButtons() {
    [
      'mobilePairButton',
      'mini2RotateButton',
      'roiSetupButton',
      'roiCandidateButton',
      'csvStopButton',
      'pumpBluetoothButton',
      'pumpRightButton',
      'pumpStopButton',
      'pumpResetButton',
    ].forEach((id) => {
      const button = $android(id);
      if (button) button.disabled = false;
    });
    simplifyAndroidRoiControls();
  }

  function applyAndroidVisiblePreview(live) {
    const dataUrl = live?.visible_preview_data_url;
    if (!dataUrl) return;
    const visible = $android('visiblePreview');
    if (!visible) return;
    const frameId = Number(live.visible_preview_frame_id || live.visible_capture_index || live.frame_id || 0);
    if (Number.isFinite(frameId) && frameId > 0 && frameId <= latestAndroidPreviewFrameId) return;
    if (Number.isFinite(frameId) && frameId > 0) latestAndroidPreviewFrameId = frameId;
    visible.src = dataUrl;
    visible.dataset.androidPreview = 'camera_x_image_analysis';
    visible.style.display = 'block';
    setPreviewFrameAspect(
      visible,
      live.visible_preview_width || live.visible_frame_width || visible.naturalWidth,
      live.visible_preview_height || live.visible_frame_height || visible.naturalHeight,
    );
    setAndroidText('visibleState', `CameraX ${live.visible_capture_index || live.frame_id || '-'}`);
    if (!window.AutoTitrationRoiDraftActive && typeof refreshRoiOverlays === 'function') refreshRoiOverlays();
  }

  function applyAndroidThermalPreviewFrame(live) {
    const dataUrl = live?.thermal_preview_data_url;
    if (!dataUrl) return false;
    const thermal = $android('thermalPreview');
    if (!thermal) return false;
    const thermalFrameId = Number(live.thermal_frame_counter || live.thermal_preview_frame_id || 0);
    if (Number.isFinite(thermalFrameId) && thermalFrameId > 0 && thermalFrameId <= latestAndroidThermalFrameId) return false;
    if (Number.isFinite(thermalFrameId) && thermalFrameId > 0) latestAndroidThermalFrameId = thermalFrameId;
    const frameWidth = Number(live.thermal_frame_width || live.thermal_preview_width || thermal.naturalWidth || 0);
    const frameHeight = Number(live.thermal_frame_height || live.thermal_preview_height || thermal.naturalHeight || 0);
    thermal.onload = () => {
      setPreviewFrameAspect(thermal, thermal.naturalWidth || frameWidth, thermal.naturalHeight || frameHeight);
      if (!window.AutoTitrationRoiDraftActive && typeof refreshRoiOverlays === 'function') refreshRoiOverlays();
    };
    thermal.src = dataUrl;
    thermal.dataset.previewRotationDegrees = String(live?.thermal_preview_rotation_degrees ?? '');
    delete thermal.dataset.placeholder;
    thermal.style.display = 'block';
    setPreviewFrameAspect(thermal, frameWidth, frameHeight);
    if (!window.AutoTitrationRoiDraftActive && typeof refreshRoiOverlays === 'function') refreshRoiOverlays();
    return true;
  }

  function applyCrashReport(crash) {
    const link = $android('crashDownloadLink');
    if (!link) return;
    if (crash?.present && crash.text) {
      link.hidden = false;
      link.href = `data:text/plain;charset=utf-8,${encodeURIComponent(crash.text)}`;
      link.textContent = '크래시 로그 저장';
      setAndroidText('roiSettingsStatus', '이전 앱 크래시 로그 있음');
      return;
    }
    link.hidden = true;
    link.href = '#';
  }

  function showAndroidThermalPlaceholder(mini2, live) {
    const thermal = $android('thermalPreview');
    if (!thermal) return;
    if (live?.thermal_preview_data_url) {
      delete thermal.dataset.placeholder;
      return;
    }
    thermal.dataset.placeholder = 'true';
    if (typeof hideRoiOverlay === 'function') hideRoiOverlay('thermalRoiOverlay');
    const rawStatus = mini2?.raw_frame_status || live?.raw_frame_status || 'blocked_no_stream_entrypoint';
    const backend = mini2?.mini2_selected_backend || live?.mini2_selected_backend || '-';
    const route = mini2?.mini2_route_reason || live?.mini2_device_route || '';
    const stage = mini2?.raw_stream?.stage_report || live?.mini2_stage_report || '';
    const reason = mini2?.raw_stream?.reason || mini2?.mini2_reason || live?.mini2_reason || 'Mini2 stream waiting';
    const detail = [backend, route, stage].filter(Boolean).join(' · ');
    const headline = rawStatus === 'raw_streaming_unverified' ? 'Mini2 프레임 수신 중' : 'Mini2 연결 재시도 중';
    const friendlyStatus = rawStatus === 'raw_streaming_unverified'
      ? 'USB_FRAME_INFO 수신됨 · 온도 변환 검증 대기'
      : 'USB 권한/케이블/스트림을 계속 확인 중';
    const reasonSvg = splitSvgLines(friendlyStatus, 54, 2).map((line, index) =>
      `<text x="320" y="${300 + index * 24}" text-anchor="middle" fill="#cbd5e1" font-size="17" font-family="sans-serif">${escapeSvgText(line)}</text>`
    ).join('');
    const detailSvg = splitSvgLines('상세 진단은 아래 Mini2 진단에 표시됩니다', 48, 1).map((line, index) =>
      `<text x="320" y="${370 + index * 20}" text-anchor="middle" fill="#93c5fd" font-size="15" font-family="sans-serif">${escapeSvgText(line)}</text>`
    ).join('');
    const svg = `
      <svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
        <defs>
          <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
            <stop offset="0" stop-color="#111827"/>
            <stop offset="1" stop-color="#312e81"/>
          </linearGradient>
        </defs>
        <rect width="640" height="480" fill="url(#bg)"/>
        <rect x="48" y="68" width="544" height="344" rx="28" fill="rgba(15,23,42,.78)" stroke="#64748b" stroke-width="3"/>
        <text x="320" y="148" text-anchor="middle" fill="#f8fafc" font-size="34" font-family="sans-serif" font-weight="700">적외선 화면 대기</text>
        <text x="320" y="205" text-anchor="middle" fill="#cbd5e1" font-size="24" font-family="sans-serif">${escapeSvgText(headline)}</text>
        <text x="320" y="248" text-anchor="middle" fill="#fbbf24" font-size="18" font-family="sans-serif">권한 확인 후 수동 Mini2 USB 확인 필요</text>
        ${reasonSvg}
        ${detailSvg}
      </svg>`;
    thermal.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
    thermal.style.display = 'block';
    setAndroidText('thermalState', headline);
    setAndroidText('mini2DebugLabel', [reason, detail].filter(Boolean).join(' · ') || '-');
    updateMini2DiagnosticExport({ mini2, live });
  }

  function sendAndroidVisibleRoi(rect) {
    const payload = {
      normalized: true,
      x: Math.max(0, Math.min(1, rect.x)),
      y: Math.max(0, Math.min(1, rect.y)),
      width: Math.max(0.001, Math.min(1, rect.width)),
      height: Math.max(0.001, Math.min(1, rect.height)),
      source: 'android_webview_visible_preview',
    };
    const response = JSON.parse(bridge.setVisibleRoi(JSON.stringify(payload)));
    applyBridgePayload(response);
    return response;
  }

  function normalizeImageRect(image, rect) {
    const naturalWidth = image.naturalWidth || image.clientWidth || 1;
    const naturalHeight = image.naturalHeight || image.clientHeight || 1;
    return {
      x: rect.x / naturalWidth,
      y: rect.y / naturalHeight,
      width: rect.width / naturalWidth,
      height: rect.height / naturalHeight,
    };
  }

  function addAndroidVisibleRoiHandler() {
    const image = $android('visiblePreview');
    if (!image || typeof imagePointFromEvent !== 'function' || typeof rectFromPoints !== 'function') return;
    const hitElement = image.closest('.camera-frame') || image;
    let drag = null;
    hitElement.addEventListener('pointerdown', (event) => {
      if (latestLiveMetadata?.roi_state === 'recording' || latestRoiLocked) {
        setAndroidText('previewStatus', '녹화 중이거나 ROI 잠금 상태입니다');
        return;
      }
      const start = imagePointFromEvent(image, event);
      if (!start) return;
      event.preventDefault();
      hitElement.setPointerCapture?.(event.pointerId);
      window.AutoTitrationRoiDraftActive = true;
      drag = { start, current: start };
      if (typeof updateRoiOverlay === 'function') {
        updateRoiOverlay('visiblePreview', 'visibleRoiOverlay', { ...start, width: 1, height: 1 }, { draft: true });
      }
    });
    hitElement.addEventListener('pointermove', (event) => {
      if (!drag) return;
      const current = imagePointFromEvent(image, event);
      if (!current) return;
      drag.current = current;
      if (typeof updateRoiOverlay === 'function') {
        updateRoiOverlay('visiblePreview', 'visibleRoiOverlay', rectFromPoints(drag.start, current), { draft: true });
      }
    });
    hitElement.addEventListener('pointerup', (event) => {
      if (!drag) return;
      const end = imagePointFromEvent(image, event) || drag.current;
      const rect = rectFromPoints(drag.start, end);
      drag = null;
      hitElement.releasePointerCapture?.(event.pointerId);
      const naturalWidth = image.naturalWidth || image.clientWidth || 1;
      const naturalHeight = image.naturalHeight || image.clientHeight || 1;
      try {
        if (rect.width < 3 && rect.height < 3) {
          const size = 0.22;
          sendAndroidVisibleRoi({
            x: (end.x / naturalWidth) - size / 2,
            y: (end.y / naturalHeight) - size / 2,
            width: size,
            height: size,
          });
        } else if (rect.width >= 3 && rect.height >= 3) {
          sendAndroidVisibleRoi(normalizeImageRect(image, rect));
        } else {
          setAndroidText('previewStatus', 'ROI가 너무 얇습니다. 다시 드래그하세요');
        }
      } finally {
        window.AutoTitrationRoiDraftActive = false;
        if (typeof refreshRoiOverlays === 'function') refreshRoiOverlays();
      }
    });
    hitElement.addEventListener('pointercancel', () => {
      drag = null;
      window.AutoTitrationRoiDraftActive = false;
      if (typeof refreshRoiOverlays === 'function') refreshRoiOverlays();
    });
  }

  function maybePromptManualMini2Probe(payload) {
    const mini2 = payload?.mini2 || {};
    const raw = mini2.raw_stream_status || payload?.live?.raw_stream_status || '';
    const reason = [
      mini2.raw_stream?.reason,
      mini2.mini2_reason,
      payload?.live?.mini2_reason,
    ].filter(Boolean).join(' · ');
    const isPassiveOfficialGate = reason.includes('passive status polling')
      || reason.includes('official HCUSBSDK/JNI stream is not started');
    const hasUsbPermission = mini2?.mini2_usb_permission === true;
    if (
      mini2ManualProbePromptShown ||
      !hasUsbPermission ||
      raw !== 'blocked_native_stream' ||
      !isPassiveOfficialGate
    ) {
      return;
    }
    mini2ManualProbePromptShown = true;
    setAndroidText('mobilePairStatus', 'Mini2 USB 권한 확인됨 · 수동 확인 필요');
    setAndroidText('previewStatus', 'Mini2 native stream은 크래시 위험 때문에 자동 실행하지 않습니다. Mini2 USB 확인을 직접 누르세요.');
  }

  window.AutoTitrationShouldIgnoreRoiStatus = (data = {}) => {
    const rawRevision = data.visible_roi_revision ?? data.roi_revision;
    const revision = Number(rawRevision ?? 0);
    if (!Number.isFinite(revision)) return false;
    if (revision < latestAndroidRoiRevision) return true;
    latestAndroidRoiRevision = Math.max(latestAndroidRoiRevision, revision);
    return false;
  };

  function showAndroidAutoRoiCandidateResult(payload) {
    const reason = payload?.reason || payload?.roi?.auto_roi_result_reason || 'unknown';
    const target = payload?.target || payload?.roi?.pending_auto_candidate_target || 'both';
    const applied = Boolean(payload?.applied_now);
    const confidence = payload?.confidence;
    const maskSource = payload?.roi?.visible_mask_source || payload?.roi?.thermal_mask_source || '';
    const label = applied ? '적용' : '대기/실패';
    setAndroidText('roiSettingsStatus', `${ANDROID_LABEL}: ROI 후보 요청 ${label} · ${target} · ${reason}${maskSource ? ` · ${maskSource}` : ''}${confidence ? ` · conf ${Number(confidence).toFixed(3)}` : ''}`);
    if (applied && payload?.roi && typeof applyRoiStatus === 'function') applyRoiStatus(payload.roi);
  }

  function applyBridgePayload(payload) {
    if (!payload || payload.ok === false) {
      showAndroidError('Android bridge 실패', payload);
      return;
    }
    try {
      if (payload.live) applyAndroidVisiblePreview(payload.live);
      applyCrashReport(payload.last_crash_report || payload.crash);
      if (payload.live?.thermal_preview_data_url) applyAndroidThermalPreviewFrame(payload.live);
      showAndroidThermalPlaceholder(payload.mini2 || {}, payload.live || {});
      if (typeof applyMobileStatus === 'function') applyMobileStatus(payload);
      const candidateResponse = Object.prototype.hasOwnProperty.call(payload, 'applied_now');
      if (payload.roi && typeof applyRoiStatus === 'function' && (!candidateResponse || payload.applied_now === true)) applyRoiStatus(payload.roi);
      if (payload.live && typeof applyLiveMetadata === 'function') applyLiveMetadata(payload.live);
      if (payload.csv && typeof applyCsvStatus === 'function') applyCsvStatus(payload.csv);
      const pump = payload.pump || {};
      const pumpVolume = pump.pump_firmware_volume_ml ?? payload.live?.pump_firmware_volume_ml ?? payload.csv?.pump_firmware_volume_ml;
      if (pumpVolume !== undefined && pumpVolume !== null && pumpVolume !== '') {
        setAndroidText('pumpVolumeValue', `${Number(pumpVolume).toFixed(4)} mL`);
      }
      if (pump.pump_last_status) {
        setAndroidText('roiSettingsStatus', `펌프 ${pump.pump_state || '-'} · ${pump.pump_last_status}`);
      }
    } catch (error) {
      setAndroidText('previewStatus', `Android UI 적용 오류 · ${error.message}`);
    }

    const mini2 = payload.mini2 || {};
    const status = mini2.mini2_status || payload.live?.thermal_status || '-';
    const reason = mini2.mini2_reason || payload.message || 'Android native bridge active';
    setAndroidText('mobileSourceValue', ANDROID_LABEL);
    setAndroidText('mobilePairStatus', `네이티브 · ${status}`);
    setAndroidText('mobileRoiStatus', payload.roi?.visible_roi || payload.live?.sync_quality || '-');
    setAndroidText('statusLabel', status);
    const route = mini2.mini2_official_module_type || payload.live?.mini2_official_module_type || '-';
    const raw = mini2.raw_stream_status || payload.live?.raw_stream_status || status;
    const rawLabel = raw === 'blocked_native_stream' ? '연결 재시도' : raw;
    const previewReason = raw === 'blocked_native_stream'
      ? 'Mini2 스트림 확인 중 · 상세 진단은 Mini2 진단'
      : reason;
    const rotation = payload.live?.thermal_preview_rotation_degrees ?? mini2.raw_stream?.preview_rotation_degrees ?? payload.thermal_preview_rotation_degrees;
    setAndroidText('previewStatus', `${ANDROID_LABEL} · Mini2 ${route}/${rawLabel} · ${previewReason}`);
    if (rotation !== undefined && rotation !== null && rotation !== '') {
      setAndroidText('thermalState', `Mini2 프레임 · 회전 ${rotation}°`);
    }
    setAndroidText('mini2DebugLabel', [
      mini2.raw_stream?.reason,
      reason,
      mini2.raw_stream?.stage_report,
      payload.live?.mini2_stage_report,
      mini2.mini2_selected_backend,
      mini2.mini2_route_reason,
    ].filter(Boolean).join(' · ') || '-');
    updateMini2DiagnosticExport(payload);
    maybePromptManualMini2Probe(payload);
    if (mini2.raw_frame_status) {
      const thermalUnit = mini2.raw_frame_status === 'raw_unverified' || mini2.raw_frame_status === 'raw_streaming_unverified'
        ? 'raw'
        : (mini2.raw_frame_status === 'blocked_native_stream' ? 'Mini2 대기' : mini2.raw_frame_status);
      setAndroidText('temperatureUnit', thermalUnit);
    }
    enableAndroidButtons();
    simplifyAndroidRoiControls();
  }

  function replaceButtonHandler(id, label, handler) {
    const oldButton = $android(id);
    if (!oldButton) return null;
    const button = oldButton.cloneNode(true);
    if (label) {
      const labelSlot = button.querySelector?.('[data-rotate-label]');
      if (labelSlot) {
        labelSlot.textContent = label;
        button.setAttribute('aria-label', label);
        button.title = label;
      } else {
        button.textContent = label;
      }
    }
    oldButton.replaceWith(button);
    button.addEventListener('pointerdown', (event) => {
      event.stopPropagation();
    });
    button.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      button.disabled = true;
      try {
        await handler(button);
      } finally {
        button.disabled = false;
        enableAndroidButtons();
      }
    });
    return button;
  }

  function pollAndroidStatus() {
    applyBridgePayload(readBridgeJson('getStatusJson'));
  }

  window.AutoTitrationAndroidOnPreview = (live) => {
    if (typeof live === 'string') {
      try {
        const parsed = JSON.parse(live);
        applyAndroidVisiblePreview(parsed);
        applyAndroidThermalPreviewFrame(parsed);
      } catch (error) {
        showAndroidError('Android preview parse 실패', { error: error.message });
      }
      return;
    }
    applyAndroidVisiblePreview(live);
    applyAndroidThermalPreviewFrame(live);
  };

  window.AutoTitrationAndroidOnStatus = (payload) => {
    if (typeof payload === 'string') {
      try {
        applyBridgePayload(JSON.parse(payload));
      } catch (error) {
        showAndroidError('Android status parse 실패', { error: error.message });
      }
      return;
    }
    applyBridgePayload(payload);
  };

  replaceButtonHandler('mobilePairButton', '적외선 USB 확인', () => {
    runManualMini2Probe('button');
  });

  replaceButtonHandler('mini2CopyDiagnosticButton', '진단 복사', async () => {
    let text = $android('mini2FullDiagnosticText')?.value || updateMini2DiagnosticExport(readBridgeJson('getStatusJson'));
    if (shouldRunMini2ProbeBeforeDiagnosticCopy(latestMini2DiagnosticExport)) {
      runManualMini2Probe('diagnostic_copy');
      text = $android('mini2FullDiagnosticText')?.value || updateMini2DiagnosticExport(readBridgeJson('getStatusJson'));
    }
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      setAndroidText('mobilePairStatus', '적외선 진단 JSON 복사됨');
    } else {
      setAndroidText('mobilePairStatus', '적외선 진단 JSON 생성됨');
    }
  });
  replaceButtonHandler('mini2RotateButton', '적외선 회전', () => {
    setAndroidText('previewStatus', '적외선 회전 적용 중');
    if (typeof bridge.rotateThermalPreview === 'function') {
      applyBridgePayload(readBridgeJson('rotateThermalPreview'));
      return;
    }
    setAndroidText('previewStatus', '적외선 회전 미지원 APK입니다');
  });
  replaceButtonHandler('roiSetupButton', 'ROI 자동추적', () => {
    applyBridgePayload(readBridgeJson('startNewRun'));
    setAndroidText('roiSettingsStatus', 'Android WebView: ROI 자동추적 · YOLO/mask 후보 확인 중');
    if (typeof bridge.requestAutoRoiCandidate === 'function') {
      const payload = readBridgeJson('requestAutoRoiCandidate', JSON.stringify({ target: 'both' }));
      showAndroidAutoRoiCandidateResult(payload);
      applyBridgePayload(payload);
      return;
    }
    setAndroidText('roiSettingsStatus', 'Android WebView: requestAutoRoiCandidate 미지원 APK');
  });
  replaceButtonHandler('roiCandidateButton', 'ROI 후보 요청', () => {
    setAndroidText('roiSettingsStatus', 'Android WebView: ROI 후보 요청 · YOLO/mask 후보 확인 중');
    if (typeof bridge.requestAutoRoiCandidate === 'function') {
      const payload = readBridgeJson('requestAutoRoiCandidate', JSON.stringify({ target: 'both' }));
      showAndroidAutoRoiCandidateResult(payload);
      applyBridgePayload(payload);
      return;
    }
    setAndroidText('roiSettingsStatus', 'Android WebView: requestAutoRoiCandidate 미지원 APK');
  });
  replaceButtonHandler('roiLockButton', 'ROI 잠금', () => {
    applyBridgePayload(readBridgeJson('lockRoi'));
  });
  replaceButtonHandler('csvStartButton', '녹화+펌프 시작', () => {
    startAndroidRecordingWithConfig();
  });
  replaceButtonHandler('csvStopButton', '녹화+펌프 정지', () => {
    applyBridgePayload(readBridgeJson('stopRecording'));
    saveAndroidCsvToDownloads({ auto: true });
  });
  replaceButtonHandler('pumpBluetoothButton', '펌프 BT 상태', () => {
    setAndroidText('previewStatus', '펌프 Bluetooth 상태 확인 중');
    applyBridgePayload(readBridgeJson('pumpStatus'));
  });
  replaceButtonHandler('pumpRightButton', '펌프 시작(b)', () => {
    setAndroidText('previewStatus', '펌프 b 명령 전송 중');
    applyBridgePayload(readBridgeJson('sendPumpCommand', 'b'));
  });
  replaceButtonHandler('pumpStopButton', '펌프 정지(c)', () => {
    setAndroidText('previewStatus', '펌프 c 명령 전송 중');
    applyBridgePayload(readBridgeJson('sendPumpCommand', 'c'));
  });
  replaceButtonHandler('pumpResetButton', '카운터 리셋(r)', () => {
    setAndroidText('previewStatus', '펌프 r 명령 전송 중');
    applyBridgePayload(readBridgeJson('sendPumpCommand', 'r'));
  });

  addAndroidVisibleRoiHandler();
  attachAndroidCsvDownloadHandler();
  simplifyAndroidRoiControls();
  const crashLink = $android('crashDownloadLink');
  if (crashLink) {
    crashLink.addEventListener('click', () => {
      applyCrashReport(readBridgeJson('getCrashReport'));
    });
  }
  window.setInterval(pollAndroidStatus, 1000);
  pollAndroidStatus();
})();
