const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('website/app.js', 'utf8');
const elements = new Map();
const requests = [];
let autoDownloadClicks = 0;

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function element(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id,
      value: '',
      textContent: '',
      disabled: false,
      checked: false,
      innerHTML: '',
      selectedOptions: [],
      dataset: {},
      style: {},
      addEventListener() {},
      closest() { return null; },
      getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0 }; },
      classList: { remove() {}, add() {}, toggle() {} },
      setAttribute(name, value) { this[name] = value; },
      querySelector() { return null; },
      appendChild() {},
    });
  }
  return elements.get(id);
}

function deferredFetch(url, options = {}) {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  const request = {
    url,
    options,
    resolve(payload, { ok = true, status = 200 } = {}) {
      resolve({ ok, status, json: async () => payload });
    },
  };
  requests.push(request);
  return promise;
}

const context = {
  console,
  window: {
    AutoTitrationAndroid: {},
    location: { href: 'http://example.test/', port: '', hostname: 'example.test' },
    localStorage: { getItem() { return ''; }, setItem() {} },
    addEventListener() {},
    setTimeout() { return 0; },
    clearTimeout() {},
    setInterval() { return 0; },
  },
  document: {
    body: { dataset: {}, appendChild() {} },
    getElementById: element,
    querySelectorAll() { return []; },
    createElement(tag) {
      return {
        tag,
        style: {},
        dataset: {},
        click() { if (tag === 'a') autoDownloadClicks += 1; },
        remove() {},
        appendChild() {},
      };
    },
  },
  EventSource: function EventSource() {
    return { addEventListener() {}, close() {}, set onerror(_) {} };
  },
  fetch: deferredFetch,
};

vm.createContext(context);
vm.runInContext(source, context);

async function settle() {
  await Promise.resolve();
  await Promise.resolve();
}

async function testPumpLifecycle() {
  const dispense = context.sendPumpCommand('/api/pump/dispense', 'dispense pending');
  const duplicateDispense = context.sendPumpCommand('/api/pump/dispense', 'duplicate pending');
  const oppositeMotion = context.sendPumpCommand('/api/pump/retract', 'retract pending');
  assert(dispense === duplicateDispense, 'duplicate pump motion must share the in-flight request');
  assert(dispense !== oppositeMotion, 'opposite motion should be rejected instead of sharing the wrong operation');
  assert(await oppositeMotion === null, 'opposite motion must be ignored while motion is in flight');
  assert(requests.length === 1, `expected one motion POST, got ${requests.length}`);

  const stop = context.sendPumpCommand('/api/pump/stop', 'stop pending');
  const duplicateStop = context.sendPumpCommand('/api/pump/stop', 'duplicate stop pending');
  assert(stop === duplicateStop, 'duplicate STOP must share the in-flight STOP request');
  assert(requests.length === 2, 'STOP must preempt pending motion with its own POST');
  assert(element('serialPumpStopButton').disabled === false, 'emergency STOP must remain enabled');
  assert(element('serialPumpDispenseButton').disabled, 'motion buttons must be disabled during requests');
  assert(element('serialPumpRetractButton').disabled, 'opposite motion must be visibly blocked');

  requests[1].resolve({ ok: true, pump: { action: 'stop', command: 'c', sent: true } });
  await stop;
  assert(element('pumpCommandStatus').textContent.includes('펌프 정지'), 'STOP response must set stopped status');

  requests[0].resolve({ ok: true, pump: { action: 'start', command: 'b', sent: true } });
  await dispense;
  await settle();
  assert(element('pumpCommandStatus').textContent.includes('펌프 정지'), 'stale motion response overwrote STOP status');
  assert(!element('serialPumpDispenseButton').disabled, 'motion buttons must recover after requests settle');
  assert(element('serialPumpStopButton').disabled === false, 'STOP must still be enabled after requests settle');

  const retract = context.sendPumpCommand('/api/pump/retract', 'retract pending');
  assert(requests.length === 3, 'new motion should be allowed after prior lifecycle settles');
  requests[2].resolve({ ok: true, pump: { action: 'retract', command: 'a', sent: true } });
  await retract;
}

function configureCsvInputs() {
  const values = {
    titrationTypeSelect: 'weak_acid_strong_base',
    sampleSubstanceInput: 'acetic acid',
    sampleConcentrationInput: '0.1',
    sampleVolumeInput: '25',
    sampleValenceInput: '1',
    standardSolutionNameInput: 'NaOH',
    standardConcentrationInput: '0.1',
    titrantValenceInput: '1',
    indicatorSelect: 'phenolphthalein',
    theoryEquivalenceInput: '25',
    pumpRateInput: '0.2',
    equivalenceWindowInput: '0.5',
    slowRateStepsInput: '25',
  };
  Object.entries(values).forEach(([id, value]) => { element(id).value = value; });
  vm.runInContext('latestRoiRecordable = true; latestRoiComplete = true;', context);
}

async function testCsvLifecycleAndDownloads() {
  configureCsvInputs();
  const initialRequestCount = requests.length;
  const start = context.startCsvRecording();
  const duplicateStart = context.startCsvRecording();
  assert(start === duplicateStart, 'duplicate CSV start must share the in-flight request');
  assert(requests.length === initialRequestCount + 1, 'duplicate CSV start emitted another POST');

  const stop = context.stopCsvRecording();
  const duplicateStop = context.stopCsvRecording();
  assert(stop === duplicateStop, 'duplicate CSV stop must share the in-flight request');
  assert(requests.length === initialRequestCount + 2, 'CSV stop must preempt an in-flight start');

  const startRequest = requests[initialRequestCount];
  const stopRequest = requests[initialRequestCount + 1];
  stopRequest.resolve({
    ok: true,
    csv: { state: 'stopped', recording: false, session_id: 7, started_epoch_s: 1000, row_count: 3 },
  });
  await stop;
  assert(vm.runInContext('latestCsvStatus.state', context) === 'stopped', 'stop response did not win CSV state');
  assert(autoDownloadClicks === 1, 'explicit stopped session should download exactly once');

  startRequest.resolve({
    ok: true,
    csv: { state: 'recording', recording: true, session_id: 7, started_epoch_s: 1000, row_count: 0 },
  });
  await start;
  await settle();
  assert(vm.runInContext('latestCsvStatus.state', context) === 'stopped', 'stale start response overwrote newer stop');
  assert(autoDownloadClicks === 1, 'stale start response caused a duplicate download');

  context.applyCsvStatus({ state: 'recording', recording: true, session_id: 8, started_epoch_s: 2000, row_count: 1 });
  context.applyCsvStatus({ state: 'stopped', recording: false, session_id: 8, started_epoch_s: 2000, row_count: 2 });
  assert(autoDownloadClicks === 2, 'recording-to-stopped without finalizing must auto-download');
  context.applyCsvStatus({ state: 'stopped', recording: false, session_id: 8, started_epoch_s: 2000, row_count: 2 });
  assert(autoDownloadClicks === 2, 'same backend/session downloaded twice');

  context.applyCsvStatus({ state: 'recording', recording: true, session_id: 8, started_epoch_s: 3000, row_count: 1 });
  context.applyCsvStatus({ state: 'stopped', recording: false, session_id: 8, started_epoch_s: 3000, row_count: 2 });
  assert(autoDownloadClicks === 3, 'reused session id with a new start timestamp must download again');

  vm.runInContext("liveStreamBase = 'http://second-backend.test'; latestCsvStatus = null;", context);
  context.applyCsvStatus({ state: 'recording', recording: true, session_id: 8, started_epoch_s: 3000, row_count: 1 });
  context.applyCsvStatus({ state: 'stopped', recording: false, session_id: 8, started_epoch_s: 3000, row_count: 2 });
  assert(autoDownloadClicks === 4, 'same session identity on a different backend must download independently');

  const failedStop = context.stopCsvRecording();
  const failedStopRequest = requests[requests.length - 1];
  failedStopRequest.resolve({ ok: false, error: 'collector rejected stop' }, { ok: false, status: 500 });
  await failedStop;
  assert(element('csvStateLabel').textContent.includes('녹화 종료 실패'), 'stop error wording was not operation-specific');
  assert(!element('csvStateLabel').textContent.includes('녹화 시작 실패'), 'stop error was mislabeled as start failure');
}

async function testCrossActionPreemption() {
  configureCsvInputs();
  const initialRequestCount = requests.length;
  const start = context.startCsvRecording();
  const blockedMotion = context.sendPumpCommand('/api/pump/dispense', 'blocked during CSV start');
  assert(await blockedMotion === null, 'manual motion must be blocked during CSV start');
  assert(requests.length === initialRequestCount + 1, 'blocked motion emitted a POST during CSV start');

  const emergencyStop = context.sendPumpCommand('/api/pump/stop', 'emergency stop');
  assert(requests.length === initialRequestCount + 2, 'emergency STOP did not preempt CSV start');
  requests[initialRequestCount + 1].resolve({
    ok: true,
    pump: { action: 'stop', command: 'c', sent: true },
  });
  await emergencyStop;
  requests[initialRequestCount].resolve({
    ok: true,
    csv: { state: 'recording', recording: true, session_id: 9, started_epoch_s: 4000 },
    pump: { action: 'start', command: 'b', sent: true },
  });
  await start;
  await settle();
  assert(element('pumpCommandStatus').textContent.includes('펌프 정지'), 'stale CSV start overwrote emergency STOP');
  assert(vm.runInContext('latestCsvStatus.state', context) !== 'recording', 'stale CSV start overwrote CSV state');

  const motion = context.sendPumpCommand('/api/pump/dispense', 'manual motion');
  assert(requests.length === initialRequestCount + 3, 'manual motion did not start after CSV request settled');
  const csvStop = context.stopCsvRecording();
  const blockedOpposite = context.sendPumpCommand('/api/pump/retract', 'blocked during CSV stop');
  assert(await blockedOpposite === null, 'manual motion must be blocked during CSV stop');
  assert(requests.length === initialRequestCount + 4, 'blocked motion emitted a POST during CSV stop');

  requests[initialRequestCount + 3].resolve({
    ok: true,
    csv: { state: 'stopped', recording: false, session_id: 9, started_epoch_s: 4000 },
    pump: { action: 'stop', command: 'c', sent: true },
  });
  await csvStop;
  requests[initialRequestCount + 2].resolve({
    ok: true,
    pump: { action: 'start', command: 'b', sent: true },
  });
  await motion;
  await settle();
  assert(element('pumpCommandStatus').textContent.includes('펌프 정지'), 'stale manual motion overwrote CSV STOP');
}

function testWithheldPredictionReadiness() {
  const stalePrediction = {
    state: 'stopped',
    predicted_equivalence_status: 'withheld',
    predicted_equivalence_volume_ml: 12.34,
    sample_concentration_from_predicted_equivalence_M: 0.12345,
    predicted_equivalence_pH: 8.76,
  };
  const reasonLabels = {
    insufficient_usable_sensor_time_volume_observations: '사용 가능한 센서·시간·주입량 관측이 부족합니다',
    insufficient_recorded_time_progression: '기록 시간이 충분히 진행되지 않았습니다',
    insufficient_recorded_volume_progression: '주입량 변화가 충분하지 않습니다',
    no_sensor_variation: '센서 변화가 감지되지 않았습니다',
  };

  Object.entries(reasonLabels).forEach(([reason, expectedLabel]) => {
    context.updateConcentrationModePreview({ ...stalePrediction, predicted_equivalence_reason: reason });
    assert(element('calcModeStatus').textContent.includes(expectedLabel), `missing Korean reason for ${reason}`);
    assert(!element('calcModeStatus').textContent.includes('완료'), `withheld ${reason} was shown as complete`);
    assert(element('calcPredictedEquivalenceValue').textContent === '-', 'withheld volume was not cleared');
    assert(element('calcSampleConcentrationValue').textContent === '-', 'withheld concentration was not cleared');
  });

  context.updateConcentrationModePreview({
    ...stalePrediction, state: 'stopped', auto_stop_state: 'triggered',
    auto_stop_reason: 'required_sensor_missing',
    predicted_equivalence_reason: 'no_sensor_variation',
  });
  assert(element('calcModeStatus').textContent.startsWith('오류로 종료'), 'terminal sensor fault must precede readiness label');

  context.applyLiveMetadata({
    csv_state: 'stopped',
    csv_row_count: 4,
    predicted_equivalence_status: 'withheld',
    predicted_equivalence_reason: 'no_sensor_variation',
    predicted_equivalence_volume_ml: 12.34,
    sample_concentration_from_predicted_equivalence_M: 0.12345,
    predicted_equivalence_pH: 8.76,
  });
  assert(
    vm.runInContext('latestCsvStatus.predicted_equivalence_status', context) === 'withheld',
    'live event did not pass prediction readiness status to CSV rendering',
  );
  assert(element('calculatedConcentrationValue').textContent === '-', 'live withheld concentration was not cleared');
  assert(element('calcModeStatus').textContent.includes('센서 변화가 감지되지 않았습니다'), 'live reason was not rendered');

}

function testGetAndLiveDownloadIdentityConsistency() {
  const clicksBefore = autoDownloadClicks;
  context.applyCsvStatus({
    state: 'recording',
    recording: true,
    session_id: 21,
    started_epoch_s: 5000,
    row_count: 1,
  });
  context.applyLiveMetadata({
    csv_state: 'stopped',
    csv_recording: false,
    csv_session_id: 21,
    csv_recording_started_epoch_s: 5000,
    csv_row_count: 8,
  });
  assert(autoDownloadClicks === clicksBefore + 1, 'SSE stopped shape did not trigger one session download');
  assert(
    vm.runInContext('latestCsvStatus.started_epoch_s', context) === 5000,
    'SSE recording start epoch was not forwarded to CSV status',
  );

  context.applyLiveMetadata({
    csv_state: 'recording',
    csv_recording: true,
    csv_session_id: 21,
    csv_recording_started_epoch_s: 5000,
    csv_row_count: 8,
  });
  context.applyCsvStatus({
    state: 'stopped',
    recording: false,
    session_id: 21,
    started_epoch_s: 5000,
    row_count: 8,
  });
  assert(autoDownloadClicks === clicksBefore + 1, 'GET and SSE shapes produced duplicate session downloads');
}

async function testStaleStatusIntakeAfterStops() {
  context.applyCsvStatus({
    state: 'recording', recording: true, session_id: 30, started_epoch_s: 6000,
    updated_epoch_s: 100, row_count: 2,
  }, { source: 'live' });
  const csvStopRequestIndex = requests.length;
  const csvStop = context.stopCsvRecording();
  requests[csvStopRequestIndex].resolve({
    ok: true,
    csv: {
      state: 'stopped', recording: false, session_id: 30, started_epoch_s: 6000,
      updated_epoch_s: 200, row_count: 6,
    },
    pump: { action: 'stop', command: 'c', sent: true },
  });
  await csvStop;

  const staleGetIndex = requests.length;
  const staleGet = context.refreshCsvStatus();
  requests[staleGetIndex].resolve({
    ok: true,
    csv: {
      state: 'recording', recording: true, session_id: 30, started_epoch_s: 6000,
      updated_epoch_s: 150, row_count: 3, auto_stop_state: 'triggered',
      auto_stop_reason: 'persistent_color_change',
    },
  });
  await staleGet;
  context.applyLiveMetadata({
    csv_state: 'recording', csv_recording: true, csv_session_id: 30,
    csv_recording_started_epoch_s: 6000, csv_updated_epoch_s: 175, csv_row_count: 4,
    auto_stop_state: 'triggered', auto_stop_reason: 'persistent_color_change',
  });
  assert(vm.runInContext('latestCsvStatus.state', context) === 'stopped', 'stale GET/SSE restored recording after CSV STOP');
  assert(vm.runInContext('latestCsvStatus.updated_epoch_s', context) === 200, 'stale GET/SSE replaced CSV STOP revision');
  assert(element('pumpCommandStatus').textContent.includes('펌프 정지'), 'stale GET/SSE replaced CSV STOP pump status');

  context.applyCsvStatus({
    state: 'recording', recording: true, session_id: 31, started_epoch_s: 7000,
    updated_epoch_s: 300, row_count: 5,
  }, { source: 'get' });
  const pumpStopRequestIndex = requests.length;
  const pumpStop = context.sendPumpCommand('/api/pump/stop', 'manual pump stop');
  requests[pumpStopRequestIndex].resolve({
    ok: true,
    pump: { action: 'stop', command: 'c', sent: true },
  });
  await pumpStop;

  const pumpStaleGetIndex = requests.length;
  const pumpStaleGet = context.refreshCsvStatus();
  requests[pumpStaleGetIndex].resolve({
    ok: true,
    csv: {
      state: 'recording', recording: true, session_id: 31, started_epoch_s: 7000,
      updated_epoch_s: 290, row_count: 4, auto_stop_state: 'triggered',
      auto_stop_reason: 'persistent_color_change',
    },
  });
  await pumpStaleGet;
  context.applyLiveMetadata({
    csv_state: 'recording', csv_recording: true, csv_session_id: 31,
    csv_recording_started_epoch_s: 7000, csv_updated_epoch_s: 295, csv_row_count: 4,
    auto_stop_state: 'triggered', auto_stop_reason: 'persistent_color_change',
  });
  assert(vm.runInContext('latestCsvStatus.updated_epoch_s', context) === 300, 'stale status replaced pump-STOP baseline');
  assert(element('pumpCommandStatus').textContent.includes('펌프 정지'), 'stale status replaced manual pump STOP');

  context.applyLiveMetadata({
    csv_state: 'recording', csv_recording: true, csv_session_id: 31,
    csv_recording_started_epoch_s: 7000, csv_updated_epoch_s: 350, csv_row_count: 9,
    auto_stop_state: 'triggered', auto_stop_reason: 'persistent_color_change',
  });
  assert(vm.runInContext('latestCsvStatus.updated_epoch_s', context) === 350, 'fresh CSV revision was blocked after pump-only STOP');
  assert(vm.runInContext('latestCsvStatus.row_count', context) === 9, 'fresh recording progress was not preserved after pump-only STOP');
  assert(element('pumpCommandStatus').textContent.includes('펌프 정지'), 'old auto-stop trigger replaced manual pump STOP on fresh CSV data');
}

(async () => {
  await testPumpLifecycle();
  await testCsvLifecycleAndDownloads();
  await testCrossActionPreemption();
  testWithheldPredictionReadiness();
  testGetAndLiveDownloadIdentityConsistency();
  await testStaleStatusIntakeAfterStops();
  context.setAppMode('calculator');
  assert(element('resultsView').hidden === false, 'results and graphs hidden in results mode');
  assert(element('sensorGrid').hidden === true, 'video still shown in results mode');
  context.setAppMode('csv');
  assert(element('resultsView').hidden === true, 'graphs leaked into recording mode');
  assert(element('sensorGrid').hidden === false, 'recording video hidden');
  console.log('web request lifecycle regression OK');
})().catch((error) => {
  console.error(error.stack || error);
  process.exitCode = 1;
});
