const fs = require('node:fs');
const { execFileSync } = require('node:child_process');
const fixture = JSON.parse(execFileSync('python3', ['-m', 'tests.graph_payload_fixture'], {encoding:'utf8'}));
const harness = fs.readFileSync('tests/js/test_web_request_lifecycle.js', 'utf8')
  .split('(async () => {\n  await testPumpLifecycle();')[0]
  .replace('AutoTitrationAndroid: {},', "AutoTitrationAndroid: {}, AutoTitrationDemoView: require('../../website/demo-view.js'),");
eval(harness + `
for (const legacy of [false, true]) {
  context.resetDemoViewForBackend();
  context.applyCsvStatus(fixture.initial, {source:'post'});
  fixture.frames.forEach(frame => {
    const data={...frame};
    if (legacy) delete data.csv_session_id;
    context.applyLiveMetadata(data);
  });
  assert(vm.runInContext('demoViewState.samples.length',context)===81,'collector measurements lost');
  assert(vm.runInContext('demoViewState.samples[0].thermalC',context)===24,'trusted temperature lost');
  context.applyLiveMetadata(fixture.finalizing);
  context.applyLiveMetadata(fixture.stopped);
  assert(vm.runInContext('demoViewState.samples.length',context)===81,'stop erased graph');
  assert(!element('resultsView').hidden,'stop did not reveal results');
  assert(autoDownloadClicks===0,'graph completion downloaded automatically');
}
// Legacy compatibility is not permission to attach unidentified or stale frames.
context.resetDemoViewForBackend();
context.applyCsvStatus(fixture.initial, {source:'post'});
const unknown={...fixture.frames[0]}; delete unknown.csv_session_id;
delete unknown.csv_recording_started_epoch_s;
context.updateDemoLiveSample(unknown,true);
assert(vm.runInContext('demoViewState.samples.length',context)===0,'unidentified frame accepted');
unknown.csv_recording_started_epoch_s=999;
context.updateDemoLiveSample(unknown,true);
assert(vm.runInContext('demoViewState.samples.length',context)===0,'old-session frame accepted');
const untrusted={...fixture.frames[0],celsius_allowed:false};
context.applyLiveMetadata(untrusted);
assert(vm.runInContext('demoViewState.samples[0].thermalC',context)===null,'untrusted Celsius plotted');
assert(vm.runInContext('demoViewState.samples[0].color',context)!==null,'thermal failure suppressed color');
console.log('collector graph contract: real payloads, legacy timestamp guard, stop retention, trusted Celsius OK');
`);
