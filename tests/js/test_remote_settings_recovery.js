const fs = require('node:fs');
const harness = fs.readFileSync('tests/js/test_web_request_lifecycle.js', 'utf8')
  .split('(async () => {\n  await testPumpLifecycle();')[0]
  .replace('AutoTitrationAndroid: {},', 'matchMedia: () => ({ matches: true }),')
  .replace('body: { dataset: {}, appendChild() {} }',
    'body: { dataset: {}, classList: { add() {} }, appendChild() {} }');
eval(harness + `
(async () => {
  const defaults = {pump_rate_ml_per_s:.99, titration_type:'strong_acid_strong_base', sample_volume_ml:20};
  const saved = {...defaults, pump_rate_ml_per_s:.42};
  context.buildPumpTimelineStartPayload = () => defaults;
  vm.runInContext('latestRoiRecordable=true; latestRoiComplete=true;', context);
  for (const config of [null, saved]) {
    requests.length = 0;
    const start = context.startCsvRecording();
    assert(context.startCsvRecording() === start, 'duplicate start was not suppressed');
    requests[0].resolve({ok:true, config, defaults_allowed:config===null}); await settle(); await settle();
    assert(requests[1].url.endsWith('/api/csv/start'), 'recording did not continue');
    assert(JSON.stringify(JSON.parse(requests[1].options.body)) === JSON.stringify(config || defaults), 'recording ignored notebook configuration/defaults');
    requests[1].resolve({ok:true, csv:{state:'recording', recording:true}}); await start;
    assert(requests.length === 2, 'phone wrote notebook settings');
  }
  for (const response of [
    {payload:{ok:true, config:null, defaults_allowed:false}},
    {payload:{ok:false}, options:{ok:false,status:503}},
  ]) {
    requests.length = 0;
    const start = context.startCsvRecording();
    requests[0].resolve(response.payload, response.options); await start;
    assert(requests.length === 1, 'invalid settings or network failure used defaults');
  }
  context.buildPumpTimelineStartPayload = () => {throw Error('invalid input');};
  requests.length = 0;
  const invalid = context.startCsvRecording();
  requests[0].resolve({ok:true, config:null}); await invalid;
  assert(requests.length === 1, 'invalid defaults started recording');
  context.buildPumpTimelineStartPayload = () => defaults;
  for (const cancel of ['stop', 'backend']) {
    requests.length = 0;
    vm.runInContext('latestRoiRecordable=true; latestRoiComplete=true;', context);
    const start = context.startCsvRecording();
    if (cancel === 'stop') {
      const stop = context.stopCsvRecording();
      requests[1].resolve({ok:true,csv:{state:'stopped',recording:false}}); await stop;
    } else context.resetDemoViewForBackend();
    const count = requests.length;
    requests[0].resolve({ok:true,config:null}); await start;
    assert(requests.length === count, 'cancelled config request started recording');
  }
  console.log('remote defaults: notebook builder, saved-setting priority, invalidation and STOP/backend fences OK');
})().catch(error => {console.error(error); process.exitCode=1;});
`);
