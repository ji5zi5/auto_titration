// Remote mode is browser-only; the Android native bridge keeps its own UI.
const compactViewMode = !window.AutoTitrationAndroid
  && !/[?&]remote=0(?:&|$)/.test(window.location?.search || '')
  && (/[?&]remote=1(?:&|$)/.test(window.location?.search || '')
    || Boolean(window.matchMedia?.('(max-width: 700px)').matches));
// A layout change must never grant a remote browser notebook settings ownership.
const remoteControlMode = !window.AutoTitrationAndroid
  && (/[?&](?:remote|remote_control)=1(?:&|$)/.test(window.location?.search || '')
    || Boolean(window.matchMedia?.('(max-width: 700px)').matches));
if (compactViewMode) document.body.classList.add('remote-control-mode');
if (remoteControlMode) document.body.classList.add('remote-controller-mode');

const $ = (id) => document.getElementById(id);

// Keep both browser views reachable without losing connection/query context.
function updateViewLinks() {
  for (const [id, remote] of [['viewFullLink', '0'], ['viewCompactLink', '1']]) {
    const link = $(id);
    if (!link) continue;
    link.hidden = Boolean(window.AutoTitrationAndroid);
    if (link.hidden) continue;
    const url = new URL(window.location.href);
    url.searchParams.set('remote', remote);
    if (remoteControlMode) url.searchParams.set('remote_control', '1');
    link.href = url.href;
    link.setAttribute('aria-current', compactViewMode === (remote === '1') ? 'page' : 'false');
  }
}

window.addEventListener('DOMContentLoaded', updateViewLinks);
window.addEventListener('hashchange', updateViewLinks);
const LOCAL_COLLECTOR_BACKEND = 'http://127.0.0.1:8766';
const DASHBOARD_LOCAL_BACKEND = 'http://127.0.0.1:8765';
const BACKEND_STORAGE_KEY = 'autoTitrationBackendBase';

let lastFrameAt = 0;
let settingsDirty = false;
let liveEvents = null;
let liveStreamBase = resolveInitialBackendBase();
let localFailoverTimer = null;
let roiSetupMode = true;
let latestRoiLocked = false;
let latestRoiComplete = false;
let latestRoiRecordable = false;
let latestLiveMetadata = {};
let roiDrag = null;
let selectedConstantsCandidate = null;
let latestConstantsLookup = null;
let constantsLookupTimer = null;
let constantsLookupSerial = 0;
let constantsSelectionMode = '';
let candidateNoticeTimer = null;
let currentAppMode = 'csv';
let latestCsvStatus = null;
let latestCsvStatusSource = '';
let autoRoiSetupEnabled = false;
let autoRoiSetupTimer = null;
let autoRoiRequestInFlight = false;
let backendRevision = 0;
let csvControlSequence = 0;
let csvStartInFlight = null;
let csvStopInFlight = null;
let pumpCommandSequence = 0;
let pumpMotionInFlight = null;
let pumpMotionPath = '';
let pumpStopInFlight = null;
let pumpStopCsvSessionKey = '';
const downloadedCsvSessions = new Set();
const demoViewApi = window.AutoTitrationDemoView || null;
const demoViewState = demoViewApi ? demoViewApi.createState(600) : null;

const AUTO_ROI_RETRY_MS = 1200;

const TITRATION_SUBSTANCE_PRESETS = {
  strong_acid_strong_base: {
    sample: 'hydrochloric acid',
    standard: 'sodium hydroxide',
    indicator: 'phenolphthalein',
  },
  weak_acid_strong_base: {
    sample: 'acetic acid',
    standard: 'sodium hydroxide',
    indicator: 'phenolphthalein',
  },
  strong_acid_weak_base: {
    sample: 'hydrochloric acid',
    standard: 'ammonia',
    indicator: 'methyl_orange',
  },
  weak_acid_weak_base: {
    sample: 'acetic acid',
    standard: 'ammonia',
    indicator: 'bromothymol_blue',
  },
};

function setText(id, value) {
  const element = $(id);
  if (element) element.textContent = value;
}

function setDemoConnection(connection) {
  if (!demoViewState) return;
  demoViewState.connection = connection;
  renderDemoView();
}

function resetDemoViewForBackend() {
  backendRevision += 1;
  csvControlSequence += 1;
  pumpCommandSequence += 1;
  constantsLookupSerial += 1;
  csvStartInFlight = null;
  csvStopInFlight = null;
  pumpMotionInFlight = null;
  pumpStopInFlight = null;
  pumpMotionPath = '';
  pumpStopCsvSessionKey = '';
  remoteSettingsSyncing = false;
  stopAutoRoiSetup();
  autoRoiRequestInFlight = false;
  latestCsvStatus = null;
  latestCsvStatusSource = '';
  latestLiveMetadata = {};
  latestRoiRecordable = false;
  latestRoiComplete = false;
  latestRoiLocked = false;
  roiDrag = null;
  updateCsvControlButtons();
  updatePumpCommandButtons();
  if (!demoViewState || !demoViewApi) return;
  demoViewApi.resetState(demoViewState);
  renderDemoView();
}

function drawTrend(canvasId, emptyId, valueKey, stroke, unit) {
  if (typeof compactViewMode !== 'undefined' && compactViewMode) return;
  const canvas = $(canvasId);
  if (!canvas || typeof canvas.getContext !== 'function' || !demoViewState) return;
  const samples = demoViewState.samples;
  const values = samples.map((sample) => sample[valueKey]).filter(Number.isFinite);
  const empty = $(emptyId);
  if (empty) empty.hidden = values.length > 0;
  const width = Math.max(220, Math.round(canvas.clientWidth || 640));
  const height = Math.max(160, Math.round(canvas.clientHeight || 240));
  const ratio = Math.min(2, window.devicePixelRatio || 1);
  if (canvas.width !== width * ratio || canvas.height !== height * ratio) {
    canvas.width = width * ratio;
    canvas.height = height * ratio;
  }
  const context = canvas.getContext('2d');
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  const plot = { left: 68, top: 20, right: width - 16, bottom: height - 32 };
  context.strokeStyle = '#e2e2e7';
  context.lineWidth = 1;
  for (let index = 0; index <= 3; index += 1) {
    const y = plot.top + ((plot.bottom - plot.top) * index) / 3;
    context.beginPath(); context.moveTo(plot.left, y); context.lineTo(plot.right, y); context.stroke();
  }
  if (!samples.length || !values.length) return;
  const xs = samples.map((sample) => sample.x).filter(Number.isFinite);
  let xMin = Math.min(...xs);
  let xMax = Math.max(...xs);
  let yMin = Math.min(...values);
  let yMax = Math.max(...values);
  if (xMin === xMax) xMax = xMin + 1;
  if (yMin === yMax) { yMin -= .5; yMax += .5; }
  const yPad = (yMax - yMin) * .08;
  yMin -= yPad; yMax += yPad;
  const xAt = (value) => plot.left + ((value - xMin) / (xMax - xMin)) * (plot.right - plot.left);
  const yAt = (value) => plot.bottom - ((value - yMin) / (yMax - yMin)) * (plot.bottom - plot.top);

  context.font = '11px Pretendard, system-ui, sans-serif';
  context.fillStyle = '#6e6e73';
  context.textAlign = 'right';
  context.fillText(`${yMax.toFixed(valueKey === 'thermalC' ? 1 : 2)} ${unit}`, plot.left - 6, plot.top + 4);
  context.fillText(`${yMin.toFixed(valueKey === 'thermalC' ? 1 : 2)} ${unit}`, plot.left - 6, plot.bottom);
  context.textAlign = 'left';
  context.fillText(`${xMin.toFixed(1)} s`, plot.left, height - 10);
  context.textAlign = 'right';
  context.fillText(`${xMax.toFixed(1)} s`, plot.right, height - 10);

  const labelEnds = [-Infinity, -Infinity, -Infinity];
  demoViewState.markers.filter((marker) => marker.x >= xMin && marker.x <= xMax).forEach((marker) => {
    const x = xAt(marker.x);
    context.strokeStyle = 'rgba(29, 29, 31, .24)';
    context.setLineDash([4, 4]);
    context.beginPath(); context.moveTo(x, plot.top); context.lineTo(x, plot.bottom); context.stroke();
    context.setLineDash([]);
    context.fillStyle = '#6e6e73';
    context.font = '10px Pretendard, system-ui, sans-serif';
    context.textAlign = 'center';
    const labelWidth = context.measureText(marker.label).width;
    const labelX = Math.max(plot.left + labelWidth / 2, Math.min(plot.right - labelWidth / 2, x));
    const lane = labelEnds.findIndex((end) => end + 4 < labelX - labelWidth / 2);
    if (lane >= 0) {
      context.fillText(marker.label, labelX, plot.top + 11 + lane * 12);
      labelEnds[lane] = labelX + labelWidth / 2;
    }
  });
  context.setLineDash([]);
  context.strokeStyle = stroke;
  context.lineWidth = 2.5;
  let drawing = false;
  const flushSegment = () => {
    if (!drawing) return;
    context.stroke();
    drawing = false;
  };
  samples.forEach((sample) => {
    const value = sample[valueKey];
    if (!Number.isFinite(value)) { flushSegment(); return; }
    const x = xAt(sample.x);
    const y = yAt(value);
    if (!drawing) { context.beginPath(); context.moveTo(x, y); drawing = true; }
    else context.lineTo(x, y);
  });
  flushSegment();
}

function renderDemoView() {
  if (!demoViewState) return;
  const result = demoViewState.result;
  const csv = demoViewState.csv || {};
  const lastStageLabel = demoViewState.stage?.label || '관측 대기';
  const stageLabel = demoViewState.connection === 'disconnected' ? '연결 끊김' : lastStageLabel;
  setText('demoStageValue', stageLabel);
  const connectionLabel = demoViewState.connection === 'live' ? '실시간 연결' : demoViewState.connection === 'disconnected' ? '재연결 대기' : '수집기 연결 중';
  const lastStageNote = demoViewState.connection === 'disconnected' ? ` · 마지막 상태 ${lastStageLabel}` : '';
  setText('demoStageNote', `${connectionLabel}${lastStageNote}`);
  setText('demoLiveVolume', Number.isFinite(parseFiniteNumber(csv.injected_volume_ml)) ? parseFiniteNumber(csv.injected_volume_ml).toFixed(2) : '-');
  const elapsed = parseFiniteNumber(csv.recording_elapsed_s ?? csv.pump_elapsed_s);
  setText('demoElapsedSeconds', Number.isFinite(elapsed) ? elapsed.toFixed(1) : '-');
  setText('calcFinalVolumeValue', Number.isFinite(result.volumeMl) ? result.volumeMl.toFixed(3) : '-');
  setText('calcPredictedEquivalenceValue', Number.isFinite(result.predictedVolumeMl) ? result.predictedVolumeMl.toFixed(3) : '-');
  setText('calcSampleConcentrationValue', Number.isFinite(result.concentrationM) ? result.concentrationM.toFixed(5) : '-');
  setText('demoCsvStatus', result.csvLabel);
  setText('demoOutcomeBadge', result.label);
  const badge = $('demoOutcomeBadge');
  if (badge) badge.dataset.outcome = result.outcome;
  drawTrend('colorTrendCanvas', 'colorTrendEmpty', 'color', '#0066cc', 'ΔRGB');
  drawTrend('thermalTrendCanvas', 'thermalTrendEmpty', 'thermalC', '#b54708', '°C');
}

function updateDemoCsvStatus(csv) {
  if (!demoViewApi || !demoViewState) return;
  demoViewApi.applyCsvStatus(demoViewState, csv);
  renderDemoView();
}

function updateDemoLiveSample(data, accepted) {
  if (!accepted || !demoViewApi || !demoViewState) return;
  demoViewState.connection = 'live';
  demoViewApi.appendSample(demoViewState, data, hasTrustedCelsiusTemperature(data));
  renderDemoView();
}

function showVisibleCandidateNotice(kind, title, body) {
  const notice = $('visibleCandidateNotice');
  if (!notice) return;
  if (candidateNoticeTimer) {
    window.clearTimeout(candidateNoticeTimer);
    candidateNoticeTimer = null;
  }
  const normalizedKind = ['success', 'error', 'waiting'].includes(kind) ? kind : 'waiting';
  notice.hidden = false;
  notice.classList.remove('is-success', 'is-error', 'is-waiting');
  notice.classList.add(`is-${normalizedKind}`);
  setText('visibleCandidateNoticeTitle', title);
  setText('visibleCandidateNoticeBody', body);
  if (normalizedKind !== 'waiting') {
    candidateNoticeTimer = window.setTimeout(() => hideVisibleCandidateNotice(), 5000);
  }
}

function hideVisibleCandidateNotice() {
  const notice = $('visibleCandidateNotice');
  if (!notice) return;
  if (candidateNoticeTimer) {
    window.clearTimeout(candidateNoticeTimer);
    candidateNoticeTimer = null;
  }
  notice.hidden = true;
  notice.classList.remove('is-success', 'is-error', 'is-waiting');
  notice.classList.add('is-waiting');
}

function normalizeBackendBase(value) {
  const raw = String(value ?? '').trim();
  if (!raw) return defaultBackendBase();
  if (raw === '.' || raw === './' || raw === '/') return '';
  const withoutTrailingSlash = raw.replace(/\/+$/, '');
  if (/^https?:\/\/[^/\s]+/i.test(withoutTrailingSlash)) return withoutTrailingSlash;
  if (/^\/[\S]*$/.test(withoutTrailingSlash)) return withoutTrailingSlash;
  throw new Error('http:// 또는 https:// 백엔드 주소를 입력하세요');
}

function isDashboardProxyOrigin() {
  try {
    const url = new URL(window.location.href);
    return (
      window.location.port === '8765' ||
      (['127.0.0.1', 'localhost'].includes(url.hostname) && ['8765', ''].includes(url.port))
    );
  } catch {
    return false;
  }
}

function isAndroidWebViewBridge() {
  return Boolean(window.AutoTitrationAndroid);
}

function defaultBackendBase() {
  if (isAndroidWebViewBridge()) return '';
  if (isDashboardProxyOrigin()) return '';
  return LOCAL_COLLECTOR_BACKEND;
}

function proxyBackendBase() {
  return isDashboardProxyOrigin() ? '' : LOCAL_COLLECTOR_BACKEND;
}

function migrateStoredBackendBase(value) {
  const raw = String(value ?? '').trim();
  if (isDashboardProxyOrigin()) return '';
  if (!raw) return raw;
  if (raw === DASHBOARD_LOCAL_BACKEND) {
    return defaultBackendBase();
  }
  try {
    const url = new URL(raw);
    if (['127.0.0.1', 'localhost'].includes(url.hostname) && url.port === '8765') {
      return defaultBackendBase();
    }
  } catch {
    // Non-URL values are validated later by normalizeBackendBase.
  }
  return raw;
}

function readStoredBackendBase() {
  try {
    return window.localStorage?.getItem(BACKEND_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

function writeStoredBackendBase(value) {
  try {
    window.localStorage?.setItem(BACKEND_STORAGE_KEY, value || '.');
  } catch {
    // 저장이 막힌 브라우저여도 현재 화면 연결은 계속 사용한다.
  }
}

function resolveInitialBackendBase() {
  try {
    if (typeof window.AUTO_TITRATION_STREAM_BASE === 'string') {
      return normalizeBackendBase(window.AUTO_TITRATION_STREAM_BASE || '.');
    }
    const stored = readStoredBackendBase();
    const migrated = migrateStoredBackendBase(stored);
    if (migrated !== stored) writeStoredBackendBase(migrated);
    return normalizeBackendBase(migrated || defaultBackendBase());
  } catch {
    return defaultBackendBase();
  }
}

function endpoint(path) {
  return `${liveStreamBase}${path}`;
}

function backendBaseDisplay(value = liveStreamBase) {
  return value || '현재 웹사이트 주소';
}

function setBackendBaseStatus(message) {
  setText('backendBaseStatus', message);
}

function updateCsvDownloadLinks(filename = 'auto-titration-live.csv') {
  const href = endpoint('/api/csv');
  ['csvDownloadLink', 'calcCsvDownloadLink'].forEach((id) => {
    const link = $(id);
    if (!link) return;
    link.href = href;
    link.download = filename;
  });
  return href;
}

function setPreviewSources() {
  if (compactViewMode) { updateCsvDownloadLinks('auto-titration-live.csv'); return; }
  const visible = $('visiblePreview');
  if (visible) visible.src = endpoint('/stream/visible.mjpg');
  const thermal = $('thermalPreview');
  if (thermal) {
    delete thermal.dataset.placeholder;
    thermal.src = endpoint('/stream/thermal.mjpg');
  }
  updateCsvDownloadLinks('auto-titration-ml-training.csv');
  setBackendBaseStatus(`백엔드: ${backendBaseDisplay()}`);
}

function csvSessionDownloadKey(csv) {
  const sessionId = csv?.session_id;
  if (sessionId === null || sessionId === undefined || String(sessionId).trim() === '') return '';
  const startedEpoch = csv?.started_epoch_s;
  const startIdentity = startedEpoch === null || startedEpoch === undefined ? '' : String(startedEpoch);
  return `${liveStreamBase}\n${String(sessionId)}\n${startIdentity}`;
}

function csvStatusSourcePriority(source) {
  return { live: 1, get: 2, post: 3 }[source] || 0;
}

function csvStatusVersion(csv) {
  return parseFiniteNumber(csv?.updated_epoch_s);
}

function csvSessionStartedEpoch(csv) {
  return parseFiniteNumber(csv?.started_epoch_s);
}

function shouldAcceptCsvStatus(csv, source) {
  if (!latestCsvStatus) return true;
  const incomingStart = csvSessionStartedEpoch(csv);
  const currentStart = csvSessionStartedEpoch(latestCsvStatus);
  if (Number.isFinite(incomingStart) && Number.isFinite(currentStart) && incomingStart !== currentStart) {
    return incomingStart > currentStart;
  }

  const incomingSession = csv?.session_id;
  const currentSession = latestCsvStatus.session_id;
  if (
    incomingSession !== null
    && incomingSession !== undefined
    && currentSession !== null
    && currentSession !== undefined
    && String(incomingSession) !== String(currentSession)
  ) {
    if (Number.isFinite(incomingStart) && !Number.isFinite(currentStart)) return true;
    if (!Number.isFinite(incomingStart) && !Number.isFinite(currentStart)) {
      const incomingNumber = Number(incomingSession);
      const currentNumber = Number(currentSession);
      return Number.isFinite(incomingNumber) && Number.isFinite(currentNumber) && incomingNumber > currentNumber;
    }
    return false;
  }

  const incomingVersion = csvStatusVersion(csv);
  const currentVersion = csvStatusVersion(latestCsvStatus);
  if (Number.isFinite(incomingVersion) && Number.isFinite(currentVersion)) {
    if (incomingVersion !== currentVersion) return incomingVersion > currentVersion;
    return csvStatusSourcePriority(source) > csvStatusSourcePriority(latestCsvStatusSource);
  }
  if (Number.isFinite(incomingVersion)) return true;
  if (Number.isFinite(currentVersion)) {
    return !(latestCsvStatus.state === 'stopped' && csv?.state === 'recording');
  }
  return !(latestCsvStatus.state === 'stopped' && csv?.state === 'recording');
}

function triggerCsvAutoDownload(csv = latestCsvStatus) {
  if (remoteControlMode) return false;
  const downloadKey = csvSessionDownloadKey(csv);
  if (!downloadKey || downloadedCsvSessions.has(downloadKey)) return false;
  downloadedCsvSessions.add(downloadKey);
  const filename = 'auto-titration-live.csv';
  const href = updateCsvDownloadLinks(filename);

  const autoLink = document.createElement('a');
  autoLink.href = href;
  autoLink.download = filename;
  autoLink.style.display = 'none';
  document.body.appendChild(autoLink);
  autoLink.click();
  autoLink.remove();
  setText('previewStatus', 'CSV 자동 다운로드 시작 요청');
  return true;
}

function shouldFailoverToDefaultBackend() {
  if (isDashboardProxyOrigin() && liveStreamBase === LOCAL_COLLECTOR_BACKEND) return true;
  const target = proxyBackendBase();
  if (liveStreamBase === target) return false;
  if (liveStreamBase === '') return isDashboardProxyOrigin();
  try {
    const url = new URL(liveStreamBase);
    return ['127.0.0.1', 'localhost'].includes(url.hostname) && url.port === '8765';
  } catch {
    return false;
  }
}

function clearLocalBackendFailover() {
  if (localFailoverTimer) {
    window.clearTimeout(localFailoverTimer);
    localFailoverTimer = null;
  }
}

function scheduleLocalBackendFailover(events) {
  clearLocalBackendFailover();
  if (!shouldFailoverToDefaultBackend()) return;
  localFailoverTimer = window.setTimeout(() => {
    if (events !== liveEvents || lastFrameAt) return;
    liveStreamBase = proxyBackendBase();
    latestCsvStatus = null;
    latestCsvStatusSource = '';
    resetDemoViewForBackend();
    const input = $('backendBaseInput');
    if (input) input.value = liveStreamBase || '.';
    writeStoredBackendBase(liveStreamBase);
    setBackendBaseStatus(`로컬 수집 서버로 자동 전환: ${backendBaseDisplay()}`);
    connectLiveStream();
    loadRoiSettings();
    refreshCsvStatus();
  }, 1400);
}

function parseFiniteNumber(value) {
  if (value === null || value === undefined) return Number.NaN;
  if (typeof value === 'string' && value.trim() === '') return Number.NaN;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
}

function hasFiniteNumber(value) {
  return Number.isFinite(parseFiniteNumber(value));
}

function isLikelyInvalidMini2ZeroCelsius(data = {}) {
  const status = String(data.thermal_conversion_status || '').trim();
  if (status) return status !== 'ok';
  if (data.thermal_celsius_fallback_reason || data.thermal_warning) return true;
  const temp = parseFiniteNumber(data.temperature_avg_c);
  if (!Number.isFinite(temp) || Math.abs(temp) > 0.05) return false;
  const raw = parseFiniteNumber(data.raw_avg ?? data.thermal_raw_roi_p50);
  const mode = String(data.thermal_mode || data.thermal_source || '');
  return Number.isFinite(raw) && Math.abs(raw) > 1 && /mini2|official|hikmicro/i.test(mode)
    && celsiusSummaryLooksAllZero(data);
}

function celsiusSummaryLooksAllZero(data = {}) {
  const fields = [
    'temperature_min_c',
    'temperature_max_c',
    'temperature_delta_c',
    'temperature_std_c',
    'thermal_roi_range',
    'thermal_roi_p05',
    'thermal_roi_p50',
    'thermal_roi_p95',
  ];
  const parsed = fields.map((field) => parseFiniteNumber(data[field])).filter(Number.isFinite);
  if (!parsed.length) return true;
  return parsed.every((value) => Math.abs(value) <= 0.05);
}

function celsiusAuthorizationFrom(data = {}) {
  const summary = data.temperature_summary && typeof data.temperature_summary === 'object'
    ? data.temperature_summary
    : {};
  const provenance = String(data.temperature_provenance ?? summary.provenance ?? '').trim();
  const scope = String(data.temperature_scope ?? summary.scope ?? '').trim();
  if (provenance === 'official_f2_analyzer_measurement_stats' && ['rectangle', 'fullscreen'].includes(scope)) {
    return data.official_measurement_status === 'READY'
      && data.official_measurement_matches_current_frame === true
      && data.official_measurement_temporal_scope === 'current_frame'
      && data.official_measurement_age_frames === 0
      ? { provenance, scope }
      : null;
  }
  if (
    (provenance === 'device_global_summary' && scope === 'device_global_summary')
    || (provenance === 'windows_official_mini2_roi_scalar' && scope === 'thermal_roi')
  ) {
    return { provenance, scope };
  }
  return null;
}

function hasTrustedCelsiusTemperature(data = {}) {
  const avg = parseFiniteNumber(data.temperature_avg_c);
  const min = parseFiniteNumber(data.temperature_min_c);
  const max = parseFiniteNumber(data.temperature_max_c);
  if (
    data.celsius_allowed !== true
    || data.full_matrix_celsius_allowed !== false
    || !celsiusAuthorizationFrom(data)
    || !Number.isFinite(avg)
    || !Number.isFinite(min)
    || !Number.isFinite(max)
    || min > avg
    || avg > max
    || isLikelyInvalidMini2ZeroCelsius(data)
  ) {
    return false;
  }
  const temp = avg;
  const raw = parseFiniteNumber(data.raw_avg ?? data.thermal_raw_roi_p50);
  if (Math.abs(temp) <= 0.05 && Number.isFinite(raw) && Math.abs(raw) > 1 && celsiusSummaryLooksAllZero(data)) {
    return false;
  }
  return true;
}

function formatNumber(value, digits = 1) {
  const parsed = parseFiniteNumber(value);
  if (!Number.isFinite(parsed)) return '-';
  return parsed.toFixed(digits);
}

function formatMs(value, digits = 0) {
  const parsed = parseFiniteNumber(value);
  if (!Number.isFinite(parsed)) return '-';
  return `${parsed.toFixed(digits)}ms`;
}

function formatSignedMs(value, digits = 0) {
  const parsed = parseFiniteNumber(value);
  if (!Number.isFinite(parsed)) return '-';
  const sign = parsed > 0 ? '+' : '';
  return `${sign}${parsed.toFixed(digits)}ms`;
}

function formatMl(value, digits = 3) {
  const parsed = parseFiniteNumber(value);
  if (!Number.isFinite(parsed)) return '-';
  return `${parsed.toFixed(digits)} mL`;
}

function formatMolar(value, digits = 4) {
  const parsed = parseFiniteNumber(value);
  if (!Number.isFinite(parsed)) return '-';
  return `${parsed.toFixed(digits)} M`;
}

function calculateEquivalenceVolumeMl({
  sampleConcentrationM,
  sampleVolumeMl,
  sampleValence = 1,
  titrantConcentrationM,
  titrantValence = 1,
}) {
  const sampleConcentration = parseFiniteNumber(sampleConcentrationM);
  const sampleVolume = parseFiniteNumber(sampleVolumeMl);
  const sampleN = parseFiniteNumber(sampleValence);
  const titrantConcentration = parseFiniteNumber(titrantConcentrationM);
  const titrantN = parseFiniteNumber(titrantValence);
  if (
    !Number.isFinite(sampleConcentration) || sampleConcentration <= 0 ||
    !Number.isFinite(sampleVolume) || sampleVolume <= 0 ||
    !Number.isFinite(sampleN) || sampleN <= 0 ||
    !Number.isFinite(titrantConcentration) || titrantConcentration <= 0 ||
    !Number.isFinite(titrantN) || titrantN <= 0
  ) {
    return Number.NaN;
  }
  return (sampleConcentration * sampleVolume * sampleN) / (titrantConcentration * titrantN);
}

function calculateSampleConcentrationM({
  titrantVolumeMl,
  titrantConcentrationM,
  titrantValence = 1,
  sampleVolumeMl,
  sampleValence = 1,
}) {
  const titrantVolume = parseFiniteNumber(titrantVolumeMl);
  const titrantConcentration = parseFiniteNumber(titrantConcentrationM);
  const titrantN = parseFiniteNumber(titrantValence);
  const sampleVolume = parseFiniteNumber(sampleVolumeMl);
  const sampleN = parseFiniteNumber(sampleValence);
  if (
    !Number.isFinite(titrantVolume) || titrantVolume < 0 ||
    !Number.isFinite(titrantConcentration) || titrantConcentration <= 0 ||
    !Number.isFinite(titrantN) || titrantN <= 0 ||
    !Number.isFinite(sampleVolume) || sampleVolume <= 0 ||
    !Number.isFinite(sampleN) || sampleN <= 0
  ) {
    return Number.NaN;
  }
  return (titrantConcentration * titrantVolume * titrantN) / (sampleVolume * sampleN);
}

const KW_25C = 1e-14;

function clampPh(value) {
  const parsed = parseFiniteNumber(value);
  if (!Number.isFinite(parsed)) return Number.NaN;
  return Math.max(0, Math.min(14, parsed));
}

function solveWeakBaseOh(kb, concentration) {
  return (-kb + Math.sqrt(kb * kb + 4 * kb * concentration)) / 2;
}

function solveWeakAcidH(ka, concentration) {
  return (-ka + Math.sqrt(ka * ka + 4 * ka * concentration)) / 2;
}

function calculateTheoreticalEquivalencePh({
  sampleConcentrationM,
  sampleVolumeMl,
  sampleValence = 1,
  titrantConcentrationM,
  titrantValence = 1,
  titrationType = 'strong_acid_strong_base',
  samplePka,
  titrantPkb,
}) {
  const equivalenceVolume = calculateEquivalenceVolumeMl({
    sampleConcentrationM,
    sampleVolumeMl,
    sampleValence,
    titrantConcentrationM,
    titrantValence,
  });
  const sampleConcentration = parseFiniteNumber(sampleConcentrationM);
  const sampleVolume = parseFiniteNumber(sampleVolumeMl);
  if (!Number.isFinite(equivalenceVolume) || !Number.isFinite(sampleConcentration) || !Number.isFinite(sampleVolume)) {
    return Number.NaN;
  }
  const totalVolumeL = (sampleVolume + equivalenceVolume) / 1000;
  if (totalVolumeL <= 0) return Number.NaN;
  const saltConcentration = Math.max((sampleConcentration * sampleVolume / 1000) / totalVolumeL, 1e-12);
  if (titrationType === 'strong_acid_strong_base') return 7.0;
  const pka = Number.isFinite(parseFiniteNumber(samplePka)) ? parseFiniteNumber(samplePka) : 4.76;
  const pkb = Number.isFinite(parseFiniteNumber(titrantPkb)) ? parseFiniteNumber(titrantPkb) : 4.75;
  if (titrationType === 'weak_acid_strong_base') {
    const ka = 10 ** (-pka);
    const kb = KW_25C / ka;
    const oh = solveWeakBaseOh(kb, saltConcentration);
    return clampPh(14 + Math.log10(Math.max(oh, 1e-14)));
  }
  if (titrationType === 'strong_acid_weak_base') {
    const kb = 10 ** (-pkb);
    const ka = KW_25C / kb;
    const h = solveWeakAcidH(ka, saltConcentration);
    return clampPh(-Math.log10(Math.max(h, 1e-14)));
  }
  if (titrationType === 'weak_acid_weak_base') {
    return clampPh(7 + 0.5 * (pkb - pka));
  }
  return Number.NaN;
}

function currentSelectedSamplePka() {
  return parseFiniteNumber(selectedConstantsCandidate?.pka_value);
}

function currentTheoreticalEquivalencePh() {
  return calculateTheoreticalEquivalencePh({
    ...currentChemistryNumbers(),
    titrationType: $('titrationTypeSelect')?.value || 'strong_acid_strong_base',
    samplePka: currentSelectedSamplePka(),
    titrantPkb: 4.75,
  });
}

function csvOrCurrentPositiveNumber(csv, key, fallback) {
  const fromCsv = parseFiniteNumber(csv?.[key]);
  if (Number.isFinite(fromCsv) && fromCsv > 0) return fromCsv;
  const parsedFallback = parseFiniteNumber(fallback);
  return Number.isFinite(parsedFallback) && parsedFallback > 0 ? parsedFallback : Number.NaN;
}

function predictedEquivalencePhFromCsv(csv) {
  const predicted = parseFiniteNumber(csv?.predicted_equivalence_pH);
  if (Number.isFinite(predicted)) return predicted;
  const predictedConcentration = parseFiniteNumber(csv?.sample_concentration_from_predicted_equivalence_M);
  if (!Number.isFinite(predictedConcentration) || predictedConcentration <= 0) return Number.NaN;
  const current = currentChemistryNumbers();
  return calculateTheoreticalEquivalencePh({
    sampleConcentrationM: predictedConcentration,
    sampleVolumeMl: csvOrCurrentPositiveNumber(csv, 'sample_volume_ml', current.sampleVolumeMl),
    sampleValence: csvOrCurrentPositiveNumber(csv, 'sample_valence', current.sampleValence),
    titrantConcentrationM: csvOrCurrentPositiveNumber(csv, 'titrant_concentration_M', current.titrantConcentrationM),
    titrantValence: csvOrCurrentPositiveNumber(csv, 'titrant_valence', current.titrantValence),
    titrationType: csv?.titration_type || $('titrationTypeSelect')?.value || 'strong_acid_strong_base',
    samplePka: parseFiniteNumber(csv?.selected_pka_value) || currentSelectedSamplePka(),
    titrantPkb: parseFiniteNumber(csv?.selected_pkb_value) || 4.75,
  });
}

function readNumericInput(id, fallback = Number.NaN) {
  const value = parseFiniteNumber($(id)?.value);
  return Number.isFinite(value) ? value : fallback;
}

function currentChemistryNumbers() {
  return {
    sampleConcentrationM: readNumericInput('sampleConcentrationInput'),
    sampleVolumeMl: readNumericInput('sampleVolumeInput'),
    sampleValence: readNumericInput('sampleValenceInput', 1),
    titrantConcentrationM: readNumericInput('standardConcentrationInput'),
    titrantValence: readNumericInput('titrantValenceInput', 1),
  };
}

function predictionSourceLabel(csv) {
  const source = String(csv?.predicted_equivalence_source || '').trim();
  if (source === 'type_conditioned_sensor_endpoint_ranker') return '적정 종류별 시계열 모델';
  if (source === 'typewise_frame_zone_classifier') return '적정 종류별 분류 모델';
  if (source === 'ml_json_regression_model') return '모델 예측';
  if (source === 'live_feature_peak_estimator') return '센서 peak 추정';
  if (source) return source;
  return '';
}

function predictionReadinessReasonLabel(reason) {
  const labels = {
    insufficient_usable_sensor_time_volume_observations: '사용 가능한 센서·시간·주입량 관측이 부족합니다',
    insufficient_recorded_time_progression: '기록 시간이 충분히 진행되지 않았습니다',
    insufficient_recording_time_span: '기록 시간이 충분히 진행되지 않았습니다',
    insufficient_recorded_volume_progression: '주입량 변화가 충분하지 않습니다',
    no_sensor_variation: '센서 변화가 감지되지 않았습니다',
    flat_recorded_sensor_signals: '센서 변화가 감지되지 않았습니다',
  };
  const normalized = String(reason || '').trim();
  return labels[normalized] || normalized || '충분한 예측 데이터가 없습니다';
}

function predictionValuesAvailable(csv) {
  const status = String(csv?.predicted_equivalence_status || '').trim();
  return !status || status === 'available';
}

function predictionReadinessStatusLabel(csv) {
  const status = String(csv?.predicted_equivalence_status || '').trim();
  const reason = predictionReadinessReasonLabel(csv?.predicted_equivalence_reason);
  if (status === 'withheld') return `예측 보류 · ${reason}`;
  if (status === 'unavailable') return `예측 사용 불가 · ${reason}`;
  if (status === 'pending') return `예측 준비 중 · ${reason}`;
  return '';
}

function updateConcentrationModePreview(csv = latestCsvStatus) {
  const predictedVolume = parseFiniteNumber(csv?.predicted_equivalence_volume_ml);
  const concentration = parseFiniteNumber(csv?.sample_concentration_from_predicted_equivalence_M);
  const sourceLabel = predictionSourceLabel(csv);
  const valuesAvailable = predictionValuesAvailable(csv);
  const readinessLabel = predictionReadinessStatusLabel(csv);

  const finalValuesAvailable = valuesAvailable && csv?.state === 'stopped';
  setText('calcPredictedEquivalenceValue', finalValuesAvailable ? formatMl(predictedVolume, 3) : '-');
  setText('calcSampleConcentrationValue', finalValuesAvailable ? formatMolar(concentration, 5) : '-');
  const terminalVolume = csv?.state === 'stopped'
    ? parseFiniteNumber(csv?.injected_volume_ml)
    : Number.NaN;
  setText('calcFinalVolumeValue', Number.isFinite(terminalVolume) ? terminalVolume.toFixed(3) : '-');

  const terminalFault = csv?.state === 'stopped'
    && (csv?.auto_stop_state === 'error' || /failed|error|missing/.test(String(csv?.auto_stop_reason || '')));
  if (terminalFault) {
    setText('calcModeStatus', readinessLabel ? `오류로 종료 · ${readinessLabel}` : '오류로 종료 · 계산값은 참고용');
  } else if (readinessLabel) {
    setText('calcModeStatus', readinessLabel);
  } else if (Number.isFinite(predictedVolume) && Number.isFinite(concentration)) {
    const source = sourceLabel || '예측 계산';
    const stopReason = String(csv?.auto_stop_reason || '');
    if (csv?.state === 'stopped' && (csv?.auto_stop_state === 'error' || /failed|error|missing/.test(stopReason))) {
      setText('calcModeStatus', '오류로 종료 · 계산값은 참고용');
    } else if (csv?.state === 'stopped' && csv?.auto_stop_state === 'triggered' && stopReason === 'persistent_color_change') {
      setText('calcModeStatus', `${source} 완료`);
    } else if (csv?.state === 'stopped' && csv?.auto_stop_state === 'triggered') {
      setText('calcModeStatus', '안전 정지 · 계산값 확인');
    } else if (csv?.state === 'stopped') {
      setText('calcModeStatus', '수동 종료 · 계산값 확인');
    } else {
      setText('calcModeStatus', `${source} 준비됨`);
    }
  } else if (csv?.state === 'recording' || csv?.recording) {
    setText('calcModeStatus', '녹화 중 · 종료하면 자동 계산');
  } else if (csv?.state === 'stopped') {
    setText('calcModeStatus', '예측값 없음 · CSV 확인');
  } else {
    setText('calcModeStatus', '녹화 종료 후 계산 결과 표시');
  }
}

function updateConcentrationCalculationPreview({ writeTheory = true } = {}) {
  const chemistry = currentChemistryNumbers();
  const calculatedTheory = calculateEquivalenceVolumeMl(chemistry);
  if (Number.isFinite(calculatedTheory)) {
    if (writeTheory) {
      const theoryInput = $('theoryEquivalenceInput');
      if (theoryInput) theoryInput.value = calculatedTheory.toFixed(2);
    }
    setText('calculatedConcentrationValue', '-');
    const label = $('calculatedConcentrationValue');
    if (label) {
      label.title = '예측 농도 대기';
    }
  } else {
    setText('calculatedConcentrationValue', '-');
  }
  updateConcentrationModePreview();
  return calculatedTheory;
}

function setAppMode(mode) {
  const normalized = mode === 'calculator' ? 'calculator' : 'csv';
  currentAppMode = normalized;
  document.body.dataset.appMode = normalized;
  const calculatorMode = !compactViewMode && normalized === 'calculator';

  document.querySelectorAll('.csv-mode-only').forEach((element) => {
    element.classList.toggle('mode-hidden', calculatorMode);
    if ('hidden' in element) element.hidden = calculatorMode;
  });
  const calculatorPanel = $('concentrationCalculatorControls');
  if (calculatorPanel) calculatorPanel.hidden = !calculatorMode;
  const sensorGrid = $('sensorGrid');
  if (sensorGrid) sensorGrid.hidden = calculatorMode;
  const resultsView = $('resultsView');
  if (resultsView) resultsView.hidden = !calculatorMode;

  const csvButton = $('csvCollectionModeButton');
  const calculatorButton = $('concentrationCalculationModeButton');
  if (csvButton) {
    csvButton.classList.toggle('is-active', !calculatorMode);
    csvButton.setAttribute('aria-selected', calculatorMode ? 'false' : 'true');
  }
  if (calculatorButton) {
    calculatorButton.classList.toggle('is-active', calculatorMode);
    calculatorButton.setAttribute('aria-selected', calculatorMode ? 'true' : 'false');
  }
  if (calculatorMode) {
    updateConcentrationModePreview();
    renderDemoView(); // Re-size the plots after revealing the result panel.
  }
}

function setWaiting(message) {
  setText('previewStatus', message);
  setText('visibleState', '카메라 대기');
  setText('syncQuality', '동기화 대기');
}

function csvStateLabel(csv) {
  if (csv?.recording) return '녹화';
  if (csv?.finalizing || csv?.state === 'finalizing') return '분석 마무리';
  if (csv?.state === 'stopped') return '종료';
  return '대기';
}

function autoStopLabel(csv) {
  const state = String(csv?.auto_stop_state || 'disabled');
  const reason = String(csv?.auto_stop_reason || '');
  const pulseState = String(csv?.auto_stop_pulse_state || '');
  if (state === 'triggered') {
    if (reason === 'persistent_color_change') return '색 변화 감지 정지';
    if (reason === 'pulse_control_failed') return '미세 주입 제어 오류 정지';
    if (reason === 'emergency_stop') return '비상 정지';
    if (reason.includes('maximum_volume')) return '최대량 안전정지';
    return '자동 안전정지';
  }
  if (pulseState === 'pulse_injecting') return '미세 주입 중';
  if (pulseState === 'pulse_settling') return '미세 주입 · 혼합 대기';
  if (pulseState === 'slow_continuous') return '저속 연속 주입 중 · 명목 유량';
  if (state === 'armed_calibrating') return '초기 색 보정 중';
  if (state === 'armed_confirming') return '색 변화 확인 중';
  if (state === 'armed') return '색 변화 감시 중';
  if (state === 'armed_safety_only') return '모델 없음 · 최대량 감시';
  if (state === 'unavailable') return reason === 'pump_not_started' ? '펌프 연결 필요' : '사용 불가';
  if (state === 'error') return '정지 오류';
  return '꺼짐';
}

function formatHealthAge(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return '';
  return ` · ${formatMs(parsed)}`;
}

function applyCollectorHealth(health) {
  if (!health?.ok) throw new Error(health?.error || 'collector health not ok');
  const latest = health.latest || {};
  const csv = health.csv || {};
  const visibleAge = formatHealthAge(health.visible_age_ms);
  const thermalAge = formatHealthAge(health.thermal_age_ms);
  const retryCount = Number(health.mini2_retry_count ?? latest.mini2_retry_count ?? 0);
  const reconnectCount = Number(health.mini2_reconnect_count ?? latest.mini2_reconnect_count ?? 0);
  const thermalMode = latest.thermal_mode || latest.thermal_source || '';
  setText(
    'healthCollectorValue',
    health.metadata_ready ? `동작 중${formatHealthAge(health.metadata_age_ms)}` : '메타데이터 대기',
  );
  setText(
    'healthVisibleValue',
    health.visible_stream_ready ? `수신 중${visibleAge}` : '카메라 대기',
  );
  let mini2Text = health.thermal_stream_ready ? `수신 중${thermalAge}` : '열화상 대기';
  if (health.mini2_unavailable || thermalMode === 'mini2_unavailable') {
    mini2Text = `재탐색 중 · retry ${Number.isFinite(retryCount) ? retryCount : 0}`;
  } else if (Number.isFinite(reconnectCount) && reconnectCount > 0) {
    mini2Text += ` · reconnect ${reconnectCount}`;
  }
  setText('healthThermalValue', mini2Text);
  setText('healthCsvValue', `${csvStateLabel(csv)} · ${formatNumber(csv.row_count ?? 0, 0)}행`);
  if (health.pump && shouldApplyPumpHealthLabel(health.pump)) setText('pumpCommandStatus', pumpHealthLabel(health.pump));
  const guard = health.absolute_pump_guard || {};
  if (guard.absolute_guard_reason === 'absolute_deadline_reached') {
    const seconds = parseFiniteNumber(guard.absolute_guard_effective_maximum_run_time_s);
    setText(
      'pumpCommandStatus',
      `안전 제한 정지${Number.isFinite(seconds) ? ` · ${seconds.toFixed(1)}초` : ''}`,
    );
  } else if (guard.absolute_guard_state === 'stop_unconfirmed') {
    setText('pumpCommandStatus', `정지 확인 실패 · ${guard.absolute_guard_error || '-'}`);
  }
  const hints = Array.isArray(health.action_hints) ? health.action_hints : [];
  setText('healthActionValue', hints[0] || '상태 확인 중');
}

async function refreshCollectorHealth() {
  const requestBackendRevision = backendRevision;
  try {
    const response = await fetch(endpoint('/api/collector-health'), { cache: 'no-store' });
    if (requestBackendRevision !== backendRevision) return null;
    const payload = await response.json().catch(() => ({}));
    if (requestBackendRevision !== backendRevision) return null;
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `health ${response.status}`);
    applyCollectorHealth(payload);
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    setText('healthCollectorValue', '연결 안 됨');
    setText('healthVisibleValue', '대기');
    setText('healthThermalValue', '대기');
    setText('healthCsvValue', '대기');
    setText('healthActionValue', `Collector 창/포트 8766 확인 · ${error.message}`);
  }
}

function applyCsvStatus(csv, { source = '' } = {}) {
  if (!csv) return;
  if (!shouldAcceptCsvStatus(csv, source)) return false;
  const previousState = latestCsvStatus?.state;
  const previousSessionId = latestCsvStatus?.session_id;
  const previousStartedEpoch = latestCsvStatus?.started_epoch_s;
  const normalizedCsv = { ...csv };
  if (
    (normalizedCsv.session_id === null || normalizedCsv.session_id === undefined)
    && previousSessionId !== null
    && previousSessionId !== undefined
  ) {
    normalizedCsv.session_id = previousSessionId;
  }
  if (
    (normalizedCsv.started_epoch_s === null || normalizedCsv.started_epoch_s === undefined)
    && previousStartedEpoch !== null
    && previousStartedEpoch !== undefined
  ) {
    normalizedCsv.started_epoch_s = previousStartedEpoch;
  }
  csv = normalizedCsv;
  latestCsvStatus = normalizedCsv;
  latestCsvStatusSource = source;
  setText('csvRowCount', formatNumber(csv.row_count, 0));
  const rowsPerSecond = parseFiniteNumber(csv.csv_rows_per_s);
  setText('csvRowsPerSecondValue', Number.isFinite(rowsPerSecond) ? `${rowsPerSecond.toFixed(1)}/s` : '-');
  setText('csvPathLabel', csv.path || '-');
  setText('csvStateLabel', csvStateLabel(csv));
  setText('autoStopStatus', autoStopLabel(csv));
  const csvSessionKey = csvSessionDownloadKey(csv);
  if (csv.auto_stop_state === 'triggered' && csvSessionKey !== pumpStopCsvSessionKey) {
    const volume = parseFiniteNumber(csv.auto_stop_trigger_volume_ml);
    setText(
      'pumpCommandStatus',
      `${autoStopLabel(csv)}${Number.isFinite(volume) ? ` · ${formatMl(volume, 2)}` : ''}`,
    );
  }
  setText('pumpVolumeValue', formatMl(csv.injected_volume_ml));
  if (
    predictionValuesAvailable(csv)
    && hasFiniteNumber(csv.sample_concentration_from_predicted_equivalence_M)
  ) {
    setText('calculatedConcentrationValue', formatMolar(csv.sample_concentration_from_predicted_equivalence_M));
    const label = $('calculatedConcentrationValue');
    if (label) {
      const predictedVolume = parseFiniteNumber(csv.predicted_equivalence_volume_ml);
      const error = parseFiniteNumber(csv.predicted_sample_concentration_error_percent);
      const bits = [predictionSourceLabel(csv) || '예측 당량점'];
      if (Number.isFinite(predictedVolume)) bits.push(`Veq ${formatMl(predictedVolume, 3)}`);
      if (Number.isFinite(error)) bits.push(`입력 농도 대비 ${error >= 0 ? '+' : ''}${error.toFixed(2)}%`);
      if (csv.predicted_equivalence_model_key) bits.push(String(csv.predicted_equivalence_model_key));
      label.title = bits.join(' · ');
    }
  } else {
    setText('calculatedConcentrationValue', '-');
    const label = $('calculatedConcentrationValue');
    if (label) {
      const readinessLabel = predictionReadinessStatusLabel(csv);
      label.title = readinessLabel || (
        hasFiniteNumber(csv.sample_concentration_from_injected_M)
          ? '예측 농도 대기 · 현재 주입량 역산값은 최종 농도 표시에서 제외'
          : '예측 농도 대기'
      );
    }
  }
  updateConcentrationModePreview(csv);
  setText('equivalenceDistanceValue', formatMl(csv.distance_to_equivalence_ml));
  setText('equivalenceLabelValue', csv.equivalence_window_label || '-');
  updateCsvControlButtons(csv);
  updateCsvDownloadLinks('auto-titration-live.csv');
  updateDemoCsvStatus(csv);
  if (['recording', 'finalizing'].includes(previousState) && csv.state === 'stopped') {
    triggerCsvAutoDownload(csv);
    setAppMode('calculator');
  }
  return true;
}

function updateCsvControlButtons(csv = latestCsvStatus) {
  const startButton = $('csvStartButton');
  const stopButton = $('csvStopButton');
  const busy = Boolean(csv?.recording || csv?.finalizing || csv?.state === 'finalizing');
  if (startButton) {
    startButton.disabled = busy || Boolean(csvStartInFlight || csvStopInFlight)
      || !latestRoiRecordable || !latestRoiComplete;
  }
  if (stopButton) stopButton.disabled = !(csv?.recording || csvStartInFlight);
}

function readPositiveNumberInput(id, label) {
  const raw = $(id)?.value;
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${label}은 0보다 큰 숫자여야 합니다`);
  }
  return value;
}

function readTextInput(id) {
  return String($(id)?.value || '').trim();
}

function readRequiredTextInput(id, label) {
  const value = readTextInput(id);
  if (!value) {
    throw new Error(`${label}은 비어 있을 수 없습니다`);
  }
  return value;
}

function selectedIndicatorLabel() {
  const select = $('indicatorSelect');
  const option = select?.selectedOptions?.[0];
  return option?.textContent?.trim() || select?.value || '-';
}

function setSelectValueIfPresent(id, value) {
  const select = $(id);
  if (!select || value === undefined) return false;
  const hasOption = Array.from(select.options || []).some((option) => option.value === value);
  if (!hasOption) return false;
  select.value = value;
  return true;
}

function applyTitrationTypePreset({ lookup = true } = {}) {
  const type = $('titrationTypeSelect')?.value || 'weak_acid_strong_base';
  const preset = TITRATION_SUBSTANCE_PRESETS[type] || TITRATION_SUBSTANCE_PRESETS.weak_acid_strong_base;
  const sampleChanged = setSelectValueIfPresent('sampleSubstanceInput', preset.sample);
  setSelectValueIfPresent('standardSolutionNameInput', preset.standard);
  setSelectValueIfPresent('indicatorSelect', preset.indicator);
  updateConcentrationCalculationPreview({ writeTheory: true });
  if (lookup && sampleChanged) scheduleChemistryConstantsLookup(0);
}

function indicatorTransitionRange(key) {
  return {
    phenolphthalein: [8.2, 10.0],
    methyl_orange: [3.1, 4.4],
    bromothymol_blue: [6.0, 7.6],
  }[key] || [null, null];
}

function constantsCandidateLabel(candidate) {
  const pka = Number(candidate?.pka_value);
  const pkaText = Number.isFinite(pka) ? pka.toFixed(3) : '-';
  const temp = Number(candidate?.temperature_c);
  const tempText = Number.isFinite(temp) ? `${temp.toFixed(Math.abs(temp - Math.round(temp)) < 0.05 ? 0 : 1)}℃` : '온도 미기재';
  return `${candidate?.pka_type || 'pKa'} ${pkaText} · ${tempText} · ${candidate?.name || candidate?.nickname || candidate?.unique_id || 'candidate'}`;
}

function roomTemperatureCandidateScore(candidate, index = 0) {
  const temp = Number(candidate?.temperature_c);
  const tempPenalty = Number.isFinite(temp) ? Math.abs(temp - 25.0) : 12.0;
  const pkaType = String(candidate?.pka_type || '').toLowerCase();
  const text = [
    pkaType,
    candidate?.remarks,
    candidate?.cosolvent,
    candidate?.assessment,
  ].join(' ').toLowerCase();
  let score = -tempPenalty;
  if (pkaType === 'pka' || pkaType === 'pka1') score += 30;
  else if (pkaType.startsWith('pka')) score += 8;
  if (pkaType.includes('pkah')) score -= 8;
  if (text.includes('d2o') || text.includes('deuter') || pkaType.includes('0-d')) score -= 30;
  if (String(candidate?.cosolvent || '').trim()) score -= 10;
  if (String(candidate?.assessment || '').toLowerCase() === 'reliable') score += 6;
  const upstreamScore = Number(candidate?.score);
  if (Number.isFinite(upstreamScore)) score += upstreamScore * 0.02;
  return score - index * 0.001;
}

function pickRoomTemperatureCandidateIndex(candidates) {
  if (!Array.isArray(candidates) || !candidates.length) return -1;
  let bestIndex = 0;
  let bestScore = roomTemperatureCandidateScore(candidates[0], 0);
  candidates.forEach((candidate, index) => {
    const score = roomTemperatureCandidateScore(candidate, index);
    if (score > bestScore) {
      bestScore = score;
      bestIndex = index;
    }
  });
  return bestIndex;
}

function autoSelectRoomTemperatureCandidate(candidates) {
  const index = pickRoomTemperatureCandidateIndex(candidates);
  if (index < 0) {
    selectedConstantsCandidate = null;
    constantsSelectionMode = '';
    return null;
  }
  selectedConstantsCandidate = candidates[index];
  constantsSelectionMode = 'auto_room_temperature';
  const candidateSelect = $('constantsCandidateSelect');
  if (candidateSelect) candidateSelect.value = String(index);
  setText('constantsLookupStatus', `자동 선택 · 상온 우선 · ${constantsCandidateLabel(selectedConstantsCandidate)}`);
  setText('activityWarningLabel', '실시간 계산 안 함');
  return selectedConstantsCandidate;
}

function constantsConfirmationStatus(candidateCount, constantsAmbiguous) {
  if (selectedConstantsCandidate) {
    if (constantsSelectionMode === 'user') return 'confirmed_by_user';
    if (constantsSelectionMode === 'auto_room_temperature') return 'auto_selected_room_temperature';
    return constantsAmbiguous ? 'auto_selected_ranked_candidate' : 'single_candidate';
  }
  if (candidateCount > 1) return 'unconfirmed_ambiguous';
  if (candidateCount === 0) return 'not_found_or_not_looked_up';
  return 'unselected';
}

function buildChemistryMetadataPayload() {
  const titrationType = readRequiredTextInput('titrationTypeSelect', '적정 종류');
  const sampleQuery = readRequiredTextInput('sampleSubstanceInput', '시료 물질');
  const sampleConcentration = readPositiveNumberInput('sampleConcentrationInput', '시료 농도');
  const sampleVolume = readPositiveNumberInput('sampleVolumeInput', '시료 부피');
  const sampleValence = Math.max(1, readNumericInput('sampleValenceInput', 1));
  const titrantName = readRequiredTextInput('standardSolutionNameInput', '표준용액 이름');
  const standardConcentration = readPositiveNumberInput('standardConcentrationInput', '표준용액 농도');
  const titrantValence = Math.max(1, readNumericInput('titrantValenceInput', 1));
  const indicator = $('indicatorSelect')?.value || 'phenolphthalein';
  const [transitionLow, transitionHigh] = indicatorTransitionRange(indicator);
  const candidateCount = Number(latestConstantsLookup?.candidate_count ?? 0);
  const constantsAmbiguous = Boolean(latestConstantsLookup?.ambiguous);
  const calculatedTheory = updateConcentrationCalculationPreview({ writeTheory: false });
  const theoreticalPh = currentTheoreticalEquivalencePh();
  const concentrationFromTheory = calculateSampleConcentrationM({
    titrantVolumeMl: Number($('theoryEquivalenceInput')?.value || calculatedTheory),
    titrantConcentrationM: standardConcentration,
    titrantValence,
    sampleVolumeMl: sampleVolume,
    sampleValence,
  });
  const payload = {
    titration_type: titrationType,
    sample_name: sampleQuery,
    sample_concentration_M: sampleConcentration,
    sample_volume_ml: sampleVolume,
    sample_valence: sampleValence,
    titrant_name: titrantName,
    titrant_concentration_M: standardConcentration,
    titrant_valence: titrantValence,
    indicator,
    chemistry_model: 'live_collection_metadata_only',
    chemistry_model_version: '1.0',
    constants_query: sampleQuery,
    constants_candidate_count: candidateCount,
    constants_lookup_ambiguous: constantsAmbiguous,
    constants_confirmation_status: constantsConfirmationStatus(candidateCount, constantsAmbiguous),
    constants_warning: latestConstantsLookup?.warning || '',
    activity_model: 'davies_ionic_strength_warning_not_calculated_live',
    indicator_transition_low_pH: transitionLow,
    indicator_transition_high_pH: transitionHigh,
    indicator_endpoint_confidence: 'not_calculated_no_ph_curve',
    indicator_endpoint_warning: '지시약 변색범위만 기록합니다. pH 곡선 기반 예상 종말점은 별도 분석에서 계산합니다.',
    standard_solution_uncertainty_note: '표준용액 농도는 사용자가 입력한 값입니다',
    equivalence_formula: "nMV=n'M'V'",
  };
  if (Number.isFinite(calculatedTheory)) {
    payload.calculated_theoretical_equivalence_volume_ml = Number(calculatedTheory.toFixed(6));
  }
  if (Number.isFinite(theoreticalPh)) {
    payload.theoretical_equivalence_pH = Number(theoreticalPh.toFixed(6));
  }
  if (Number.isFinite(concentrationFromTheory)) {
    payload.sample_concentration_from_theoretical_equivalence_M = Number(concentrationFromTheory.toFixed(8));
  }
  if (selectedConstantsCandidate) {
    payload.constants_source = 'IUPAC Dissociation Constants high-confidence local CSV';
    payload.constants_source_id = selectedConstantsCandidate.unique_id || '';
    payload.selected_pka_type = selectedConstantsCandidate.pka_type || '';
    payload.selected_pka_value = selectedConstantsCandidate.pka_value;
    payload.selected_pka_temperature_c = selectedConstantsCandidate.temperature_c;
  }
  return payload;
}

function buildPumpSafetyPayload() {
  return {
    maximum_pump_rate_ml_per_s: 1.05,
    absolute_maximum_volume_ml: 100.0,
    absolute_maximum_run_time_s: 120.0,
  };
}

function buildPumpTimelineStartPayload() {
  const calculatedTheory = updateConcentrationCalculationPreview({ writeTheory: false });
  const manualTheory = Number($('theoryEquivalenceInput')?.value);
  const theoryVolume = Number.isFinite(manualTheory) && manualTheory > 0 ? manualTheory : calculatedTheory;
  const autoStopEnabled = Boolean($('autoStopEnabledInput')?.checked);
  const slowStageEnabled = autoStopEnabled && Boolean($('slowStageEnabledInput')?.checked);
  const slowRateSteps = Number($('slowRateStepsInput')?.value || 25);
  return {
    pump_rate_ml_per_s: readPositiveNumberInput('pumpRateInput', '펌프 유량'),
    ...buildPumpSafetyPayload(),
    manual_unbounded: !autoStopEnabled,
    theoretical_equivalence_volume_ml: Number.isFinite(theoryVolume)
      ? Number(theoryVolume.toFixed(6))
      : readPositiveNumberInput('theoryEquivalenceInput', '이론 당량점'),
    equivalence_window_ml: readPositiveNumberInput('equivalenceWindowInput', '당량점 허용범위'),
    auto_stop_enabled: autoStopEnabled,
    // Auto-stop learns the starting ROI color and waits for a live-model
    // confirmation plus a persistent color transition. Theory is not a gate.
    auto_stop_confirmation_delay_s: 0.4,
    auto_stop_maximum_volume_ml: 100.0,
    // At the live-model approach threshold, continuous pumping stops. The
    // firmware then injects five full steps at a time and waits before the
    // existing persistent-color endpoint confirmation runs again.
    auto_stop_pulse_enabled: autoStopEnabled,
    auto_stop_pulse_approach_score: 0.20,
    auto_stop_pulse_steps: 5,
    auto_stop_pulse_settle_time_s: 0.50,
    auto_stop_slow_stage_enabled: slowStageEnabled,
    auto_stop_slow_onset_score: 0.10,
    auto_stop_slow_onset_duration_s: 0.50,
    auto_stop_slow_rate_steps_per_s: slowRateSteps,
    pulse_nominal_ml_per_step: 0.0099,
    pulse_ml_per_step_upper_bound: 0.0105,
    ...buildChemistryMetadataPayload(),
  };
}

async function lookupChemistryConstants({ silent = false } = {}) {
  const requestBackendRevision = backendRevision;
  const query = readTextInput('sampleSubstanceInput');
  const requestSerial = ++constantsLookupSerial;
  selectedConstantsCandidate = null;
  constantsSelectionMode = '';
  latestConstantsLookup = null;
  const candidateSelect = $('constantsCandidateSelect');
  if (!query) {
    if (candidateSelect) {
      candidateSelect.innerHTML = '<option value="">시료 물질 입력</option>';
      candidateSelect.disabled = true;
    }
    setText('constantsLookupStatus', '시료 입력 대기');
    return;
  }
  if (candidateSelect) {
    candidateSelect.innerHTML = '<option value="">조회 중</option>';
    candidateSelect.disabled = true;
  }
  if (!silent) setText('constantsLookupStatus', '조회 중');
  try {
    const response = await fetch(endpoint('/api/chemistry/constants/lookup'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, limit: 8 }),
    });
    const payload = await response.json().catch(() => ({}));
    if (requestBackendRevision !== backendRevision) return null;
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `상수 API ${response.status}`);
    if (requestSerial !== constantsLookupSerial || query !== readTextInput('sampleSubstanceInput')) return;
    latestConstantsLookup = payload;
    const candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
    populateConstantsCandidateSelect(candidates, Boolean(payload.ambiguous));
    if (!candidates.length) {
      setText('constantsLookupStatus', payload.warning || '후보 없음');
      return;
    }
    autoSelectRoomTemperatureCandidate(candidates);
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    setText('constantsLookupStatus', `실패 · ${error.message}`);
  }
}

function populateConstantsCandidateSelect(candidates, ambiguous) {
  const candidateSelect = $('constantsCandidateSelect');
  if (!candidateSelect) return;
  candidateSelect.innerHTML = '';
  const placeholder = document.createElement('option');
  placeholder.value = '';
  placeholder.textContent = ambiguous ? '상온 후보 자동 선택, 필요 시 변경' : '상온 후보 자동 선택';
  candidateSelect.appendChild(placeholder);
  candidates.forEach((candidate, index) => {
    const option = document.createElement('option');
    option.value = String(index);
    option.textContent = `${constantsCandidateLabel(candidate)} · ${candidate.assessment || '-'}`;
    candidateSelect.appendChild(option);
  });
  candidateSelect.disabled = candidates.length === 0;
}

function selectConstantsCandidate() {
  const candidateSelect = $('constantsCandidateSelect');
  const candidates = Array.isArray(latestConstantsLookup?.candidates) ? latestConstantsLookup.candidates : [];
  const rawValue = candidateSelect?.value ?? '';
  if (rawValue === '') {
    selectedConstantsCandidate = null;
    constantsSelectionMode = '';
    setText('constantsLookupStatus', candidates.length ? '후보 미선택' : '미선택');
    return;
  }
  const index = Number(rawValue);
  selectedConstantsCandidate = Number.isInteger(index) && index >= 0 && index < candidates.length ? candidates[index] : null;
  if (!selectedConstantsCandidate) {
    constantsSelectionMode = '';
    setText('constantsLookupStatus', candidates.length ? '후보 미선택' : '미선택');
    return;
  }
  constantsSelectionMode = 'user';
  setText('constantsLookupStatus', `선택됨 · ${constantsCandidateLabel(selectedConstantsCandidate)}`);
}

function csvOperationFailureLabel(path) {
  return path.endsWith('/stop') ? '녹화 종료 실패' : '녹화 시작 실패';
}

async function postCsvControl(path, pendingText, body, requestSequence) {
  const requestBackendRevision = backendRevision;
  setText('csvStateLabel', pendingText);
  try {
    if (remoteControlMode && path === '/api/csv/start') {
      const configResponse = await fetch(endpoint('/api/remote/config'), { cache: 'no-store' });
      if (requestBackendRevision !== backendRevision) return null;
      const shared = await configResponse.json().catch(() => ({}));
      if (requestBackendRevision !== backendRevision) return null;
      if (requestSequence !== csvControlSequence) return null;
      if (!configResponse.ok || !shared.ok || !shared.config) {
        throw new Error('노트북의 실험 설정이 아직 동기화되지 않았습니다. 설정과 연결 상태를 확인하세요');
      }
      body = shared.config;
    }
    const response = await fetch(endpoint(path), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
    const payload = await response.json().catch(() => ({}));
    if (requestBackendRevision !== backendRevision) return null;
    if (requestSequence !== csvControlSequence) return null;
    if (!response.ok || payload.ok === false) {
      const rawError = String(payload.error || `CSV API ${response.status}`);
      let explanation = '';
      if (rawError.includes('acknowledged web-control firmware')) {
        explanation = '미세 주입 펌웨어 확인 응답을 받지 못했습니다. 업로드 후 실행 중인 수집기를 다시 시작해 주세요.';
      } else if (rawError.includes('baseline timed out')) {
        explanation = '펌프 시작 전 초기색 수집 시간이 초과되었습니다. 카메라 영상과 ROI 고정을 확인해 주세요.';
      } else if (rawError.includes('model_unavailable') || rawError.includes('model validation failed')) {
        explanation = '자동정지용 모델을 사용할 수 없습니다. 실험 종료 후 농도 계산용 모델과는 별도입니다.';
      }
      const message = explanation ? `${explanation} (${rawError})` : rawError;
      setText('csvStateLabel', `${csvOperationFailureLabel(path)} · ${message}`);
      throw new Error(message);
    }
    if (payload.roi) applyRoiStatus(payload.roi);
    if (path.endsWith('/start')) pumpStopCsvSessionKey = '';
    applyCsvStatus(payload.csv, { source: 'post' });
    if (payload.pump) applyPumpCommandStatus(payload.pump);
    return payload.csv;
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    if (requestSequence !== csvControlSequence) return null;
    throw error;
  }
}


function shouldApplyPumpHealthLabel(pump) {
  const current = $('pumpCommandStatus')?.textContent || '';
  if (!pump?.connected) return true;
  return !/(주입 중|되감기|펌프 정지|전송)/.test(current);
}

function pumpHealthLabel(pump) {
  if (!pump) return '대기';
  if (pump.connected) {
    const command = pump.last_command ? ` · 마지막 ${pump.last_command}` : '';
    return `연결됨 · ${pump.port || 'COM'}${command}`;
  }
  if (pump.likely_busy) return '포트 사용 중 · IDE 닫기';
  if (pump.status === 'waiting_for_port') return '자동재시도 · USB 대기';
  if (pump.status === 'error' || pump.status === 'busy') return `연결 실패 · ${pump.message || pump.last_error || '-'}`;
  if (pump.auto_retry) return '자동재시도 중';
  return '대기';
}

function pumpCommandLabel(pump) {
  if (!pump) return '대기';
  const command = pump.command ? String(pump.command) : '-';
  if (pump.status === 'disabled') return `미설정 · ${command}`;
  if (pump.status === 'error') return `오류 · ${pump.error || command}`;
  const guardSeconds = parseFiniteNumber(pump.absolute_guard?.absolute_guard_effective_maximum_run_time_s);
  const guardSuffix = Number.isFinite(guardSeconds) ? ` · 최대 ${guardSeconds.toFixed(1)}초` : '';
  if (pump.action === 'start') return `주입 중 · ${command}${guardSuffix}`;
  if (pump.action === 'retract') return `되감기 · ${command}${guardSuffix}`;
  if (pump.action === 'stop') return `펌프 정지 · ${command}`;
  return pump.sent ? `전송 · ${command}` : '대기';
}

function applyPumpCommandStatus(pump) {
  setText('pumpCommandStatus', pumpCommandLabel(pump));
  if (pump?.status === 'disabled') {
    setText('previewStatus', '펌프 포트 미설정 · CSV만 기록합니다');
  } else if (pump?.status === 'error') {
    setText('previewStatus', `펌프 명령 실패 · ${pump.error || pump.message || pump.command || '-'}`);
  }
}

function updatePumpCommandButtons() {
  const motionBlocked = Boolean(
    pumpMotionInFlight || pumpStopInFlight || csvStartInFlight || csvStopInFlight,
  );
  const dispenseButton = $('serialPumpDispenseButton');
  const retractButton = $('serialPumpRetractButton');
  const stopButton = $('serialPumpStopButton');
  if (dispenseButton) dispenseButton.disabled = motionBlocked;
  if (retractButton) retractButton.disabled = motionBlocked;
  if (stopButton) stopButton.disabled = false;
}

function sendPumpCommand(path, pendingText) {
  const requestBackendRevision = backendRevision;
  const isStop = path.endsWith('/stop');
  if (isStop && pumpStopInFlight) return pumpStopInFlight;
  if (isStop && (csvStartInFlight || csvStopInFlight)) csvControlSequence += 1;
  if (!isStop && (csvStartInFlight || csvStopInFlight)) return Promise.resolve(null);
  if (!isStop && pumpStopInFlight) return Promise.resolve(null);
  if (!isStop && pumpMotionInFlight) {
    return path === pumpMotionPath ? pumpMotionInFlight : Promise.resolve(null);
  }

  const requestSequence = ++pumpCommandSequence;
  if (!isStop) pumpStopCsvSessionKey = '';
  setText('pumpCommandStatus', pendingText);
  const safetyPayload = isStop ? {} : { manual_unbounded: true };
  const request = (async () => {
    try {
      const response = await fetch(endpoint(path), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(safetyPayload),
      });
      const payload = await response.json().catch(() => ({}));
      if (requestSequence !== pumpCommandSequence || requestBackendRevision !== backendRevision) return null;
      if (payload.pump) applyPumpCommandStatus(payload.pump);
      if (!response.ok || payload.ok === false) {
        throw new Error(payload.error || payload.pump?.error || `펌프 API ${response.status}`);
      }
      if (isStop) pumpStopCsvSessionKey = csvSessionDownloadKey(latestCsvStatus);
      return payload.pump;
    } catch (error) {
      if (requestSequence !== pumpCommandSequence || requestBackendRevision !== backendRevision) return null;
      throw error;
    }
  })();

  if (isStop) pumpStopInFlight = request;
  else {
    pumpMotionInFlight = request;
    pumpMotionPath = path;
  }
  updatePumpCommandButtons();
  request.finally(() => {
    if (isStop && pumpStopInFlight === request) pumpStopInFlight = null;
    if (!isStop && pumpMotionInFlight === request) {
      pumpMotionInFlight = null;
      pumpMotionPath = '';
    }
    updatePumpCommandButtons();
  }).catch(() => {});
  return request;
}

function startCsvRecording() {
  if (csvStartInFlight) return csvStartInFlight;
  if (csvStopInFlight) return csvStopInFlight;
  setAppMode('csv');
  stopAutoRoiSetup();
  if (!latestRoiRecordable || !latestRoiComplete) {
    setText('csvStateLabel', 'ROI 고정 필요');
    setText('previewStatus', '두 ROI를 잡고 ROI 고정을 누르세요');
    return Promise.resolve(null);
  }
  const requestSequence = ++csvControlSequence;
  setText('pumpCommandStatus', '녹화 시작 → b');
  let body;
  try {
    body = remoteControlMode ? {} : buildPumpTimelineStartPayload();
  } catch (error) {
    setText('csvStateLabel', `녹화 시작 실패 · ${error.message}`);
    setText('pumpCommandStatus', `녹화 시작 실패 · ${error.message}`);
    return Promise.resolve(null);
  }
  const request = postCsvControl(
    '/api/csv/start',
    '시작 중',
    body,
    requestSequence,
  ).catch((error) => {
    if (requestSequence === csvControlSequence) {
      setText('csvStateLabel', `녹화 시작 실패 · ${error.message}`);
      setText('pumpCommandStatus', `녹화 시작 실패 · ${error.message}`);
    }
    return null;
  });
  csvStartInFlight = request;
  updateCsvControlButtons();
  updatePumpCommandButtons();
  request.finally(() => {
    if (csvStartInFlight === request) csvStartInFlight = null;
    updateCsvControlButtons();
    updatePumpCommandButtons();
  });
  return request;
}

function completeCsvStop(csv) {
  if (csv?.state === 'stopped') {
    triggerCsvAutoDownload();
    setAppMode('calculator');
  }
  return csv;
}

function stopCsvRecording() {
  if (csvStopInFlight) return csvStopInFlight;
  pumpCommandSequence += 1;
  const requestSequence = ++csvControlSequence;
  setText('pumpCommandStatus', '녹화 종료 → c');
  const request = postCsvControl('/api/csv/stop', '종료 중', {}, requestSequence)
    .then(completeCsvStop)
    .catch((error) => {
      if (requestSequence === csvControlSequence) {
        setText('csvStateLabel', `녹화 종료 실패 · ${error.message}`);
        setText('pumpCommandStatus', `녹화 종료 실패 · ${error.message}`);
      }
      return null;
    });
  csvStopInFlight = request;
  updateCsvControlButtons();
  updatePumpCommandButtons();
  request.finally(() => {
    if (csvStopInFlight === request) csvStopInFlight = null;
    updateCsvControlButtons();
    updatePumpCommandButtons();
  });
  return request;
}

async function refreshCsvStatus() {
  const requestBackendRevision = backendRevision;
  try {
    const response = await fetch(endpoint('/api/csv/status'), { cache: 'no-store' });
    if (requestBackendRevision !== backendRevision) return null;
    const payload = await response.json();
    if (requestBackendRevision !== backendRevision) return null;
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `CSV API ${response.status}`);
    applyCsvStatus(payload.csv, { source: 'get' });
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    setText('csvPathLabel', `CSV 대기 · ${error.message}`);
  }
}

function imagePointFromEvent(image, event) {
  const geometry = imageDrawGeometry(image);
  if (!geometry) return null;
  const { rect, naturalWidth, naturalHeight, drawnWidth, drawnHeight, offsetX, offsetY } = geometry;
  const clientX = event.clientX ?? event.touches?.[0]?.clientX;
  const clientY = event.clientY ?? event.touches?.[0]?.clientY;
  const localX = clientX - rect.left - offsetX;
  const localY = clientY - rect.top - offsetY;
  if (localX < 0 || localY < 0 || localX > drawnWidth || localY > drawnHeight) return null;
  return {
    x: Math.round((localX / drawnWidth) * naturalWidth),
    y: Math.round((localY / drawnHeight) * naturalHeight),
  };
}

function imageDrawGeometry(image) {
  if (!image) return null;
  const rect = image.getBoundingClientRect();
  const naturalWidth = image.naturalWidth || image.clientWidth;
  const naturalHeight = image.naturalHeight || image.clientHeight;
  if (!rect.width || !rect.height || !naturalWidth || !naturalHeight) return null;

  const imageAspect = naturalWidth / naturalHeight;
  const rectAspect = rect.width / rect.height;
  let drawnWidth = rect.width;
  let drawnHeight = rect.height;
  let offsetX = 0;
  let offsetY = 0;
  if (rectAspect > imageAspect) {
    drawnWidth = rect.height * imageAspect;
    offsetX = (rect.width - drawnWidth) / 2;
  } else {
    drawnHeight = rect.width / imageAspect;
    offsetY = (rect.height - drawnHeight) / 2;
  }
  return { rect, naturalWidth, naturalHeight, drawnWidth, drawnHeight, offsetX, offsetY };
}

function rectFromPoints(a, b) {
  const x = Math.min(a.x, b.x);
  const y = Math.min(a.y, b.y);
  return {
    x,
    y,
    width: Math.max(1, Math.abs(b.x - a.x)),
    height: Math.max(1, Math.abs(b.y - a.y)),
  };
}

function parseRoiString(value) {
  const parts = String(value || '').split(',').map((part) => Number(part.trim()));
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) return null;
  const [x, y, width, height] = parts;
  if (width <= 0 || height <= 0) return null;
  return { x, y, width, height };
}

function updateRoiOverlay(imageId, overlayId, roiValue, { locked = false, draft = false } = {}) {
  const image = $(imageId);
  const overlay = $(overlayId);
  const roi = typeof roiValue === 'string' ? parseRoiString(roiValue) : roiValue;
  const geometry = imageDrawGeometry(image);
  if (!overlay || !roi || !geometry) {
    if (overlay) overlay.style.display = 'none';
    return;
  }
  const scaleX = geometry.drawnWidth / geometry.naturalWidth;
  const scaleY = geometry.drawnHeight / geometry.naturalHeight;
  overlay.style.display = 'block';
  overlay.style.left = `${geometry.offsetX + roi.x * scaleX}px`;
  overlay.style.top = `${geometry.offsetY + roi.y * scaleY}px`;
  overlay.style.width = `${Math.max(2, roi.width * scaleX)}px`;
  overlay.style.height = `${Math.max(2, roi.height * scaleY)}px`;
  overlay.classList.toggle('is-locked', Boolean(locked));
  overlay.classList.toggle('is-draft', Boolean(draft));
}

function hideRoiOverlay(overlayId) {
  const overlay = $(overlayId);
  if (!overlay) return;
  overlay.style.display = 'none';
  overlay.classList.remove('is-locked', 'is-draft');
}

function roiStatusIsDrafting() {
  return Boolean(roiDrag || window.AutoTitrationRoiDraftActive);
}


function refreshRoiOverlays() {
  if (roiStatusIsDrafting()) return;
  // Size the frame to the video instead of letterboxing it into a short panel.
  for (const image of [$('visiblePreview'), $('thermalPreview')]) {
    const frame = image?.closest('.camera-frame');
    if (frame && image.naturalWidth > 0 && image.naturalHeight > 0) {
      const ratio = `${image.naturalWidth} / ${image.naturalHeight}`;
      if (frame.style.aspectRatio !== ratio) frame.style.aspectRatio = ratio;
    }
  }
  updateRoiOverlay('visiblePreview', 'visibleRoiOverlay', latestLiveMetadata.visible_roi, { locked: latestRoiLocked });
  const thermalImage = $('thermalPreview');
  if (thermalImage?.dataset.placeholder === 'true') {
    hideRoiOverlay('thermalRoiOverlay');
  } else {
    updateRoiOverlay('thermalPreview', 'thermalRoiOverlay', latestLiveMetadata.thermal_roi, { locked: latestRoiLocked });
  }
}



async function sendRoiRect(target, rect) {
  const requestBackendRevision = backendRevision;
  setText('previewStatus', `${target} ROI 저장 중 · ${rect.x},${rect.y},${rect.width},${rect.height}`);
  if (target === 'visible') {
    showVisibleCandidateNotice(
      'waiting',
      '카메라 ROI 저장 중',
      `${rect.x},${rect.y},${rect.width},${rect.height}`,
    );
  }
  const response = await fetch(endpoint('/api/roi-rect'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ target, ...rect }),
  });
  const payload = await response.json().catch(() => ({}));
  if (requestBackendRevision !== backendRevision) return null;
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `ROI API 오류 ${response.status}`);
  }
  if (payload.roi) applyRoiStatus(payload.roi);
  setText('previewStatus', `${target} ROI 저장 · ${payload.roi_rect || `${rect.x},${rect.y},${rect.width},${rect.height}`}`);
  if (target === 'visible') {
    showVisibleCandidateNotice(
      'success',
      '카메라 ROI 저장',
      `${payload.roi_rect || `${rect.x},${rect.y},${rect.width},${rect.height}`}`,
    );
  }
}

async function postRoiAction(path, body = {}, pendingText = 'ROI 처리 중') {
  const requestBackendRevision = backendRevision;
  setText('roiSettingsStatus', pendingText);
  const response = await fetch(endpoint(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (requestBackendRevision !== backendRevision) return null;
  if (!response.ok || payload.ok === false) throw new Error(payload.error || `ROI API ${response.status}`);
  if (payload.roi) applyRoiStatus(payload.roi);
  return payload;
}

function roiStateLabel(state) {
  return {
    setup: '설정',
    locked: '고정',
    recording: '녹화',
    stopped: '종료',
  }[state] || state || '대기';
}

function applyRoiStatus(data = {}) {
  if (typeof window.AutoTitrationShouldIgnoreRoiStatus === 'function' && window.AutoTitrationShouldIgnoreRoiStatus(data)) return;
  latestRoiLocked = Boolean(data.roi_locked);
  latestRoiComplete = Boolean(data.roi_complete ?? (data.visible_roi_ready && data.thermal_roi_ready));
  latestRoiRecordable = Boolean(data.roi_recordable ?? (latestRoiLocked && latestRoiComplete && data.roi_state !== 'recording'));
  latestLiveMetadata = { ...latestLiveMetadata, ...data };
  if (latestRoiLocked || data.roi_state === 'recording') stopAutoRoiSetup();
  const statusText = latestRoiLocked
    ? 'ROI 고정'
    : latestRoiComplete
      ? 'ROI 준비'
      : 'ROI 설정';
  setText(
    'roiSettingsStatus',
    `${statusText}${data.roi_error ? ` · ${data.roi_error}` : ''}`,
  );
  updateRoiButtons(data);
  if (roiStatusIsDrafting()) return;
  refreshRoiOverlays();
}

function updateRoiButtons(data = latestLiveMetadata) {
  const state = data.roi_state || 'setup';
  const recording = state === 'recording';
  const locked = Boolean(data.roi_locked);
  const complete = Boolean(data.roi_complete ?? latestRoiComplete);
  const editable = Boolean(data.roi_editable ?? (!locked && !recording));
  const recordable = Boolean(data.roi_recordable ?? (locked && complete && !recording));
  const setupButton = $('roiSetupButton');
  const autoSetupButton = $('roiAutoSetupButton');
  const lockButton = $('roiLockButton');
  const unlockButton = $('roiUnlockButton');
  const resetButton = $('roiResetButton');
  const startButton = $('csvStartButton');
  if (setupButton) setupButton.disabled = recording;
  if (autoSetupButton) autoSetupButton.disabled = recording || locked;
  if (lockButton) lockButton.disabled = recording || locked || !complete;
  if (unlockButton) unlockButton.disabled = recording || !locked;
  if (resetButton) resetButton.disabled = recording;
  if (startButton) startButton.disabled = recording || !recordable || !complete;
}

function updateAutoRoiSetupButton() {
  const button = $('roiAutoSetupButton');
  if (!button) return;
  button.textContent = `자동 ROI ${autoRoiSetupEnabled ? 'ON' : 'OFF'}`;
  button.setAttribute('aria-pressed', autoRoiSetupEnabled ? 'true' : 'false');
  button.classList.toggle('is-active', autoRoiSetupEnabled);
}

function stopAutoRoiSetup() {
  autoRoiSetupEnabled = false;
  if (autoRoiSetupTimer) {
    window.clearTimeout(autoRoiSetupTimer);
    autoRoiSetupTimer = null;
  }
  updateAutoRoiSetupButton();
}

function scheduleAutoRoiCandidate(delayMs = AUTO_ROI_RETRY_MS) {
  if (!autoRoiSetupEnabled || autoRoiSetupTimer) return;
  autoRoiSetupTimer = window.setTimeout(() => {
    autoRoiSetupTimer = null;
    requestAutoRoiCandidate();
  }, Math.max(0, Number(delayMs) || 0));
}

function autoRoiFailureUsesMissingYolo(reason = '') {
  return /yolo_(?:model|runtime)_unavailable|requires ultralytics/i.test(String(reason));
}

async function requestAutoRoiCandidate() {
  const requestBackendRevision = backendRevision;
  if (!autoRoiSetupEnabled || autoRoiRequestInFlight) return;
  if (latestRoiLocked || latestLiveMetadata.roi_state === 'recording') {
    stopAutoRoiSetup();
    return;
  }
  autoRoiRequestInFlight = true;
  setText('roiSettingsStatus', '자동 ROI 찾는 중');
  try {
    const visibleWasReady = Boolean(latestLiveMetadata.visible_roi_ready);
    const thermalWasReady = Boolean(latestLiveMetadata.thermal_roi_ready);
    let target = 'both';
    if (visibleWasReady && !thermalWasReady) {
      target = 'thermal';
    } else if (thermalWasReady && !visibleWasReady) {
      target = 'visible';
    }
    const payload = await postRoiAction('/api/roi-auto-candidate', { target }, '자동 ROI 찾는 중');
    if (requestBackendRevision !== backendRevision) return null;
    const roi = payload.roi || {};
    const visibleReady = Boolean(roi.visible_roi_ready);
    const thermalReady = Boolean(roi.thermal_roi_ready);
    const reason = String(payload.reason || '');
    if (visibleReady && thermalReady) {
      stopAutoRoiSetup();
      setText('previewStatus', '두 ROI 자동 설정 완료 · 확인 후 ROI 고정');
      setText('roiSettingsStatus', '자동 ROI 완료');
      showVisibleCandidateNotice('success', '자동 ROI 완료', '두 영역을 확인한 뒤 ROI 고정을 누르세요');
      return;
    }
    if (autoRoiFailureUsesMissingYolo(reason)) {
      stopAutoRoiSetup();
      const message = thermalReady
        ? '열화상 ROI는 설정됨 · 카메라 ROI는 직접 드래그'
        : 'YOLO가 없어 카메라 ROI는 직접 드래그';
      setText('previewStatus', message);
      setText('roiSettingsStatus', '자동 ROI 일부만 완료');
      showVisibleCandidateNotice('waiting', '카메라 ROI 수동 선택', message);
      return;
    }
    const waitingForFrame = /queued_waiting_for_/i.test(reason);
    setText(
      'roiSettingsStatus',
      waitingForFrame ? '자동 ROI · 카메라 연결 대기' : '자동 ROI · 대상을 화면 중앙에 놓으세요',
    );
    scheduleAutoRoiCandidate(waitingForFrame ? 650 : AUTO_ROI_RETRY_MS);
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    stopAutoRoiSetup();
    setText('previewStatus', `자동 ROI 실패 · ${error.message}`);
    setText('roiSettingsStatus', '수동 ROI를 사용하세요');
    showVisibleCandidateNotice('error', '자동 ROI 실패', error.message);
  } finally {
    if (requestBackendRevision === backendRevision) autoRoiRequestInFlight = false;
  }
}

async function toggleAutoRoiSetup() {
  const requestBackendRevision = backendRevision;
  if (autoRoiSetupEnabled) {
    stopAutoRoiSetup();
    setText('roiSettingsStatus', '자동 ROI OFF · 직접 드래그');
    return;
  }
  if (latestLiveMetadata.roi_state === 'recording') {
    setText('previewStatus', '녹화 중 자동 ROI 사용 불가');
    return;
  }
  const ready = await enterRoiSetupMode();
  if (requestBackendRevision !== backendRevision) return null;
  if (!ready) return;
  autoRoiSetupEnabled = true;
  updateAutoRoiSetupButton();
  setText('previewStatus', '자동 ROI 설정 중 · 비커를 화면에 놓으세요');
  await requestAutoRoiCandidate();
  if (requestBackendRevision !== backendRevision) return null;
}

async function enterRoiSetupMode({ reset = false } = {}) {
  const requestBackendRevision = backendRevision;
  if (latestLiveMetadata.roi_state === 'recording') {
    setText('previewStatus', '녹화 중 ROI 변경 불가');
    return false;
  }
  roiSetupMode = true;
  const state = latestLiveMetadata.roi_state || 'setup';
  const needsServerUnlock = state !== 'setup' || latestRoiLocked;
  if (needsServerUnlock) {
    try {
      await postRoiAction('/api/roi-unlock', { reset }, reset ? 'ROI 재설정' : 'ROI 선택');
      if (requestBackendRevision !== backendRevision) return null;
      if (reset) {
        latestLiveMetadata.visible_roi = '';
        latestLiveMetadata.thermal_roi = '';
        refreshRoiOverlays();
      }
    } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
      setText('roiSettingsStatus', `ROI 선택 실패 · ${error.message}`);
      return false;
    }
  }
  try {
    await setRoiAutoTracking('off', { updateStatus: false });
    if (requestBackendRevision !== backendRevision) return null;
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    setText('roiSettingsStatus', `자동추적 끄기 실패 · ${error.message}`);
  }
  setText('previewStatus', 'ROI 선택 · 두 화면에서 드래그');
  setText('roiSettingsStatus', 'ROI 선택');
  updateRoiButtons({ ...latestLiveMetadata, roi_state: 'setup', roi_locked: false, roi_editable: true });
  return true;
}

function syncSettingsControls(settings, { updateStatus = true } = {}) {
  if (!settings || settingsDirty) return;
  if (Object.prototype.hasOwnProperty.call(settings, 'thermal_rotation_degrees')) {
    updateMini2RotateButton(settings.thermal_rotation_degrees);
  }
  if (updateStatus) {
    setText('roiSettingsStatus', 'ROI 선택');
  }
}

function scheduleChemistryConstantsLookup(delayMs = 450) {
  if (constantsLookupTimer) {
    window.clearTimeout(constantsLookupTimer);
    constantsLookupTimer = null;
  }
  const query = readTextInput('sampleSubstanceInput');
  selectedConstantsCandidate = null;
  constantsSelectionMode = '';
  latestConstantsLookup = null;
  const candidateSelect = $('constantsCandidateSelect');
  if (candidateSelect) {
    candidateSelect.innerHTML = query ? '<option value="">자동 조회 중</option>' : '<option value="">시료 물질 입력</option>';
    candidateSelect.disabled = true;
  }
  setText('constantsLookupStatus', query ? '자동 조회 대기' : '시료 입력 대기');
  if (!query) return;
  constantsLookupTimer = window.setTimeout(() => {
    constantsLookupTimer = null;
    lookupChemistryConstants({ silent: true });
  }, Math.max(0, Number(delayMs) || 0));
}

async function loadRoiSettings() {
  const requestBackendRevision = backendRevision;
  try {
    const response = await fetch(endpoint('/api/settings'), { cache: 'no-store' });
    if (requestBackendRevision !== backendRevision) return null;
    const payload = await response.json();
    if (requestBackendRevision !== backendRevision) return null;
    if (!response.ok || payload.ok === false) throw new Error(payload.error || `설정 API ${response.status}`);
    syncSettingsControls(payload.settings);
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    setText('roiSettingsStatus', `설정 연결 대기 · ${error.message}`);
  }
}

async function setRoiAutoTracking(mode, { updateStatus = false, pendingText = '' } = {}) {
  const requestBackendRevision = backendRevision;
  const requestedAutoMode = 'off';
  if (pendingText) setText('roiSettingsStatus', pendingText);
  const response = await fetch(endpoint('/api/settings'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      roi_auto_detect: requestedAutoMode,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (requestBackendRevision !== backendRevision) return null;
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `설정 API 오류 ${response.status}`);
  }
  syncSettingsControls(payload.settings, { updateStatus });
  return payload.settings;
}

function thermalRotationDegreesFrom(data = latestLiveMetadata) {
  return Number(data?.thermal_rotation_degrees) === 180 ? 180 : 0;
}

function updateMini2RotateButton(degrees = thermalRotationDegreesFrom()) {
  const button = $('mini2RotateButton');
  if (!button || isAndroidWebViewBridge()) return;
  const normalized = Number(degrees) === 180 ? 180 : 0;
  const label = normalized === 180 ? '적외선 0° 복귀' : '적외선 180° 회전';
  button.dataset.rotation = String(normalized);
  button.title = label;
  button.setAttribute('aria-label', label);
  const labelSlot = button.querySelector('[data-rotate-label]');
  if (labelSlot) {
    labelSlot.textContent = label;
  } else if (!button.querySelector('svg')) {
    button.textContent = label;
  }
}

async function setThermalRotationDegrees(degrees, { resetRoi = true } = {}) {
  const requestBackendRevision = backendRevision;
  const rotation = Number(degrees) === 180 ? 180 : 0;
  const response = await fetch(endpoint('/api/settings'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ thermal_rotation_degrees: rotation }),
  });
  const payload = await response.json().catch(() => ({}));
  if (requestBackendRevision !== backendRevision) return null;
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `설정 API 오류 ${response.status}`);
  }
  latestLiveMetadata = { ...latestLiveMetadata, ...(payload.settings || {}) };
  syncSettingsControls(payload.settings, { updateStatus: false });
  if (resetRoi) {
    await enterRoiSetupMode({ reset: true });
    if (requestBackendRevision !== backendRevision) return null;
  }
  return rotation;
}

async function toggleMini2Rotation() {
  const requestBackendRevision = backendRevision;
  if (latestLiveMetadata.roi_state === 'recording') {
    setText('previewStatus', '녹화 중 회전 불가');
    return;
  }
  const next = thermalRotationDegreesFrom() === 180 ? 0 : 180;
  setText('previewStatus', `적외선 ${next}° 적용 중`);
  try {
    const applied = await setThermalRotationDegrees(next, { resetRoi: true });
    if (requestBackendRevision !== backendRevision) return null;
    updateMini2RotateButton(applied);
    setText('previewStatus', `적외선 ${applied}° 적용 · ROI 재고정`);
    setText('roiSettingsStatus', '적외선 회전 · ROI 재선택');
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    setText('previewStatus', `적외선 회전 실패 · ${error.message}`);
  }
}

async function applyRoiSettings(event) {
  const requestBackendRevision = backendRevision;
  if (event) event.preventDefault();
  settingsDirty = true;
  setText('roiSettingsStatus', '자동추적 끄는 중');
  try {
    await setRoiAutoTracking('off', { updateStatus: true });
    if (requestBackendRevision !== backendRevision) return null;
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    setText('roiSettingsStatus', `설정 실패 · ${error.message}`);
  } finally {
    settingsDirty = false;
  }
}

function addRoiDragHandler(imageId, overlayId, target) {
  const image = $(imageId);
  if (!image) return;
  const hitElement = image.closest('.camera-frame') || image;
  hitElement.addEventListener('pointerdown', async (event) => {
    if (latestLiveMetadata.roi_state === 'recording') return;
    if (latestRoiLocked || latestLiveMetadata.roi_state === 'locked' || latestLiveMetadata.roi_state === 'stopped') {
      setText('previewStatus', 'ROI 선택 버튼을 누르세요');
      return;
    }
    if (!roiSetupMode || latestLiveMetadata.roi_state !== 'setup') {
      const ready = await enterRoiSetupMode();
      if (!ready) return;
    }
    stopAutoRoiSetup();
    const start = imagePointFromEvent(image, event);
    if (!start) {
      setText('previewStatus', `${target} 화면 안쪽 드래그`);
      return;
    }
    event.preventDefault();
    hitElement.setPointerCapture?.(event.pointerId);
    roiDrag = {
      imageId,
      overlayId,
      target,
      start,
      current: start,
      pointerId: event.pointerId,
    };
    updateRoiOverlay(imageId, overlayId, { x: start.x, y: start.y, width: 1, height: 1 }, { draft: true });
    setText('previewStatus', `${target} ROI 드래그 중`);
  });
  hitElement.addEventListener('pointermove', (event) => {
    if (!roiDrag || roiDrag.imageId !== imageId) return;
    const current = imagePointFromEvent(image, event);
    if (!current) return;
    roiDrag.current = current;
    const rect = rectFromPoints(roiDrag.start, current);
    updateRoiOverlay(imageId, overlayId, rect, { draft: true });
  });
  hitElement.addEventListener('pointerup', async (event) => {
    if (!roiDrag || roiDrag.imageId !== imageId) return;
    const requestBackendRevision = backendRevision;
    const drag = roiDrag;
    roiDrag = null;
    hitElement.releasePointerCapture?.(event.pointerId);
    const end = imagePointFromEvent(image, event) || drag.current;
    const rect = rectFromPoints(drag.start, end);
    try {
      if (rect.width < 3 || rect.height < 3) {
        setText('previewStatus', 'ROI가 너무 작습니다');
        hideRoiOverlay(overlayId);
        refreshRoiOverlays();
        return;
      }
      await sendRoiRect(target, rect);
      if (requestBackendRevision !== backendRevision) return;
      setText('roiSettingsStatus', `${target} ROI 저장`);
      refreshRoiOverlays();
    } catch (error) {
      if (requestBackendRevision !== backendRevision) return;
      setText('previewStatus', `ROI 저장 실패 · ${error.message}`);
      if (target === 'visible') {
        showVisibleCandidateNotice('error', 'ROI 저장 실패', error.message);
      }
      refreshRoiOverlays();
    }
  });
  hitElement.addEventListener('pointercancel', () => {
    roiDrag = null;
    refreshRoiOverlays();
  });
}



function withoutRoiGeometry(data = {}) {
  const clone = { ...data };
  delete clone.visible_roi;
  delete clone.thermal_roi;
  delete clone.visible_roi_shape;
  delete clone.thermal_roi_shape;
  delete clone.roi_source;
  delete clone.roi_state;
  delete clone.roi_locked;
  delete clone.roi_complete;
  delete clone.roi_recordable;
  delete clone.roi_editable;
  delete clone.visible_roi_ready;
  delete clone.thermal_roi_ready;
  return clone;
}

function applyLiveMetadata(data) {
  const ignoreRoiStatus = typeof window.AutoTitrationShouldIgnoreRoiStatus === 'function'
    && window.AutoTitrationShouldIgnoreRoiStatus(data);
  const effectiveData = ignoreRoiStatus ? withoutRoiGeometry(data) : data;
  latestLiveMetadata = { ...latestLiveMetadata, ...effectiveData };
  if (!ignoreRoiStatus) {
    latestRoiLocked = Boolean(effectiveData.roi_locked);
    latestRoiComplete = Boolean(effectiveData.roi_complete ?? (effectiveData.visible_roi && effectiveData.thermal_roi));
    applyRoiStatus(effectiveData);
  }
  const hasCelsius = hasTrustedCelsiusTemperature(data);
  if (hasCelsius) {
    setText('temperatureValue', formatNumber(data.temperature_avg_c, 1));
    setText('temperatureUnit', '℃');
    setText('temperatureMin', `${formatNumber(data.temperature_min_c, 1)} ℃`);
    setText('temperatureMax', `${formatNumber(data.temperature_max_c, 1)} ℃`);
    setText('temperatureDelta', `${formatNumber(data.temperature_delta_c, 2)} ℃`);
  } else {
    setText('temperatureValue', formatNumber(data.raw_avg, 0));
    setText('temperatureUnit', 'raw');
    setText('temperatureMin', formatNumber(data.raw_min, 0));
    setText('temperatureMax', formatNumber(data.raw_max, 0));
    setText('temperatureDelta', formatNumber(data.raw_delta, 0));
  }

  setText('rgbRValue', formatNumber(data.visible_R_mean, 1));
  setText('rgbGValue', formatNumber(data.visible_G_mean, 1));
  setText('rgbBValue', formatNumber(data.visible_B_mean, 1));
  setText('hsvHValue', formatNumber(data.visible_H_mean, 1));
  setText('hsvSValue', formatNumber(data.visible_S_mean, 3));
  setText('hsvVValue', formatNumber(data.visible_V_mean, 3));
  setText('hsvDeltaValue', formatNumber(data.visible_HSV_delta, 3));
  const hsvDeltaElement = $('hsvDeltaValue');
  if (hsvDeltaElement) {
    hsvDeltaElement.title = `ΔH ${formatNumber(data.visible_H_delta, 1)} / ΔS ${formatNumber(data.visible_S_delta, 3)} / ΔV ${formatNumber(data.visible_V_delta, 3)}`;
  }
  setText('rgbDeltaValue', formatNumber(data.visible_color_delta, 2));
  const csvAccepted = applyCsvStatus({
    row_count: data.csv_row_count,
    csv_rows_per_s: data.csv_rows_per_s,
    path: data.csv_path,
    updated_epoch_s: data.csv_updated_epoch_s,
    recording: data.csv_recording,
    finalizing: data.csv_finalizing,
    state: data.csv_state,
    session_id: data.csv_session_id,
    started_epoch_s: data.csv_recording_started_epoch_s ?? data.csv_started_epoch_s,
    pump_elapsed_s: data.pump_elapsed_s,
    pump_rate_ml_per_s: data.pump_run_rate_ml_per_s,
    injected_volume_ml: data.injected_volume_ml,
    theoretical_equivalence_volume_ml: data.theoretical_equivalence_volume_ml,
    theoretical_equivalence_time_s: data.theoretical_equivalence_time_s,
    distance_to_equivalence_ml: data.distance_to_equivalence_ml,
    time_to_equivalence_s: data.time_to_equivalence_s,
	    equivalence_window_ml: data.equivalence_window_ml,
	    equivalence_window_label: data.equivalence_window_label,
	    titration_type: data.titration_type,
	    sample_concentration_M: data.sample_concentration_M,
	    sample_volume_ml: data.sample_volume_ml,
	    sample_valence: data.sample_valence,
	    titrant_concentration_M: data.titrant_concentration_M,
	    titrant_valence: data.titrant_valence,
	    selected_pka_value: data.selected_pka_value,
	    selected_pkb_value: data.selected_pkb_value,
	    sample_concentration_from_injected_M: data.sample_concentration_from_injected_M,
	    sample_concentration_error_percent: data.sample_concentration_error_percent,
	    predicted_equivalence_volume_ml: data.predicted_equivalence_volume_ml,
	    sample_concentration_from_predicted_equivalence_M: data.sample_concentration_from_predicted_equivalence_M,
	    predicted_sample_concentration_error_percent: data.predicted_sample_concentration_error_percent,
	    theoretical_equivalence_pH: data.theoretical_equivalence_pH,
	    predicted_equivalence_pH: data.predicted_equivalence_pH,
	    predicted_equivalence_pH_warning: data.predicted_equivalence_pH_warning,
	    predicted_equivalence_status: data.predicted_equivalence_status,
	    predicted_equivalence_reason: data.predicted_equivalence_reason,
	    calculated_theoretical_equivalence_volume_ml: data.calculated_theoretical_equivalence_volume_ml,
	    sample_concentration_from_theoretical_equivalence_M: data.sample_concentration_from_theoretical_equivalence_M,
	    equivalence_formula: data.equivalence_formula,
	    csv_event_note: data.csv_event_note,
	    csv_mark_sequence: data.csv_mark_sequence,
	    recording_elapsed_s: data.csv_recording_elapsed_s,
	    auto_stop_enabled: data.auto_stop_enabled,
	    auto_stop_state: data.auto_stop_state,
	    auto_stop_reason: data.auto_stop_reason,
	    auto_stop_trigger_volume_ml: data.auto_stop_trigger_volume_ml,
	    auto_stop_pulse_enabled: data.auto_stop_pulse_enabled,
	    auto_stop_pulse_state: data.auto_stop_pulse_state,
	    auto_stop_pulse_reason: data.auto_stop_pulse_reason,
	    auto_stop_pulse_count: data.auto_stop_pulse_count,
	    auto_stop_slow_stage_enabled: data.auto_stop_slow_stage_enabled,
	    auto_stop_slow_rate_steps_per_s: data.auto_stop_slow_rate_steps_per_s,
	    auto_stop_slow_nominal_rate_ml_per_s: data.auto_stop_slow_nominal_rate_ml_per_s,
	    pump_dosing_stage: data.pump_dosing_stage,
	    pump_state: data.pump_state,
	    pump_nominal_rate_ml_per_s: data.pump_nominal_rate_ml_per_s,
	    pump_rate_basis: data.pump_rate_basis,
	  }, { source: 'live' });
  updateDemoLiveSample(data, csvAccepted);

  setText('statusLabel', data.status_label || '-');
  syncSettingsControls(data, { updateStatus: false });
  setText('thermalRoiLabel', `${effectiveData.thermal_roi || '-'} · ${roiStateLabel(effectiveData.roi_state)}`);
  setText('visibleRoiLabel', `${effectiveData.visible_roi || '-'} · session ${effectiveData.roi_session_id || 0}`);
  setText('syncQuality', data.sync_quality || '-');
  setText('visibleState', data.visible_capture_index === '' ? 'thermal only' : `camera ${data.visible_capture_index}`);
  if (data.constants_source_id || data.selected_pka_value) {
    setText(
      'constantsLookupStatus',
      `${data.constants_source_id || data.constants_query || '-'} · ${formatNumber(data.selected_pka_value, 3)}`,
    );
  }
  if (data.indicator) setText('indicatorModelLabel', `${data.indicator} · ${selectedIndicatorLabel()}`);
  if (data.activity_warning || data.ionic_strength_label) {
    setText('activityWarningLabel', data.ionic_strength_label || data.activity_warning || '실시간 계산 안 함');
  }

  if (data.frame_id === null || data.sync_quality === 'waiting') {
    setText('previewStatus', '대기');
    return;
  }

  lastFrameAt = Date.now();
  const eventEpoch = Number(data.stream_updated_epoch_s || data.updated_epoch_s || 0);
  const eventAgeMs = eventEpoch > 0 ? Date.now() - eventEpoch * 1000 : Number.NaN;
  const mini2Ms = Number(data.latency_thermal_stream_age_ms ?? data.latency_mini2_age_ms ?? data.processing_latency_ms);
  const visibleMs = Number(data.latency_visible_stream_age_ms ?? data.latency_visible_age_ms ?? data.preview_visible_latency_ms);
  const roiMs = Number(data.roi_result_age_ms);
  const syncMs = Number(data.latency_sync_offset_ms ?? data.sync_offset_ms);
  const delayCandidates = [eventAgeMs, mini2Ms, visibleMs].filter(Number.isFinite);
  const delayMs = delayCandidates.length ? Math.max(...delayCandidates) : Number.NaN;
  setText('latencyOverallValue', formatMs(delayMs));
  setText('latencyEventAgeValue', formatMs(eventAgeMs));
  setText('latencyMini2Value', formatMs(mini2Ms));
  setText('latencyVisibleValue', formatMs(visibleMs));
  setText('latencyRoiValue', formatMs(roiMs));
  setText('latencySyncValue', formatSignedMs(syncMs));
  refreshRoiOverlays();
  const captureFps = parseFiniteNumber(data.mini2_capture_fps);
  const recordingBacklog = Math.max(0, Number(data.mini2_recording_backlog_frames) || 0);
  const recordingDrops = Math.max(0, Number(data.mini2_recording_dropped_frames) || 0);
  const captureStatus = Number.isFinite(captureFps) ? ` · ${captureFps.toFixed(1)} fps` : '';
  const backlogStatus = recordingBacklog > 0 ? ` · 처리 대기 ${recordingBacklog}` : '';
  const dropStatus = recordingDrops > 0 ? ` · 기록 누락 ${recordingDrops}` : '';
  const previewDetail = `frame ${data.frame_id ?? '-'}${captureStatus}${backlogStatus}${dropStatus}`;
  const previewLabel = $('previewStatus');
  if (previewLabel) previewLabel.title = previewDetail;
  setText(
    'previewStatus',
    `영상 연결${recordingBacklog > 0 ? ' · 저장 처리 중' : ''}${dropStatus}${latestRoiRecordable ? '' : ' · ROI 설정 필요'}`,
  );
}

function connectLiveStream() {
  setPreviewSources();
  if (liveEvents) {
    liveEvents.close();
    liveEvents = null;
  }

  setWaiting('스트림 연결 중');
  setDemoConnection('connecting');
  lastFrameAt = 0;
  let events;
  try {
    events = new EventSource(endpoint('/stream/events'));
  } catch (error) {
    setWaiting(`스트림 주소 오류 · ${error.message}`);
    setBackendBaseStatus(`연결 실패: ${backendBaseDisplay()}`);
    setDemoConnection('disconnected');
    return;
  }
  liveEvents = events;
  setBackendBaseStatus(`연결 중: ${backendBaseDisplay()}`);
  events.addEventListener('live', (event) => {
    if (events !== liveEvents) return;
    try {
      clearLocalBackendFailover();
      applyLiveMetadata(JSON.parse(event.data));
      setBackendBaseStatus(`연결됨: ${backendBaseDisplay()}`);
    } catch (error) {
      setWaiting(`메타데이터 오류 · ${error.message}`);
    }
  });
  events.onerror = () => {
    if (events !== liveEvents) return;
    setDemoConnection('disconnected');
    scheduleLocalBackendFailover(events);
    const staleMs = lastFrameAt ? Date.now() - lastFrameAt : Infinity;
    setWaiting(staleMs > 2500 ? '프레임 멈춤' : '재연결 중');
    setBackendBaseStatus(`재연결 대기: ${backendBaseDisplay()}`);
  };
}

function saveBackendBase(event) {
  if (event) event.preventDefault();
  const input = $('backendBaseInput');
  try {
    const nextBackendBase = normalizeBackendBase(input?.value || defaultBackendBase());
    const backendChanged = nextBackendBase !== liveStreamBase;
    liveStreamBase = nextBackendBase;
    latestCsvStatus = null;
    latestCsvStatusSource = '';
    if (backendChanged) resetDemoViewForBackend();
    if (input) input.value = liveStreamBase || '.';
    writeStoredBackendBase(liveStreamBase);
    setBackendBaseStatus(`저장됨: ${backendBaseDisplay()}`);
    connectLiveStream();
    loadRoiSettings();
    refreshCsvStatus();
  } catch (error) {
    setBackendBaseStatus(`주소 오류 · ${error.message}`);
  }
}

function setupBackendControls() {
  const form = $('backendForm');
  const input = $('backendBaseInput');
  const button = $('saveBackendBaseButton');
  if (input) input.value = liveStreamBase || '.';
  if (form) form.addEventListener('submit', saveBackendBase);
  if (button && !form) button.addEventListener('click', saveBackendBase);
  if (isAndroidWebViewBridge()) {
    setBackendBaseStatus('백엔드: Android WebView bridge');
  } else {
    setPreviewSources();
  }
}

function addStreamErrorHandlers() {
  const visible = $('visiblePreview');
  if (visible) {
    visible.addEventListener('error', () => {
      visible.dataset.streamState = 'error';
      setText('visibleState', '카메라 대기');
      setBackendBaseStatus(`이미지 연결 대기: ${backendBaseDisplay()}`);
      scheduleLocalBackendFailover(liveEvents);
    });
    visible.addEventListener('load', () => {
      visible.dataset.streamState = 'load';
      refreshRoiOverlays();
      if (!lastFrameAt) setText('visibleState', '카메라 수신');
    });
  }

  const thermal = $('thermalPreview');
  if (thermal) {
    thermal.addEventListener('error', () => {
      thermal.dataset.streamState = 'error';
      setText('syncQuality', '적외선 대기');
      setBackendBaseStatus(`이미지 연결 대기: ${backendBaseDisplay()}`);
      scheduleLocalBackendFailover(liveEvents);
    });
    thermal.addEventListener('load', () => {
      thermal.dataset.streamState = 'load';
      refreshRoiOverlays();
      if (!lastFrameAt) setText('syncQuality', '열화상 스트림 수신 중');
    });
  }
}

function addModeHandlers() {
  const csvButton = $('csvCollectionModeButton');
  const calculatorButton = $('concentrationCalculationModeButton');

  if (csvButton) csvButton.addEventListener('click', () => setAppMode('csv'));
  if (calculatorButton) calculatorButton.addEventListener('click', () => setAppMode('calculator'));
  setAppMode(currentAppMode);
}

function addCsvRecordingHandlers() {
  const startButton = $('csvStartButton');
  const stopButton = $('csvStopButton');
  const dispenseButton = $('serialPumpDispenseButton');
  const retractButton = $('serialPumpRetractButton');
  const pumpStopButton = $('serialPumpStopButton');
  const form = $('pumpTimelineForm');
  if (form) form.addEventListener('submit', (event) => event.preventDefault());
  if (startButton) startButton.addEventListener('click', startCsvRecording);
  if (stopButton) stopButton.addEventListener('click', stopCsvRecording);
  if (dispenseButton) {
    dispenseButton.addEventListener('click', async () => {
      try {
        await sendPumpCommand('/api/pump/dispense', '펌프 주입 → b');
      } catch (error) {
        setText('pumpCommandStatus', `펌프 주입 실패 · ${error.message}`);
      }
    });
  }
  if (retractButton) {
    retractButton.addEventListener('click', async () => {
      try {
        await sendPumpCommand('/api/pump/retract', '펌프 되감기 → a');
      } catch (error) {
        setText('pumpCommandStatus', `펌프 되감기 실패 · ${error.message}`);
      }
    });
  }
  if (pumpStopButton) {
    pumpStopButton.addEventListener('click', async () => {
      try {
        await sendPumpCommand('/api/pump/stop', '펌프 정지 → c');
      } catch (error) {
        setText('pumpCommandStatus', `정지 실패 · ${error.message}`);
      }
    });
  }
}

function addChemistryHandlers() {
  const form = $('chemistryModelForm');
  const titrationSelect = $('titrationTypeSelect');
  const sampleInput = $('sampleSubstanceInput');
  const indicatorSelect = $('indicatorSelect');
  const calculationInputIds = [
    'sampleConcentrationInput',
    'sampleVolumeInput',
    'standardConcentrationInput',
    'theoryEquivalenceInput',
    'pumpRateInput',
  ];
  if (form) form.addEventListener('submit', (event) => event.preventDefault());
  if (titrationSelect) {
    titrationSelect.addEventListener('change', () => applyTitrationTypePreset());
    applyTitrationTypePreset({ lookup: false });
  }
  calculationInputIds.forEach((id) => {
    const input = $(id);
    if (!input) return;
    input.addEventListener('input', () => {
      updateConcentrationCalculationPreview({ writeTheory: id !== 'theoryEquivalenceInput' });
    });
    input.addEventListener('change', () => {
      updateConcentrationCalculationPreview({ writeTheory: id !== 'theoryEquivalenceInput' });
    });
  });
  if (sampleInput) {
    sampleInput.addEventListener('input', () => scheduleChemistryConstantsLookup());
    sampleInput.addEventListener('change', () => scheduleChemistryConstantsLookup(0));
    sampleInput.addEventListener('blur', () => lookupChemistryConstants({ silent: true }));
    scheduleChemistryConstantsLookup(0);
  }
  const candidateSelect = $('constantsCandidateSelect');
  if (candidateSelect) candidateSelect.addEventListener('change', selectConstantsCandidate);
  if (indicatorSelect) {
    indicatorSelect.addEventListener('change', () => {
      setText('indicatorModelLabel', `${selectedIndicatorLabel()} · 변색범위 기록`);
    });
    setText('indicatorModelLabel', `${selectedIndicatorLabel()} · 변색범위 기록`);
  }
}


function addRoiSetupHandlers() {
  const setupButton = $('roiSetupButton');
  const autoSetupButton = $('roiAutoSetupButton');
  const lockButton = $('roiLockButton');
  const unlockButton = $('roiUnlockButton');
  const resetButton = $('roiResetButton');
  const rotateButton = $('mini2RotateButton');
  if (setupButton) {
    setupButton.addEventListener('click', async () => {
      stopAutoRoiSetup();
      await enterRoiSetupMode();
    });
  }
  if (autoSetupButton) {
    updateAutoRoiSetupButton();
    autoSetupButton.addEventListener('click', toggleAutoRoiSetup);
  }
  if (lockButton) {
    lockButton.addEventListener('click', async () => {
      const requestBackendRevision = backendRevision;
      try {
        stopAutoRoiSetup();
        const payload = await postRoiAction('/api/roi-lock', {}, 'ROI 고정 중');
        if (!payload || requestBackendRevision !== backendRevision) return;
        roiSetupMode = false;
        let trackingStatus = '자동추적 off';
        try {
          await setRoiAutoTracking('off', { updateStatus: false });
          if (requestBackendRevision !== backendRevision) return;
        } catch (settingsError) {
          if (requestBackendRevision !== backendRevision) return;
          trackingStatus = `자동추적 끄기 실패 · ${settingsError.message}`;
        }
        setText('previewStatus', `ROI 고정 · ${trackingStatus}`);
        setText('roiSettingsStatus', `ROI 고정 · ${trackingStatus}`);
      } catch (error) {
        if (requestBackendRevision !== backendRevision) return;
        setText('roiSettingsStatus', `잠금 실패 · ${error.message}`);
      }
    });
  }
  if (unlockButton) {
    unlockButton.addEventListener('click', async () => {
      await enterRoiSetupMode();
    });
  }
  if (resetButton) {
    resetButton.addEventListener('click', async () => {
      await enterRoiSetupMode({ reset: true });
    });
  }
  if (rotateButton) {
    updateMini2RotateButton();
    rotateButton.addEventListener('pointerdown', (event) => {
      event.stopPropagation();
    });
    rotateButton.addEventListener('click', async (event) => {
      event.preventDefault();
      event.stopPropagation();
      await toggleMini2Rotation();
    });
  }
  updateRoiButtons();
}



addStreamErrorHandlers();
setupBackendControls();
addModeHandlers();
addChemistryHandlers();
if (isAndroidWebViewBridge()) {
  setWaiting('Android WebView bridge 연결 중');
  setBackendBaseStatus('백엔드: Android WebView bridge');
  setText('roiSettingsStatus', 'Android 앱 권한/카메라 초기화 중');
} else {
  connectLiveStream();
  refreshCollectorHealth();
  window.setInterval(refreshCollectorHealth, 2000);
  refreshCsvStatus();
  addCsvRecordingHandlers();
  addRoiSetupHandlers();
  addRoiDragHandler('visiblePreview', 'visibleRoiOverlay', 'visible');
  addRoiDragHandler('thermalPreview', 'thermalRoiOverlay', 'thermal');
}
window.addEventListener('resize', () => {
  refreshRoiOverlays();
  renderDemoView();
});


// Notebook-only settings sync; never sends a recording or motion request.
let remoteSettingsSyncing = false;
let remoteSettingsRevision = 0;
let remoteSettingsTimer = null;

async function syncRemoteSettings() {
  const requestBackendRevision = backendRevision;
  if (remoteControlMode || isAndroidWebViewBridge() || remoteSettingsSyncing) return;
  if (latestCsvStatus?.recording || latestCsvStatus?.finalizing) return;
  remoteSettingsSyncing = true;
  const revision = remoteSettingsRevision;
  const backend = liveStreamBase;
  try {
    let body = null;
    let invalidReason = '';
    try {
      body = buildPumpTimelineStartPayload();
    } catch (error) {
      invalidReason = error.message;
    }
    const response = await fetch(endpoint('/api/remote/config'), { cache: 'no-store' });
    if (requestBackendRevision !== backendRevision) return null;
    const current = await response.json().catch(() => ({}));
    if (requestBackendRevision !== backendRevision) return null;
    if (!response.ok || !current.ok) throw new Error('원격 설정 연결 대기');
    if (revision !== remoteSettingsRevision || backend !== liveStreamBase) return;
    if (JSON.stringify(current.config || null) !== JSON.stringify(body)) {
      const saved = await fetch(endpoint('/api/remote/config'), {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || { clear: true }),
      });
      const result = await saved.json().catch(() => ({}));
      if (requestBackendRevision !== backendRevision) return null;
      if (!saved.ok || !result.ok) throw new Error(result.error || '원격 설정 동기화 대기');
    }
    if (revision === remoteSettingsRevision && backend === liveStreamBase) {
      setText('remoteSettingsStatus', invalidReason
        ? `원격 시작 보류 · ${invalidReason}`
        : '원격 설정 자동 동기화됨');
    }
  } catch (error) {
    if (requestBackendRevision !== backendRevision) return null;
    if (backend === liveStreamBase) setText('remoteSettingsStatus', error.message);
  } finally {
    if (requestBackendRevision === backendRevision) remoteSettingsSyncing = false;
  }
}

function scheduleRemoteSettingsSync() {
  remoteSettingsRevision += 1;
  if (remoteSettingsTimer !== null) window.clearTimeout(remoteSettingsTimer);
  remoteSettingsTimer = window.setTimeout(() => {
    remoteSettingsTimer = null;
    syncRemoteSettings();
  }, 400);
}

if (remoteControlMode) {
  setText('remoteSettingsStatus', '노트북에 저장된 설정 사용 · 설정 변경은 노트북에서');
}

if (!remoteControlMode && !isAndroidWebViewBridge()) {
  for (const id of ['pumpTimelineForm', 'chemistryModelForm']) {
    $(id)?.addEventListener('input', scheduleRemoteSettingsSync);
    $(id)?.addEventListener('change', scheduleRemoteSettingsSync);
  }
  scheduleRemoteSettingsSync();
  // Rechecks server state so reconnect/server restart repairs the shared config.
  window.setInterval(syncRemoteSettings, 2000);
}
