const assert = require('assert');
const view = require('../../website/demo-view.js');

function recording(sessionId, startedEpoch, overrides = {}) {
  return {
    state: 'recording', recording: true, session_id: sessionId, started_epoch_s: startedEpoch,
    recording_elapsed_s: 0, row_count: 0, pump_dosing_stage: 'fast', pump_state: 'continuous',
    ...overrides,
  };
}

assert.strictEqual(view.observedStage({ pump_dosing_stage: 'fast' }).label, '빠른 주입');
assert.strictEqual(view.observedStage({ auto_stop_pulse_state: 'continuous', pump_dosing_stage: 'fast' }).label, '빠른 주입');
assert.strictEqual(view.observedStage({ auto_stop_pulse_state: 'pulse_injecting', pump_dosing_stage: 'step_pulse' }).label, '미세 주입');
assert.strictEqual(view.observedStage({ pump_state: 'pulse_settling', pump_dosing_stage: 'slow_continuous' }).label, '혼합 대기');
assert.strictEqual(view.observedStage({ state: 'stopped', pump_dosing_stage: 'slow_continuous' }).label, '주입 정지');
assert.strictEqual(view.observedStage({ state: 'finalizing', pump_dosing_stage: 'slow_continuous' }).label, '결과 분석');
assert.strictEqual(view.observedStage({ pump_dosing_stage: '', model_score: 0.99 }), null, 'model score must not invent a stage');

// Default graph retention covers about one minute at the 25 fps target.
const minute = view.createState();
view.applyCsvStatus(minute, recording(10, 5000));
for (let index = 0; index < 1500; index += 1) {
  view.appendSample(minute, {
    csv_state: 'recording', csv_session_id: 10, csv_recording_started_epoch_s: 5000,
    csv_recording_elapsed_s: index / 25, visible_color_delta: index,
  });
}
assert.strictEqual(minute.samples.length, 1500, 'default graph must retain one minute at 25 fps');
assert.strictEqual(minute.samples[0].x, 0, 'first minute lost its start');
assert.strictEqual(minute.samples.at(-1).x, 59.96);
view.appendSample(minute, {
  csv_state: 'recording', csv_session_id: 10, csv_recording_started_epoch_s: 5000,
  csv_recording_elapsed_s: 60, visible_color_delta: 1500,
});
assert.strictEqual(minute.samples.length, 1500, 'graph retention must remain bounded');
assert.strictEqual(minute.samples[0].x, .04);
view.applyCsvStatus(minute, {state: 'stopped', session_id: 10, started_epoch_s: 5000});
assert.strictEqual(minute.samples.at(-1).x, 60, 'stop lost the latest point');
view.resetState(minute);
assert.strictEqual(minute.samples.length, 0);
assert.strictEqual(minute.maxSamples, 1500, 'backend reset changed retention');

const state = view.createState(10);
assert(view.applyCsvStatus(state, recording(1, 1000)));
assert(view.appendSample(state, {
  csv_state: 'recording', csv_recording: true, csv_session_id: 1, csv_recording_started_epoch_s: 1000,
  csv_recording_elapsed_s: 0.2, visible_color_delta: 1.5, temperature_avg_c: 24.1,
  pump_dosing_stage: 'fast', pump_state: 'continuous',
}, true));
assert.strictEqual(state.samples[0].thermalC, 24.1);
assert.strictEqual(state.samples[0].color, 1.5);

assert(view.appendSample(state, {
  csv_state: 'recording', csv_recording: true, csv_session_id: 1, csv_recording_started_epoch_s: 1000,
  csv_recording_elapsed_s: 0.4, visible_color_delta: null, temperature_avg_c: 9999,
  pump_dosing_stage: 'step_pulse', auto_stop_pulse_state: 'pulse_settling', pump_state: 'pulse_settling',
}, false));
assert.strictEqual(state.samples[1].color, null, 'missing color must remain a graph gap');
assert.strictEqual(state.samples[1].thermalC, null, 'untrusted Celsius must remain a graph gap');
assert.strictEqual(state.stage.label, '혼합 대기');
assert.strictEqual(view.appendSample(state, {
  csv_state: 'recording', csv_recording: true, csv_session_id: 1, csv_recording_started_epoch_s: 1000,
  csv_row_count: 3, visible_color_delta: 2,
}, true), false, 'row count must not be mislabeled as elapsed seconds');
assert.strictEqual(view.appendSample(state, {
  csv_state: 'recording', csv_recording: true, csv_session_id: 2, csv_recording_started_epoch_s: 2000,
  csv_recording_elapsed_s: 1, visible_color_delta: 2,
}, true), false, 'samples from another session must be rejected');

view.applyCsvStatus(state, {
  state: 'stopped', recording: false, session_id: 1, started_epoch_s: 1000, recording_elapsed_s: 1,
  pump_dosing_stage: 'slow_continuous', injected_volume_ml: 9.8, auto_stop_trigger_volume_ml: 9.2,
  predicted_equivalence_status: 'withheld', predicted_equivalence_volume_ml: 9.5,
  sample_concentration_from_predicted_equivalence_M: 0.1,
});
assert.strictEqual(state.stage.label, '주입 정지', 'terminal state must override stale dosing stage');
assert.strictEqual(state.result.outcome, 'manual-stop');
assert.strictEqual(state.result.label, '수동 종료');
assert.strictEqual(state.result.concentrationM, null, 'withheld prediction number must not leak');
assert.strictEqual(state.result.predictedVolumeMl, null, 'withheld predicted volume must not leak');
assert.strictEqual(state.result.volumeMl, 9.8, 'observed final injected volume remains available after stop');
assert.match(state.result.csvLabel, /다운로드 가능/);

assert.strictEqual(view.resultFrom({
  state: 'stopped', auto_stop_state: 'error', auto_stop_reason: 'pulse_control_failed',
}).outcome, 'error');
assert.strictEqual(view.resultFrom({
  state: 'stopped', auto_stop_state: 'triggered', auto_stop_reason: 'required_sensor_missing',
}).outcome, 'error');
assert.strictEqual(view.resultFrom({
  state: 'stopped', auto_stop_state: 'triggered', auto_stop_reason: 'required_color_missing',
}).outcome, 'error');
assert.strictEqual(view.resultFrom({
  state: 'stopped', auto_stop_state: 'triggered', auto_stop_reason: 'persistent_color_change',
}).outcome, 'complete');
assert.notStrictEqual(view.resultFrom({
  state: 'stopped', auto_stop_state: 'triggered', auto_stop_reason: 'emergency_stop',
}).outcome, 'complete');
const completed = view.resultFrom({
  state: 'stopped', auto_stop_state: 'triggered', auto_stop_reason: 'persistent_color_change',
  injected_volume_ml: 10.1, auto_stop_trigger_volume_ml: 9.7,
  predicted_equivalence_status: 'available', predicted_equivalence_volume_ml: 9.9,
  sample_concentration_from_predicted_equivalence_M: 0.101,
});
assert.strictEqual(completed.volumeMl, 10.1, 'total volume must use final injected total, not trigger volume');
assert.strictEqual(completed.predictedVolumeMl, 9.9, 'estimated endpoint volume must remain distinct');

assert(view.applyCsvStatus(state, recording(2, 2000)), 'fresh recording session should be accepted');
assert.strictEqual(state.samples.length, 0, 'fresh run must reset graph samples');
assert.strictEqual(state.result.volumeMl, null, 'fresh run must clear prior result');
assert.strictEqual(view.applyCsvStatus(state, {
  state: 'stopped', session_id: 1, started_epoch_s: 1000, injected_volume_ml: 99,
}), false, 'older session status must not replace the current session');
for (let index = 0; index < 25; index += 1) {
  view.appendSample(state, {
    csv_state: 'recording', csv_recording: true, csv_session_id: 2, csv_recording_started_epoch_s: 2000,
    csv_recording_elapsed_s: index / 10, visible_color_delta: index, temperature_avg_c: 20 + index / 10,
    pump_dosing_stage: index % 2 ? 'fast' : 'slow_continuous', pump_state: 'continuous',
  }, true);
}
assert.strictEqual(state.samples.length, 10, 'graph buffer must remain bounded');
assert(state.markers.length <= 10, 'stage marker buffer must remain bounded');
assert.strictEqual(state.samples[0].x, 1.5);

view.resetState(state);
assert.strictEqual(state.sessionKey, '', 'backend reset must clear session identity');
assert.strictEqual(state.samples.length, 0, 'backend reset must clear graph history');
assert(view.applyCsvStatus(state, recording(2, 1500)), 'same id with an earlier timestamp is valid after backend reset');

const fs = require('fs');
const vm = require('vm');
const appSource = fs.readFileSync('website/app.js', 'utf8');
const drawSource = appSource.slice(appSource.indexOf('function drawTrend'), appSource.indexOf('function renderDemoView'));
let strokes = 0;
const drawingContext = {
  setTransform() {}, clearRect() {}, beginPath() {}, moveTo() {}, lineTo() {}, setLineDash() {}, fillText() {},
  stroke() { strokes += 1; },
};
const canvas = { clientWidth: 640, clientHeight: 240, width: 0, height: 0, getContext: () => drawingContext };
const empty = {};
const drawSandbox = {
  demoViewState: { samples: Array.from({ length: 100 }, (_, x) => ({ x, color: x })), markers: [] },
  window: { devicePixelRatio: 1 },
  $: (id) => id === 'canvas' ? canvas : empty,
};
vm.createContext(drawSandbox);
vm.runInContext(drawSource, drawSandbox);
drawSandbox.drawTrend('canvas', 'empty', 'color', '#0066cc', 'ΔRGB');
assert.strictEqual(strokes, 5, 'one contiguous series should stroke once in addition to four grid lines');
strokes = 0;
drawSandbox.demoViewState.samples[50].color = null;
drawSandbox.drawTrend('canvas', 'empty', 'color', '#0066cc', 'ΔRGB');
assert.strictEqual(strokes, 6, 'a missing-value gap should produce exactly two stroked segments');

console.log('demo view session, stage, result, and graph guards OK');
