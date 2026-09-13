(() => {
  const bridge = window.AutoTitrationAndroid;
  if (!bridge) return;

  const $android = (id) => document.getElementById(id);
  const ANDROID_LABEL = 'Android WebView';
  const MAX_VISIBLE_MINI2_DIAGNOSTIC_CHARS = 420;
  const MINI2_OFFICIAL_PRIMARY_MODE = 'OFFICIAL_PRIMARY';
  const MINI2_MANUAL_PROBE_MIN_INTERVAL_MS = 10000;
  const ANDROID_AUTO_STOP_UNSUPPORTED_MESSAGE = '자동 정지·미세 주입은 Windows 수집기에서만 지원';
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


  function isAndroidPlainObject(value) {
    return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
  }

  function firstAndroidValue(...values) {
    for (const value of values) {
      if (value !== undefined && value !== null && value !== '') return value;
    }
    return '';
  }

  function androidHasFiniteNumber(value) {
    return typeof value === 'number' && Number.isFinite(value);
  }

  function androidFiniteNumberOrNull(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }

  function androidSafeFrameCounterOrNull(value) {
    return Number.isSafeInteger(value) && value >= 0 ? value : null;
  }

  function androidOfficialTemperatureSummaryFrom(source = {}, sourceFrameCounter) {
    if (!isAndroidPlainObject(source)) return null;
    const status = firstAndroidValue(source.official_measurement_status);
    const provenance = firstAndroidValue(source.official_temperature_provenance);
    const scope = firstAndroidValue(source.official_temperature_scope);
    const fullMatrixAllowed = firstAndroidValue(source.official_full_matrix_celsius_allowed);
    const avg = androidFiniteNumberOrNull(source.official_temperature_avg_c);
    const min = androidFiniteNumberOrNull(source.official_temperature_min_c);
    const max = androidFiniteNumberOrNull(source.official_temperature_max_c);
    const center = androidFiniteNumberOrNull(source.official_temperature_center_c);
    const sourceCounter = androidSafeFrameCounterOrNull(sourceFrameCounter);
    const measurementCounter = androidSafeFrameCounterOrNull(source.official_measurement_frame_counter);
    if (
      status !== 'READY' ||
      provenance !== 'official_f2_analyzer_measurement_stats' ||
      !['fullscreen', 'rectangle'].includes(scope) ||
      fullMatrixAllowed !== false ||
      avg === null ||
      min === null ||
      max === null ||
      min > avg ||
      avg > max ||
      (center !== null && (center < min || center > max)) ||
      sourceCounter === null ||
      measurementCounter === null ||
      measurementCounter > sourceCounter
    ) {
      return null;
    }

    const computedAgeFrames = sourceCounter - measurementCounter;
    const publishedMatchesCurrentFrame = source.official_measurement_matches_current_frame;
    const publishedTemporalScope = firstAndroidValue(source.official_measurement_temporal_scope);
    const publishedAgeFrames = androidSafeFrameCounterOrNull(source.official_measurement_age_frames);
    const isCurrentFrame = computedAgeFrames === 0
      && publishedMatchesCurrentFrame === true
      && publishedTemporalScope === 'current_frame'
      && publishedAgeFrames === 0;
    const isLastCompletedMeasurement = computedAgeFrames > 0
      && publishedMatchesCurrentFrame === false
      && publishedTemporalScope === 'last_completed_measurement'
      && publishedAgeFrames === computedAgeFrames;
    if (!isCurrentFrame && !isLastCompletedMeasurement) return null;

    const officialFields = {
      official_measurement_status: status,
      official_measurement_reason: firstAndroidValue(source.official_measurement_reason),
      official_measurement_frame_counter: measurementCounter,
      official_temperature_avg_c: avg,
      official_temperature_min_c: min,
      official_temperature_max_c: max,
      official_temperature_center_c: center,
      official_temperature_provenance: 'official_f2_analyzer_measurement_stats',
      official_temperature_scope: scope,
      official_measurement_matches_current_frame: isCurrentFrame,
      official_measurement_temporal_scope: isCurrentFrame ? 'current_frame' : 'last_completed_measurement',
      official_measurement_age_frames: computedAgeFrames,
      official_full_matrix_celsius_allowed: false,
    };
    if (!isCurrentFrame) return officialFields;
    return {
      ...officialFields,
      celsius_allowed: true,
      temperature_avg_c: avg,
      temperature_min_c: min,
      temperature_max_c: max,
      temperature_center_c: center,
      temperature_delta_c: max - min,
      temperature_provenance: 'official_f2_analyzer_measurement_stats',
      temperature_scope: scope,
      temperature_source: 'official_f2_analyzer_measurement_stats',
      full_matrix_celsius_allowed: false,
      full_matrix_temperature_status: 'unproved_not_emitted',
    };
  }

  function androidCurrentOfficialTemperatureSummaryFrom(source = {}, sourceFrameCounter) {
    const parsed = androidOfficialTemperatureSummaryFrom(source, sourceFrameCounter);
    if (
      !parsed ||
      parsed.official_measurement_matches_current_frame !== true ||
      parsed.official_measurement_temporal_scope !== 'current_frame' ||
      parsed.official_measurement_age_frames !== 0
    ) {
      return null;
    }
    return parsed;
  }

  function androidTemperatureSummaryFrom(source = {}) {
    if (!isAndroidPlainObject(source)) return null;
    const summary = isAndroidPlainObject(source.temperature_summary) ? source.temperature_summary : source;
    const avg = androidFiniteNumberOrNull(firstAndroidValue(source.temperature_avg_c, summary.avg_c));
    const min = androidFiniteNumberOrNull(firstAndroidValue(source.temperature_min_c, summary.min_c));
    const max = androidFiniteNumberOrNull(firstAndroidValue(source.temperature_max_c, summary.max_c));
    const provenance = firstAndroidValue(source.temperature_provenance, summary.provenance);
    const scope = firstAndroidValue(source.temperature_scope, summary.scope);
    const celsiusAllowed = firstAndroidValue(source.celsius_allowed, summary.celsius_allowed);
    const fullMatrixAllowed = firstAndroidValue(source.full_matrix_celsius_allowed, summary.full_matrix_celsius_allowed);
    if (
      avg === null ||
      min === null ||
      max === null ||
      celsiusAllowed !== true ||
      fullMatrixAllowed === true ||
      provenance !== 'device_global_summary' ||
      scope !== 'device_global_summary' ||
      min > avg ||
      avg > max
    ) {
      return null;
    }
    return {
      celsius_allowed: true,
      temperature_avg_c: avg,
      temperature_min_c: min,
      temperature_max_c: max,
      temperature_delta_c: max - min,
      temperature_provenance: 'device_global_summary',
      temperature_scope: 'device_global_summary',
      temperature_source: 'device_global_summary',
      full_matrix_celsius_allowed: false,
      full_matrix_temperature_status: firstAndroidValue(
        source.full_matrix_temperature_status,
        summary.full_matrix_temperature_status,
        'unproved_not_emitted',
      ),
    };
  }

  function trustedAndroidTemperature(payload = {}) {
    const mini2 = payload.mini2 || {};
    const rawStream = isAndroidPlainObject(mini2.raw_stream) ? mini2.raw_stream : {};
    const live = isAndroidPlainObject(payload.live) ? payload.live : {};
    return androidCurrentOfficialTemperatureSummaryFrom(live, live.thermal_frame_counter)
      || androidCurrentOfficialTemperatureSummaryFrom(rawStream, rawStream.frame_counter);
  }

  function trustedAndroidDeviceGlobalTemperature(payload = {}) {
    return trustedAndroidTemperature(payload);
  }

  function androidRegexValue(text, pattern) {
    const match = String(text || '').match(pattern);
    return match?.[1] || '';
  }

  function androidNestedValue(source, path) {
    return path.reduce((current, key) => (isAndroidPlainObject(current) ? current[key] : undefined), source);
  }

  function hasProvenAndroidRawMatrix(payload = {}) {
    const mini2 = payload.mini2 || {};
    const live = payload.live || {};
    const rawStream = isAndroidPlainObject(mini2.raw_stream) ? mini2.raw_stream : {};
    const status = firstAndroidValue(rawStream.raw_stream_status, mini2.raw_frame_status, live.raw_frame_status, live.raw_stream_status);
    const frameCounter = Number(firstAndroidValue(rawStream.frame_counter, live.thermal_frame_counter, live.thermal_preview_frame_id, 0));
    const width = Number(firstAndroidValue(rawStream.frame_width, live.thermal_frame_width, live.thermal_preview_width, 0));
    const height = Number(firstAndroidValue(rawStream.frame_height, live.thermal_frame_height, live.thermal_preview_height, 0));
    const hasRawStats = androidHasFiniteNumber(rawStream.raw_avg)
      || androidHasFiniteNumber(live.raw_avg)
      || androidHasFiniteNumber(rawStream.raw_min)
      || androidHasFiniteNumber(live.raw_min);
    const explicitRawMatrix = rawStream.raw_matrix_present === true
      || live.raw_matrix_present === true
      || rawStream.raw_matrix_status === 'available'
      || live.raw_matrix_status === 'available';
    return explicitRawMatrix || (
      /raw_streaming_unverified|raw_unverified/i.test(String(status))
      && Number.isFinite(frameCounter) && frameCounter > 0
      && Number.isFinite(width) && width > 0
      && Number.isFinite(height) && height > 0
      && hasRawStats
    );
  }

  function sanitizeAndroidBridgePayload(payload = {}) {
    if (!isAndroidPlainObject(payload)) return payload;
    const clean = { ...payload };
    const live = isAndroidPlainObject(payload.live) ? { ...payload.live } : payload.live;
    const roi = isAndroidPlainObject(payload.roi) ? { ...payload.roi } : payload.roi;
    const rawMatrixReady = hasProvenAndroidRawMatrix(payload);
    const trustedGlobalTemperature = trustedAndroidTemperature(payload);
    if (isAndroidPlainObject(live)) {
      if (!rawMatrixReady) {
        live.thermal_roi_ready = false;
        live.roi_complete = false;
      }
      if (trustedGlobalTemperature) {
        Object.assign(live, trustedGlobalTemperature);
      } else {
        ['avg_c', 'min_c', 'max_c', 'delta_c'].forEach((suffix) => {
          live[`temperature_${suffix}`] = null;
        });
        live.celsius_allowed = false;
      }
      clean.live = live;
    }
    if (isAndroidPlainObject(roi)) {
      if (!rawMatrixReady) {
        roi.thermal_roi_ready = false;
        roi.roi_complete = false;
        if (roi.thermal_roi && !roi.thermal_raw_matrix_proven) delete roi.thermal_roi;
      }
      clean.roi = roi;
    }
    return clean;
  }

  function classifyMini2StageReport(stageReport, reason = '', structuredEvidence = {}) {
    const text = `${stageReport || ''} ${reason || ''}`;
    const nativeStartSucceeded = /USB_StartStreamCallback=ok|startStreamPreview resultCode=1 channel=\d+/i.test(text);
    const dispatchedCallbackCount = Number(structuredEvidence.dispatchedCallbackCount || 0);
    const callbackEntryDetail = String(structuredEvidence.callbackEntryDetail || '');
    const frameCounter = Number(structuredEvidence.frameCounter || 0);
    const postStartState = String(structuredEvidence.postStartState || '');
    const invalidPacketSizeTimeout = structuredEvidence.invalidPacketSizeTimeout;
    if (/USB permission denied|mini2_usb_permission["']?\\s*[:=]\\s*false|permission_state["']?\\s*[:=]\\s*denied/i.test(text)) {
      return 'usb_permission_denied_before_native_stream';
    }
    if (/USB permission requested|USB permission pending|waiting for Android grant/i.test(text)) {
      return 'usb_permission_pending_before_native_stream';
    }
    if (/passive status polling|official HCUSBSDK\/JNI stream is not started/i.test(text)) {
      return 'manual_probe_not_run_passive_status_guard';
    }
    if (nativeStartSucceeded && frameCounter > 0) {
      return 'official_frame_observed';
    }
    if (
      nativeStartSucceeded
      && frameCounter <= 0
      && (
        Boolean(invalidPacketSizeTimeout)
        || postStartState === 'native_start_accepted_callback_invalid_packet_size_timeout'
      )
    ) {
      return 'native_start_accepted_callback_invalid_packet_size_timeout';
    }
    if (
      nativeStartSucceeded
      && frameCounter <= 0
      && dispatchedCallbackCount > 0
      && /(?:^|\s)disposition=dispatched(?:\s|$)/.test(callbackEntryDetail)
    ) {
      return 'callback_packet_observed_official_handoff_missing';
    }
    if (nativeStartSucceeded && /no_callback_entry/i.test(text) && /blocked_native_stream|stalled_without_frame|timed out|no frame callback/i.test(text)) {
      return 'native_start_succeeded_no_java_callback';
    }
    if (nativeStartSucceeded && /no_callback_entry|waiting for (?:first )?(?:USB_FRAME_INFO|Java|JNI)?\s*callback|stream_attempt_started/i.test(text)) {
      return 'native_start_succeeded_waiting_for_java_callback';
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
    const rawStream = isAndroidPlainObject(mini2.raw_stream) ? mini2.raw_stream : {};
    const explicitLastStreamAttempt = isAndroidPlainObject(mini2.last_stream_attempt) ? mini2.last_stream_attempt : {};
    const hasExplicitLastStreamAttempt = Object.keys(explicitLastStreamAttempt).length > 0;
    const hasCurrentRawStream = Object.keys(rawStream).length > 0;
    const diagnosticStream = hasCurrentRawStream ? rawStream : explicitLastStreamAttempt;
    const lastAttempt = hasExplicitLastStreamAttempt ? explicitLastStreamAttempt : diagnosticStream;
    const currentPresence = isAndroidPlainObject(mini2.current_usb_presence) ? mini2.current_usb_presence : {};
    const streamDiagnostics = diagnosticStream.stream_diagnostics || {};
    const stageReport = diagnosticStream.stage_report || diagnosticStream.raw_stage_report || live.mini2_stage_report || '';
    const attempt = diagnosticStream.attempt_diagnostics?.[0]
      || streamDiagnostics.attempt_diagnostics?.[0]
      || {};
    const lastAttemptRoute = lastAttempt.device_route || rawStream.device_route || live.mini2_device_route || '';
    const currentPresenceRoute = currentPresence.device_route || currentPresence.route_reason || mini2.mini2_route_reason || '';
    const route = diagnosticStream.device_route || live.mini2_device_route || lastAttemptRoute || currentPresenceRoute;
    const routeMatch = String(route).match(/(\d+)\s*[:/]\s*(\d+)/);
    const callbackEntryDetail = firstAndroidValue(
      diagnosticStream.java_interface_callback_entry_detail,
      streamDiagnostics.java_interface_callback_entry_detail,
    );
    const classificationReason = [
      diagnosticStream.reason || mini2.mini2_reason || live.mini2_reason,
      callbackEntryDetail,
    ].filter(Boolean).join(' ');
    const callbackEntryCount = Number(firstAndroidValue(
      diagnosticStream.java_interface_dispatched_callback_count,
      streamDiagnostics.java_interface_dispatched_callback_count,
      diagnosticStream.java_interface_callback_entry_count,
      streamDiagnostics.java_interface_callback_entry_count,
      0,
    ));
    const postStartState = firstAndroidValue(
      diagnosticStream.post_start_state,
      diagnosticStream.stream_post_start_state,
      streamDiagnostics.post_start_state,
      streamDiagnostics.stream_post_start_state,
    );
    const frameCounter = Number(firstAndroidValue(
      diagnosticStream.frame_counter,
      live.thermal_frame_counter,
      0,
    ));
    const invalidPacketSizeTimeout = firstAndroidValue(
      diagnosticStream.invalid_packet_size_timeout,
      streamDiagnostics.invalid_packet_size_timeout,
    );
    const diagnosticClassification = classifyMini2StageReport(stageReport, classificationReason, {
      dispatchedCallbackCount: callbackEntryCount,
      callbackEntryDetail,
      postStartState,
      frameCounter,
      invalidPacketSizeTimeout,
    });
    const classification = hasCurrentRawStream
      ? diagnosticClassification
      : (hasExplicitLastStreamAttempt ? 'historical_last_attempt_only' : diagnosticClassification);
    const selectedProfile = firstAndroidValue(
      attempt.profile_class,
      attempt.selected_profile,
      streamDiagnostics.profile_class,
      rawStream.profile_class,
      live.profile_class,
      androidRegexValue(stageReport, /selectedProfile=([^;\s]+)/i),
    );
    const packetClassification = firstAndroidValue(
      diagnosticStream.packet_classification,
      live.packet_classification,
      androidRegexValue(diagnosticStream.reason || live.mini2_reason || stageReport, /packet_classification=([^;\s]+)/i),
    );
    const packetStatus = firstAndroidValue(
      diagnosticStream.packet_status,
      live.packet_status,
      androidRegexValue(diagnosticStream.reason || live.mini2_reason || stageReport, /packet_status=([^;\s]+)/i),
    );
    const converterValidation = {
      celsiusAllowed: firstAndroidValue(live.celsius_allowed, rawStream.celsius_allowed, mini2.celsius_allowed),
      converterProfileStatus: firstAndroidValue(live.converter_profile_status, live.temperature_profile_status, rawStream.converter_profile_status, rawStream.temperature_profile_status, mini2.converter_profile_status),
      celsiusPublishState: firstAndroidValue(live.celsius_publish_state, rawStream.celsius_publish_state, mini2.celsius_publish_state),
      validationEvidence: firstAndroidValue(live.validation_evidence, rawStream.validation_evidence, mini2.validation_evidence, androidNestedValue(rawStream, ['converter_validation', 'validation_evidence'])),
    };
    const summary = {
      classification,
      route,
      lastAttemptRoute,
      currentPresenceRoute,
      vid: mini2.vid || mini2.vendor_id || currentPresence.vid || currentPresence.vendor_id || routeMatch?.[1] || '',
      pid: mini2.pid || mini2.product_id || currentPresence.pid || currentPresence.product_id || routeMatch?.[2] || '',
      fd: attempt.fd ?? diagnosticStream.fd ?? '',
      userId: attempt.userId ?? attempt.user_id ?? diagnosticStream.userId ?? diagnosticStream.user_id ?? '',
      channel: attempt.channel ?? diagnosticStream.channel ?? '',
      startMode: attempt.startMode || attempt.start_mode || '',
      videoFormat: attempt.videoFormat ?? attempt.video_format ?? '',
      callbackStreamType: attempt.callbackStreamType ?? attempt.callback_stream_type ?? '',
      setVideoStatus: attempt.setVideoStatus || attempt.set_video_status || '',
      startStatus: attempt.startStatus || attempt.start_status || diagnosticStream.raw_stream_status || '',
      lastError: attempt.lastError ?? attempt.last_error ?? '',
      selectedProfile,
      packetClassification,
      packetStatus,
      callbackEntryCount,
      postStartState,
      invalidPacketSizeTimeout,
      converterValidation,
      error84_after_video_ok: Boolean(diagnosticStream.error84_after_video_ok || streamDiagnostics.error84_after_video_ok || classification === 'callback_start_failed_error84_after_video_ok'),
      official_wrapper_parity_ok: diagnosticStream.official_wrapper_parity_ok ?? streamDiagnostics.official_wrapper_parity_ok ?? false,
      official_wrapper_parity: diagnosticStream.official_wrapper_parity || streamDiagnostics.official_wrapper_parity || {},
      converterStatus: diagnosticStream.converter_status || streamDiagnostics.converter_status || 'converter_status_secondary_not_raw_stream_blocker',
      rawStageReport: stageReport,
      currentUsbPresence: currentPresence,
      lastStreamAttempt: lastAttempt,
      diagnosticStream,
      diagnosticClassification,
      diagnosticStreamIsCurrent: hasCurrentRawStream,
      hasExplicitLastStreamAttempt,
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

  function ensureAndroidPumpControls() {
    if ($android('androidPumpBluetoothControls')) return;
    const anchor = $android('pumpTimelineForm');
    if (!anchor) return;

    const panel = document.createElement('div');
    panel.id = 'androidPumpBluetoothControls';
    panel.className = 'pump-settings android-pump-settings csv-mode-only';
    panel.setAttribute('aria-label', 'Bluetooth 펌프 연결');
    panel.innerHTML = `
      <label class="android-pump-device-field">
        <span>Bluetooth 펌프</span>
        <select id="pumpDeviceSelect" aria-label="연결할 Bluetooth 펌프">
          <option value="">페어링된 기기 불러오기</option>
        </select>
      </label>
      <button id="pumpRefreshButton" type="button">기기 새로고침</button>
      <button id="pumpConnectButton" type="button">연결</button>
      <button id="pumpDisconnectButton" class="secondary-button" type="button">연결 해제</button>
      <button id="pumpBluetoothSettingsButton" class="secondary-button" type="button">Bluetooth 설정</button>
      <button id="pumpBluetoothButton" class="secondary-button" type="button">상태 확인</button>
      <button id="pumpResetButton" class="secondary-button" type="button">주입량 초기화</button>
      <span id="pumpBluetoothStatus" class="android-pump-status" role="status" aria-live="polite">연결 안 됨</span>
    `;
    anchor.insertAdjacentElement('afterend', panel);
  }

  function populateAndroidPumpDevices(payload = {}) {
    const select = $android('pumpDeviceSelect');
    if (!select) return;
    const pump = payload.pump || {};
    const devices = Array.isArray(payload.pump_devices)
      ? payload.pump_devices
      : (Array.isArray(pump.paired_devices) ? pump.paired_devices : []);
    if (!devices.length) return;

    const selectedAddress = String(
      pump.pump_bluetooth_device_address
      || pump.selected_device_address
      || devices.find((device) => device.selected)?.address
      || select.value
      || '',
    );
    select.replaceChildren();
    devices.forEach((device) => {
      const option = document.createElement('option');
      option.value = String(device.address || '');
      option.textContent = String(device.name || device.address || '이름 없는 Bluetooth 기기');
      option.selected = option.value === selectedAddress;
      select.appendChild(option);
    });
  }

  function updateAndroidPumpControls(payload = {}) {
    populateAndroidPumpDevices(payload);
    const pump = payload.pump || {};
    const connected = pump.pump_connected === true || pump.transport_connected === true;
    const deviceName = pump.pump_bluetooth_device_name || pump.selected_device_name || '';
    const state = pump.pump_state || pump.transport_state || (connected ? 'connected' : 'disconnected');
    const warning = pump.pump_warning || pump.transport_warning || '';
    const statusText = connected
      ? `연결됨${deviceName ? ` · ${deviceName}` : ''}`
      : (warning || `연결 안 됨 · ${state}`);
    setAndroidText('pumpBluetoothStatus', statusText);
    setAndroidText('pumpCommandStatus', connected ? `연결됨 · ${state}` : 'Bluetooth 연결 필요');
    const disconnectButton = $android('pumpDisconnectButton');
    if (disconnectButton) disconnectButton.disabled = !connected;
  }

  function refreshAndroidPumpDevices() {
    if (typeof bridge.pumpDevices !== 'function') {
      setAndroidText('pumpBluetoothStatus', '이 APK는 Bluetooth 기기 선택을 지원하지 않습니다');
      return null;
    }
    const payload = readBridgeJson('pumpDevices');
    applyBridgePayload(payload);
    return payload;
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

  function stripUnsupportedAndroidAutoStopConfig(payload = {}) {
    return Object.fromEntries(
      Object.entries(payload).filter(([key]) => !key.startsWith('auto_stop_')),
    );
  }

  function configureAndroidUnsupportedAutoStop() {
    const input = $android('autoStopEnabledInput');
    if (input) {
      input.checked = false;
      input.disabled = true;
      input.setAttribute?.('aria-describedby', 'autoStopSupportNotice');
      const controlLabel = input.closest?.('label');
      if (controlLabel?.dataset) controlLabel.dataset.androidUnsupported = 'true';
      const optionLabel = controlLabel?.querySelector?.('strong');
      if (optionLabel) optionLabel.textContent = 'Android에서 사용할 수 없음';
      let notice = $android('autoStopSupportNotice');
      if (!notice && controlLabel?.appendChild) {
        notice = document.createElement('small');
        notice.id = 'autoStopSupportNotice';
        controlLabel.appendChild(notice);
      }
      if (notice) notice.textContent = ANDROID_AUTO_STOP_UNSUPPORTED_MESSAGE;
    }
    setAndroidText('autoStopStatus', 'Windows 수집기에서만 지원');
  }

  function buildAndroidRecordingConfig() {
    const sharedPayload = typeof buildPumpTimelineStartPayload === 'function'
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
    const payload = stripUnsupportedAndroidAutoStopConfig(sharedPayload);
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
      'pumpRefreshButton',
      'pumpConnectButton',
      'pumpBluetoothSettingsButton',
      'serialPumpDispenseButton',
      'serialPumpRetractButton',
      'serialPumpStopButton',
    ].forEach((id) => {
      const button = $android(id);
      if (button) button.disabled = false;
    });
    simplifyAndroidRoiControls();
    configureAndroidUnsupportedAutoStop();
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

  window.AutoTitrationAndroidTestHooks = {
    androidOfficialTemperatureSummaryFrom,
    androidSafeFrameCounterOrNull,
    androidCurrentOfficialTemperatureSummaryFrom,
    androidTemperatureSummaryFrom,
    trustedAndroidTemperature,
    trustedAndroidDeviceGlobalTemperature,
    hasProvenAndroidRawMatrix,
    sanitizeAndroidBridgePayload,
    classifyMini2StageReport,
    stripUnsupportedAndroidAutoStopConfig,
    configureAndroidUnsupportedAutoStop,
    buildAndroidRecordingConfig,
  };

  function applyBridgePayload(payload) {
    if (!payload || payload.ok === false) {
      showAndroidError('Android bridge 실패', payload);
      return;
    }
    payload = sanitizeAndroidBridgePayload(payload);
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
      updateAndroidPumpControls(payload);
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

  // Final endpoint inference is off the preview thread and never controls the pump.
  let endpointWorker = null;
  let endpointWorkerUrl = null;
  let nextEndpointJob = 0;
  const endpointJobs = new Map();

  function disposeEndpointWorker(reason) {
    if (endpointWorker) endpointWorker.terminate();
    if (endpointWorkerUrl) URL.revokeObjectURL(endpointWorkerUrl);
    endpointWorker = null;
    endpointWorkerUrl = null;
    for (const job of endpointJobs.values()) { clearTimeout(job.timer); job.reject(new Error(reason)); }
    endpointJobs.clear();
  }

  function ensureEndpointWorker() {
    if (endpointWorker) return endpointWorker;
    if (typeof bridge.endpointWorkerSource !== 'function' || typeof bridge.endpointModelJson !== 'function') {
      throw new Error('이 APK에는 휴대폰 예측 모델이 없습니다');
    }
    const bootstrap = `
      let model = null;
      self.onmessage = event => {
        const message = event.data;
        if (message.kind === 'model') {
          try { model = JSON.parse(message.json); } catch (_) { model = null; }
          return;
        }
        let result;
        try {
          if (!model) throw Error('endpoint_model_unavailable');
          const reason = self.AutoTitrationEndpoint.readiness(message.rows);
          result = reason
            ? { predicted_equivalence_status: 'withheld', predicted_equivalence_reason: reason }
            : self.AutoTitrationEndpoint.predict(model, message.rows, message.titration_type);
        } catch (error) {
          result = { predicted_equivalence_status: /^insufficient_|^no_endpoint/.test(error.message || '') ? 'withheld' : 'unavailable', predicted_equivalence_reason: error.message || String(error) };
        }
        self.postMessage({ id: message.id, result });
      };
    `;
    endpointWorkerUrl = URL.createObjectURL(new Blob([bridge.endpointWorkerSource(), '\n', bootstrap], { type: 'text/javascript' }));
    endpointWorker = new Worker(endpointWorkerUrl);
    endpointWorker.onmessage = event => {
      const job = endpointJobs.get(event.data?.id);
      if (!job) return;
      clearTimeout(job.timer); endpointJobs.delete(event.data.id); job.resolve(event.data.result);
    };
    endpointWorker.onerror = event => disposeEndpointWorker(event.message || '휴대폰 모델 처리 실패');
    endpointWorker.postMessage({ kind: 'model', json: bridge.endpointModelJson() });
    return endpointWorker;
  }

  async function analyzeAndroidRecording() {
    if (typeof bridge.beginEndpointAnalysis !== 'function' || typeof bridge.finishEndpointAnalysis !== 'function') return false;
    const request = readBridgeJson('beginEndpointAnalysis');
    if (!request.ok) { showAndroidError('분석 시작 실패', request); return false; }
    setAndroidText('previewStatus', '당량점·농도 분석 중…');
    let result;
    try {
      const worker = ensureEndpointWorker(), id = ++nextEndpointJob;
      result = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => disposeEndpointWorker('endpoint_analysis_timeout'), 30000);
        endpointJobs.set(id, { resolve, reject, timer });
        try { worker.postMessage({ kind: 'predict', id, rows: request.rows, titration_type: request.titration_type }); }
        catch (error) { clearTimeout(timer); endpointJobs.delete(id); reject(error); }
      });
    } catch (error) {
      result = { predicted_equivalence_status: 'unavailable', predicted_equivalence_reason: error.message || String(error) };
    }
    let response = readBridgeJson('finishEndpointAnalysis', JSON.stringify({ ...result, generation: request.generation, run_id: request.run_id }));
    if (response.ok === false) {
      response = readBridgeJson('finishEndpointAnalysis', JSON.stringify({ generation: request.generation, run_id: request.run_id,
        predicted_equivalence_status: 'unavailable', predicted_equivalence_reason: 'invalid_endpoint_result' }));
    }
    if (response.prediction_result_accepted !== true) return false; // A newer run owns the UI now.
    applyBridgePayload(response);
    return true;
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

  ensureAndroidPumpControls();
  configureAndroidUnsupportedAutoStop();

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
  replaceButtonHandler('csvStopButton', '녹화+펌프 정지', async () => {
    const stopped = readBridgeJson('stopRecording');
    applyBridgePayload(stopped);
    if (stopped.ok === false) return;
    const hasEndpointBridge = typeof bridge.beginEndpointAnalysis === 'function';
    if (!hasEndpointBridge || await analyzeAndroidRecording()) saveAndroidCsvToDownloads({ auto: true });
  });
  replaceButtonHandler('pumpBluetoothButton', '펌프 BT 상태', () => {
    setAndroidText('previewStatus', '펌프 Bluetooth 상태 확인 중');
    applyBridgePayload(readBridgeJson('pumpStatus'));
  });
  replaceButtonHandler('pumpRefreshButton', '기기 새로고침', () => {
    setAndroidText('pumpBluetoothStatus', '페어링된 기기 확인 중');
    refreshAndroidPumpDevices();
  });
  replaceButtonHandler('pumpConnectButton', '연결', () => {
    const address = $android('pumpDeviceSelect')?.value || '';
    if (!address) {
      refreshAndroidPumpDevices();
      setAndroidText('pumpBluetoothStatus', '연결할 기기를 선택하세요');
      return;
    }
    setAndroidText('pumpBluetoothStatus', 'Bluetooth 펌프 연결 중');
    applyBridgePayload(readBridgeJson('connectPump', address));
  });
  replaceButtonHandler('pumpDisconnectButton', '연결 해제', () => {
    setAndroidText('pumpBluetoothStatus', 'Bluetooth 연결 해제 중');
    applyBridgePayload(readBridgeJson('disconnectPump'));
  });
  replaceButtonHandler('pumpBluetoothSettingsButton', 'Bluetooth 설정', () => {
    applyBridgePayload(readBridgeJson('openBluetoothSettings'));
  });
  replaceButtonHandler('serialPumpDispenseButton', '펌프 주입', () => {
    setAndroidText('previewStatus', '펌프 b 명령 전송 중');
    applyBridgePayload(readBridgeJson('sendPumpCommand', 'b'));
  });
  replaceButtonHandler('serialPumpRetractButton', '펌프 되감기', () => {
    setAndroidText('previewStatus', '펌프 a 명령 전송 중');
    applyBridgePayload(readBridgeJson('sendPumpCommand', 'a'));
  });
  replaceButtonHandler('serialPumpStopButton', '펌프 정지', () => {
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
  refreshAndroidPumpDevices();
  const crashLink = $android('crashDownloadLink');
  if (crashLink) {
    crashLink.addEventListener('click', () => {
      applyCrashReport(readBridgeJson('getCrashReport'));
    });
  }
  window.setInterval(pollAndroidStatus, 1000);
  pollAndroidStatus();
})();
