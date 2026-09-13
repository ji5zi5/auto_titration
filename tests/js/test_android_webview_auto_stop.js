const fs = require('fs');
const vm = require('vm');
const assert = require('assert');

const elements = new Map();
const controlLabel = {
  dataset: {},
  querySelector: (selector) => selector === 'strong' ? elements.get('autoStopOptionLabel') : null,
  appendChild(element) { elements.set(element.id, element); },
};
elements.set('autoStopEnabledInput', {
  checked: true,
  disabled: false,
  setAttribute(name, value) { this[name] = value; },
  closest: (selector) => selector === 'label' ? controlLabel : null,
});
elements.set('autoStopOptionLabel', { textContent: '' });
elements.set('autoStopStatus', { textContent: '' });

const sandbox = {
  console,
  window: {},
  buildPumpTimelineStartPayload: () => ({
    titration_type: 'weak_acid_strong_base',
    sample_name: 'acetic acid',
    sample_concentration_M: 0.1,
    sample_volume_ml: 10,
    sample_valence: 1,
    titrant_name: 'sodium hydroxide',
    titrant_concentration_M: 0.1,
    titrant_valence: 1,
    theoretical_equivalence_volume_ml: 10,
    pump_rate_ml_per_s: 0.99,
    auto_stop_enabled: true,
    auto_stop_pulse_enabled: true,
    auto_stop_pulse_steps: 5,
    auto_stop_slow_stage_enabled: true,
    auto_stop_slow_rate_steps_per_s: 25,
  }),
  document: {
    getElementById: (id) => elements.get(id) || null,
    createElement: () => ({ setAttribute() {}, addEventListener() {}, textContent: '' }),
  },
  navigator: {},
  setInterval: () => 0,
};
sandbox.window.AutoTitrationAndroid = {
  getStatusJson: () => JSON.stringify({ ok: true, live: {}, mini2: {}, pump: {}, csv: {}, roi: {} }),
  pumpDevices: () => JSON.stringify({ ok: true, pump_devices: [] }),
};
sandbox.window.setInterval = sandbox.setInterval;

vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('website/android-webview.js', 'utf8'), sandbox, {
  filename: 'android-webview.js',
});

const hooks = sandbox.window.AutoTitrationAndroidTestHooks;
assert(hooks, 'Android test hooks must be exposed');

const sanitized = hooks.stripUnsupportedAndroidAutoStopConfig({
  pump_rate_ml_per_s: 0.99,
  auto_stop_enabled: true,
  auto_stop_confirmation_delay_s: 0.4,
  auto_stop_pulse_enabled: true,
  auto_stop_pulse_steps: 5,
  auto_stop_slow_stage_enabled: true,
  auto_stop_slow_rate_steps_per_s: 25,
});
assert.strictEqual(sanitized.pump_rate_ml_per_s, 0.99);
assert.strictEqual(Object.keys(sanitized).some((key) => key.startsWith('auto_stop_')), false);

const bridgeConfig = hooks.buildAndroidRecordingConfig();
assert.strictEqual(bridgeConfig.pump_rate_ml_per_s, 0.99);
assert.strictEqual(
  Object.keys(bridgeConfig).some((key) => key.startsWith('auto_stop_')),
  false,
  'Android bridge payload must not contain auto-stop or pulse activation fields',
);

hooks.configureAndroidUnsupportedAutoStop();
const input = elements.get('autoStopEnabledInput');
assert.strictEqual(input.checked, false);
assert.strictEqual(input.disabled, true);
assert.strictEqual(input['aria-describedby'], 'autoStopSupportNotice');
assert.strictEqual(controlLabel.dataset.androidUnsupported, 'true');
assert.strictEqual(elements.get('autoStopOptionLabel').textContent, 'Android에서 사용할 수 없음');
assert.match(elements.get('autoStopSupportNotice').textContent, /Windows 수집기에서만 지원/);
assert.match(elements.get('autoStopStatus').textContent, /Windows 수집기에서만 지원/);

console.log('android webview auto-stop capability guard ok');
