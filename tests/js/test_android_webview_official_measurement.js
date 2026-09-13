const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const code = fs.readFileSync('website/android-webview.js', 'utf8');
const sandbox = {
  console,
  window: {},
  document: { getElementById: () => null, createElement: () => ({ setAttribute() {}, addEventListener() {} }) },
  navigator: {},
  setInterval: () => 0,
};
sandbox.window.AutoTitrationAndroid = {
  getStatusJson: () => JSON.stringify({ ok: true, live: {}, mini2: {}, pump: {}, csv: {}, roi: {} }),
  pumpDevices: () => JSON.stringify({ ok: true, pump_devices: [] }),
};
sandbox.window.setInterval = sandbox.setInterval;
vm.createContext(sandbox);
vm.runInContext(code, sandbox, { filename: 'android-webview.js' });
const hooks = sandbox.window.AutoTitrationAndroidTestHooks;
assert(hooks, 'test hooks exposed');

const nativeStartStage = 'USB_StartStreamCallback=ok channel=0';
assert.strictEqual(
  hooks.classifyMini2StageReport(nativeStartStage, 'stream_attempt_started no_callback_entry', {
    dispatchedCallbackCount: 3,
    callbackEntryDetail: 'route=jni disposition=dispatched dispatchedCount=3',
    frameCounter: 0,
  }),
  'callback_packet_observed_official_handoff_missing',
);
assert.strictEqual(
  hooks.classifyMini2StageReport(nativeStartStage, 'stream_attempt_started no_callback_entry', {
    dispatchedCallbackCount: 0,
    callbackEntryDetail: 'route=jni disposition=rejected rejectedCount=3',
    frameCounter: 0,
    postStartState: 'native_start_accepted_callback_packet_observed_official_handoff_missing',
  }),
  'native_start_succeeded_waiting_for_java_callback',
);

const baseOfficial = {
  official_measurement_status: 'READY',
  official_measurement_reason: 'official_f2_scalar_measurement_ready',
  official_measurement_frame_counter: 5,
  official_temperature_avg_c: 24.5,
  official_temperature_min_c: 20.25,
  official_temperature_max_c: 28.75,
  official_temperature_center_c: 25.0,
  official_temperature_provenance: 'official_f2_analyzer_measurement_stats',
  official_temperature_scope: 'rectangle',
  official_full_matrix_celsius_allowed: false,
};
const currentOfficial = {
  ...baseOfficial,
  official_measurement_matches_current_frame: true,
  official_measurement_temporal_scope: 'current_frame',
  official_measurement_age_frames: 0,
};
const staleOfficial = {
  ...baseOfficial,
  official_measurement_matches_current_frame: false,
  official_measurement_temporal_scope: 'last_completed_measurement',
  official_measurement_age_frames: 2,
};

let parsed = hooks.trustedAndroidTemperature({
  live: { ...currentOfficial, thermal_frame_counter: 5 },
  mini2: { raw_stream: {} },
});
assert.strictEqual(parsed.temperature_avg_c, 24.5);
assert.strictEqual(parsed.temperature_provenance, 'official_f2_analyzer_measurement_stats');
assert.strictEqual(parsed.temperature_scope, 'rectangle');
assert.strictEqual(parsed.full_matrix_celsius_allowed, false);
assert.strictEqual(parsed.official_measurement_matches_current_frame, true);
assert.strictEqual(parsed.official_measurement_temporal_scope, 'current_frame');
assert.strictEqual(parsed.official_measurement_age_frames, 0);

parsed = hooks.trustedAndroidTemperature({
  live: {},
  mini2: { raw_stream: { ...currentOfficial, frame_counter: 5, official_temperature_scope: 'fullscreen' } },
});
assert.strictEqual(parsed.temperature_source, 'official_f2_analyzer_measurement_stats');
assert.strictEqual(parsed.temperature_scope, 'fullscreen');
assert.strictEqual(parsed.official_measurement_matches_current_frame, true);

const staleParsed = hooks.androidOfficialTemperatureSummaryFrom(staleOfficial, 7);
assert.strictEqual(staleParsed.official_measurement_matches_current_frame, false);
assert.strictEqual(staleParsed.official_measurement_temporal_scope, 'last_completed_measurement');
assert.strictEqual(staleParsed.official_measurement_age_frames, 2);
assert.strictEqual(staleParsed.temperature_avg_c, undefined);
assert.strictEqual(hooks.trustedAndroidTemperature({ live: { ...staleOfficial, thermal_frame_counter: 7 }, mini2: { raw_stream: {} } }), null);

const sanitizedStale = hooks.sanitizeAndroidBridgePayload({
  ok: true,
  live: { ...staleOfficial, thermal_frame_counter: 7 },
  mini2: { raw_stream: {} },
  roi: { thermal_roi: '1,2,3,4' },
});
assert.strictEqual(sanitizedStale.live.official_temperature_avg_c, 24.5);
assert.strictEqual(sanitizedStale.live.official_measurement_matches_current_frame, false);
assert.strictEqual(sanitizedStale.live.official_measurement_temporal_scope, 'last_completed_measurement');
assert.strictEqual(sanitizedStale.live.official_measurement_age_frames, 2);
assert.strictEqual(sanitizedStale.live.temperature_source, undefined);
assert.strictEqual(sanitizedStale.live.temperature_avg_c, null);
assert.strictEqual(sanitizedStale.live.celsius_allowed, false);
assert.strictEqual(sanitizedStale.live.full_matrix_celsius_allowed, undefined);
assert.strictEqual(sanitizedStale.live.thermal_roi_ready, false);
assert.strictEqual(sanitizedStale.roi.thermal_roi, undefined);

for (const bad of [
  { name: 'missing source counter', official: currentOfficial, sourceCounter: undefined },
  { name: 'null measurement counter', official: { ...currentOfficial, official_measurement_frame_counter: null }, sourceCounter: 5 },
  { name: 'negative measurement counter', official: { ...currentOfficial, official_measurement_frame_counter: -1 }, sourceCounter: 5 },
  { name: 'future measurement counter', official: { ...currentOfficial, official_measurement_frame_counter: 6 }, sourceCounter: 5 },
  { name: 'unsafe source counter', official: currentOfficial, sourceCounter: Number.MAX_SAFE_INTEGER + 1 },
  { name: 'missing current match flag', official: { ...currentOfficial, official_measurement_matches_current_frame: null }, sourceCounter: 5 },
  { name: 'wrong current scope', official: { ...currentOfficial, official_measurement_temporal_scope: 'last_completed_measurement' }, sourceCounter: 5 },
  { name: 'wrong current age', official: { ...currentOfficial, official_measurement_age_frames: 1 }, sourceCounter: 5 },
  { name: 'stale wrong age', official: { ...staleOfficial, official_measurement_age_frames: 1 }, sourceCounter: 7 },
  { name: 'stale wrong match flag', official: { ...staleOfficial, official_measurement_matches_current_frame: true }, sourceCounter: 7 },
  { name: 'stale non-stale counter', official: staleOfficial, sourceCounter: 5 },
]) {
  assert.strictEqual(hooks.androidOfficialTemperatureSummaryFrom(bad.official, bad.sourceCounter), null, bad.name);
}

for (const bad of [
  { official_temperature_provenance: 'device_global_summary' },
  { official_temperature_scope: 'matrix' },
  { official_full_matrix_celsius_allowed: true },
  { official_temperature_avg_c: Infinity },
  { official_temperature_avg_c: 40, official_temperature_min_c: 20, official_temperature_max_c: 30 },
  { official_temperature_center_c: 40, official_temperature_min_c: 20, official_temperature_max_c: 30 },
  { official_measurement_status: 'PENDING' },
]) {
  parsed = hooks.trustedAndroidTemperature({
    live: { ...currentOfficial, ...bad, thermal_frame_counter: 5 },
    mini2: { raw_stream: {} },
  });
  assert.strictEqual(parsed, null, `rejected ${JSON.stringify(bad)}`);
}

for (const malformedNumber of [false, true, '24.5', [], {}, [24.5]]) {
  parsed = hooks.trustedAndroidTemperature({
    live: {
      ...currentOfficial,
      official_temperature_avg_c: malformedNumber,
      thermal_frame_counter: 5,
    },
    mini2: { raw_stream: {} },
  });
  assert.strictEqual(parsed, null, `rejected coercible non-number ${JSON.stringify(malformedNumber)}`);
}

const plausibleGenericFallback = {
  celsius_allowed: true,
  temperature_avg_c: 22,
  temperature_min_c: 21,
  temperature_max_c: 23,
  temperature_provenance: 'device_global_summary',
  temperature_scope: 'device_global_summary',
  full_matrix_celsius_allowed: false,
};
for (const genericFallback of [
  plausibleGenericFallback,
  {
    celsius_allowed: true,
    temperature_avg_c: 0,
    temperature_min_c: 0,
    temperature_max_c: 0,
    temperature_provenance: 'device_global_summary',
    temperature_scope: 'device_global_summary',
    full_matrix_celsius_allowed: false,
  },
]) {
  assert.strictEqual(hooks.trustedAndroidTemperature({
    live: {},
    mini2: { raw_stream: genericFallback },
  }), null);
}

for (const unordered of [
  { temperature_avg_c: 20, temperature_min_c: 21, temperature_max_c: 23 },
  { temperature_avg_c: 24, temperature_min_c: 21, temperature_max_c: 23 },
  { temperature_avg_c: 22, temperature_min_c: 23, temperature_max_c: 21 },
]) {
  assert.strictEqual(hooks.androidTemperatureSummaryFrom({
    ...plausibleGenericFallback,
    ...unordered,
  }), null, `rejected unordered device-global summary ${JSON.stringify(unordered)}`);
}

const sanitizedCurrent = hooks.sanitizeAndroidBridgePayload({
  ok: true,
  live: { ...currentOfficial, thermal_frame_counter: 5 },
  mini2: { raw_stream: {} },
  roi: { thermal_roi: '1,2,3,4' },
});
assert.strictEqual(sanitizedCurrent.live.temperature_source, 'official_f2_analyzer_measurement_stats');
assert.strictEqual(sanitizedCurrent.live.full_matrix_celsius_allowed, false);
assert.strictEqual(sanitizedCurrent.live.official_full_matrix_celsius_allowed, false);
assert.strictEqual(sanitizedCurrent.live.thermal_roi_ready, false);
assert.strictEqual(sanitizedCurrent.roi.thermal_roi, undefined);

const appCode = fs.readFileSync('website/app.js', 'utf8');
const sharedCelsiusHelpers = appCode.slice(
  appCode.indexOf('function parseFiniteNumber'),
  appCode.indexOf('function formatNumber'),
);
vm.runInContext(sharedCelsiusHelpers, sandbox, { filename: 'app-celsius-helpers.js' });
sandbox.sanitizedCurrent = sanitizedCurrent;
assert.strictEqual(
  vm.runInContext('hasTrustedCelsiusTemperature(sanitizedCurrent.live)', sandbox),
  true,
  'Android sanitizer output is accepted by the shared Celsius consumer',
);
sandbox.missingProvenance = {
  ...sanitizedCurrent.live,
  temperature_provenance: '',
};
assert.strictEqual(
  vm.runInContext('hasTrustedCelsiusTemperature(missingProvenance)', sandbox),
  false,
  'shared Celsius consumer fails closed without approved provenance',
);

console.log('android webview official measurement parser ok');
