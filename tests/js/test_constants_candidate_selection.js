const fs = require('fs');
const vm = require('vm');

const source = fs.readFileSync('website/app.js', 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id,
      value: '',
      textContent: '',
      disabled: false,
      innerHTML: '',
      selectedOptions: [],
      addEventListener() {},
      closest() { return null; },
      getBoundingClientRect() { return { left: 0, top: 0, width: 320, height: 240 }; },
      classList: { remove() {}, add() {} },
      appendChild(child) {
        this.children = this.children || [];
        this.children.push(child);
      },
    });
  }
  return elements.get(id);
}
const context = {
  console,
  window: {
    location: { href: 'http://127.0.0.1:8765/' },
    localStorage: { getItem() { return ''; }, setItem() {} },
    addEventListener() {},
    setTimeout() { return 0; },
    clearTimeout() {},
  },
  document: {
    getElementById: element,
    createElement(tag) { return { tag, value: '', textContent: '' }; },
  },
  EventSource: function EventSource() {
    return { addEventListener() {}, close() {}, set onerror(_) {} };
  },
  fetch: async () => ({ ok: true, json: async () => ({ ok: true }) }),
};
vm.createContext(context);
vm.runInContext(source, context);
element('standardConcentrationInput').value = '0.100';
element('sampleSubstanceInput').value = 'acetic acid';
element('standardSolutionNameInput').value = 'NaOH';
element('indicatorSelect').value = 'phenolphthalein';
element('titrationTypeSelect').value = 'weak_acid_strong_base';

vm.runInContext(`
latestConstantsLookup = {
  ambiguous: true,
  candidate_count: 2,
  warning: 'Multiple candidates',
  candidates: [
    { unique_id: 'bad-first', pka_value: 5.3, pka_type: 'pK(0-d)', name: 'Acetic acid', temperature_c: 5 },
    { unique_id: 'good-second', pka_value: 4.76, pka_type: 'pKa1', name: 'Acetic acid', temperature_c: 25 },
  ],
};
selectedConstantsCandidate = null;
`, context);
context.populateConstantsCandidateSelect(vm.runInContext('latestConstantsLookup.candidates', context), true);
context.autoSelectRoomTemperatureCandidate(vm.runInContext('latestConstantsLookup.candidates', context));
const autoPayload = context.buildChemistryMetadataPayload();
if (autoPayload.selected_pka_value !== 4.76) {
  throw new Error(`expected room-temperature candidate pKa 4.76, got ${autoPayload.selected_pka_value}`);
}
if (autoPayload.constants_confirmation_status !== 'auto_selected_room_temperature') {
  throw new Error(`expected auto_selected_room_temperature, got ${autoPayload.constants_confirmation_status}`);
}

element('constantsCandidateSelect').value = '1';
context.selectConstantsCandidate();
const selectedPayload = context.buildChemistryMetadataPayload();
if (selectedPayload.selected_pka_value !== 4.76) {
  throw new Error(`expected explicit candidate pKa 4.76, got ${selectedPayload.selected_pka_value}`);
}
if (selectedPayload.constants_confirmation_status !== 'confirmed_by_user') {
  throw new Error(`expected confirmed_by_user, got ${selectedPayload.constants_confirmation_status}`);
}
console.log('constants room-temperature auto selection regression OK');
