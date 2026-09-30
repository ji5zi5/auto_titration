(function demoViewModule(root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.AutoTitrationDemoView = api;
}(typeof globalThis !== 'undefined' ? globalThis : this, function createDemoViewApi() {
  'use strict';

  const DEFAULT_MAX_SAMPLES = 1500; // About one minute at 25 samples per second.
  const STAGES = {
    fast: { key: 'fast', label: '빠른 주입' },
    continuous: { key: 'fast', label: '빠른 주입' },
    fast_continuous: { key: 'fast', label: '빠른 주입' },
    slow_continuous: { key: 'slow_continuous', label: '저속 연속 주입' },
    pulse_injecting: { key: 'pulse_injecting', label: '미세 주입' },
    pulse_settling: { key: 'pulse_settling', label: '혼합 대기' },
    step_pulse: { key: 'pulse_injecting', label: '미세 주입' },
    stopped: { key: 'stopped', label: '주입 정지' },
    stop: { key: 'stopped', label: '주입 정지' },
    retract: { key: 'retract', label: '되감기' },
    finalizing: { key: 'finalizing', label: '결과 분석' },
    error: { key: 'error', label: '오류 정지' },
  };

  function finite(value) {
    if (value === null || value === undefined || (typeof value === 'string' && !value.trim())) return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  }

  function isFailClosedReason(reason) {
    const value = String(reason || '').trim();
    return [
      'required_sensor_missing',
      'required_color_missing',
      'pulse_control_failed',
      'pump_stop_failed',
      'stop_action_failed',
      'stop_command_failed',
      'guard_arm_or_start_failed',
      'host_monotonic_clock_failed',
      'color_detector_failed',
      'model_score_failed',
    ].includes(value) || /(?:^|_)(?:error|failed|failure|missing)(?:_|$)/.test(value);
  }

  function sessionKey(data) {
    const id = data?.session_id ?? data?.csv_session_id;
    const started = data?.started_epoch_s ?? data?.csv_recording_started_epoch_s ?? data?.csv_started_epoch_s;
    if (id === null || id === undefined || String(id).trim() === '') return '';
    return `${String(id)}\n${started === null || started === undefined ? '' : String(started)}`;
  }

  function observedStage(data = {}) {
    if (data.csv_finalizing || data.finalizing || data.csv_state === 'finalizing' || data.state === 'finalizing') {
      return STAGES.finalizing;
    }
    const stopReason = String(data.auto_stop_reason || '');
    if (data.auto_stop_state === 'error' || isFailClosedReason(stopReason)) return STAGES.error;
    if (data.pump_state === 'retract') return STAGES.retract;
    if (data.pump_state === 'stop') return STAGES.stopped;
    if (data.csv_state === 'stopped' || data.state === 'stopped' || data.pump_state === 'stopped') return STAGES.stopped;
    const pulse = String(data.auto_stop_pulse_state || '').trim();
    if (['slow_continuous', 'pulse_injecting', 'pulse_settling', 'stopped'].includes(pulse)) return STAGES[pulse];
    const pumpState = String(data.pump_state || '').trim();
    if (STAGES[pumpState]) return STAGES[pumpState];
    const direct = String(data.pump_dosing_stage || '').trim();
    if (STAGES[direct]) return STAGES[direct];
    return null;
  }

  function createState(maxSamples = DEFAULT_MAX_SAMPLES) {
    return {
      maxSamples: Math.max(10, Math.floor(finite(maxSamples) || DEFAULT_MAX_SAMPLES)),
      sessionKey: '',
      sessionId: '',
      sessionStarted: null,
      samples: [],
      markers: [],
      stage: null,
      connection: 'connecting',
      csv: null,
      result: { outcome: 'waiting', label: '실험 대기', volumeMl: null, predictedVolumeMl: null, concentrationM: null, csvLabel: 'CSV 대기' },
    };
  }

  function resetState(state) {
    const fresh = createState(state?.maxSamples);
    Object.keys(state || {}).forEach((key) => { delete state[key]; });
    Object.assign(state, fresh);
    return state;
  }

  function resetForSession(state, data) {
    state.sessionKey = sessionKey(data);
    state.sessionId = String(data?.session_id ?? data?.csv_session_id ?? '');
    state.sessionStarted = finite(data?.started_epoch_s ?? data?.csv_recording_started_epoch_s ?? data?.csv_started_epoch_s);
    state.samples.length = 0;
    state.markers.length = 0;
    state.stage = null;
    state.result = { outcome: 'running', label: '측정 중', volumeMl: null, predictedVolumeMl: null, concentrationM: null, csvLabel: 'CSV 기록 중' };
  }

  function recordStage(state, stage, x) {
    if (!stage || stage.key === state.stage?.key) return false;
    state.stage = stage;
    if (x !== null) state.markers.push({ x, key: stage.key, label: stage.label });
    if (state.markers.length > state.maxSamples) state.markers.splice(0, state.markers.length - state.maxSamples);
    return true;
  }

  function resultFrom(csv = {}) {
    const recording = Boolean(csv.recording || csv.state === 'recording');
    const finalizing = Boolean(csv.finalizing || csv.state === 'finalizing');
    const predictionAvailable = !csv.predicted_equivalence_status || csv.predicted_equivalence_status === 'available';
    const terminal = csv.state === 'stopped';
    const reason = String(csv.auto_stop_reason || '');
    const autoTriggered = csv.auto_stop_state === 'triggered';
    let outcome = 'waiting';
    let label = '실험 대기';
    if (recording) [outcome, label] = ['running', '측정 중'];
    else if (finalizing) [outcome, label] = ['finalizing', '결과 분석 중'];
    else if (terminal && autoTriggered && reason === 'persistent_color_change') [outcome, label] = ['complete', '종말점 감지 완료'];
    else if (terminal && autoTriggered && reason.includes('maximum_volume')) [outcome, label] = ['safety-stop', '최대량 안전 정지'];
    else if (terminal && autoTriggered && reason === 'emergency_stop') [outcome, label] = ['safety-stop', '비상 정지'];
    else if (terminal && (csv.auto_stop_state === 'error' || isFailClosedReason(reason))) [outcome, label] = ['error', '오류로 종료'];
    else if (terminal && autoTriggered) [outcome, label] = ['safety-stop', '자동 정지'];
    else if (terminal) [outcome, label] = ['manual-stop', '수동 종료'];

    const volume = terminal ? finite(csv.injected_volume_ml) : null;
    const concentration = terminal && predictionAvailable
      ? finite(csv.sample_concentration_from_predicted_equivalence_M)
      : null;
    const predictedVolume = terminal && predictionAvailable
      ? finite(csv.predicted_equivalence_volume_ml)
      : null;
    const csvLabel = recording
      ? 'CSV 기록 중'
      : finalizing
        ? 'CSV 분석 마무리'
        : terminal
          ? '다운로드 가능'
          : 'CSV 대기';
    return { outcome, label, volumeMl: volume, predictedVolumeMl: predictedVolume, concentrationM: concentration, csvLabel };
  }

  function applyCsvStatus(state, csv = {}) {
    const incomingKey = sessionKey(csv);
    const recording = Boolean(csv.recording || csv.state === 'recording');
    if (incomingKey && incomingKey !== state.sessionKey) {
      const incomingStarted = finite(csv.started_epoch_s ?? csv.csv_recording_started_epoch_s ?? csv.csv_started_epoch_s);
      if (state.sessionKey && incomingStarted !== null && state.sessionStarted !== null && incomingStarted < state.sessionStarted) return false;
      if (!recording && state.sessionKey && incomingStarted === null) return false;
      resetForSession(state, csv);
    }
    state.csv = { ...csv };
    const stage = observedStage(csv);
    const markerX = finite(csv.recording_elapsed_s ?? csv.pump_elapsed_s)
      ?? state.samples[state.samples.length - 1]?.x
      ?? null;
    recordStage(state, stage, markerX);
    state.result = resultFrom(csv);
    return true;
  }

  function appendSample(state, live = {}, trustedThermal = false) {
    const incomingKey = sessionKey(live);
    if (!state.sessionKey || !incomingKey || incomingKey !== state.sessionKey) return false;
    if (!(live.csv_recording || live.csv_state === 'recording')) return false;

    const elapsed = finite(live.csv_recording_elapsed_s ?? live.recording_elapsed_s ?? live.pump_elapsed_s);
    const x = elapsed;
    if (x === null) return false;
    const stage = observedStage(live);
    recordStage(state, stage, x);
    state.samples.push({
      x,
      color: finite(live.visible_color_delta),
      thermalC: trustedThermal ? finite(live.temperature_avg_c) : null,
    });
    if (state.samples.length > state.maxSamples) state.samples.splice(0, state.samples.length - state.maxSamples);
    return true;
  }

  return { DEFAULT_MAX_SAMPLES, createState, resetState, sessionKey, observedStage, resultFrom, applyCsvStatus, appendSample };
}));
