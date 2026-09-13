const fs = require('node:fs');
const harness = fs.readFileSync('tests/js/test_web_request_lifecycle.js', 'utf8')
  .split('(async () => {\n  await testPumpLifecycle();')[0];

(async () => {
  for (const narrow of [true, false]) {
    const search = narrow ? '?remote=0' : '?remote=0&remote_control=1';
    const setup = harness
      .replace('AutoTitrationAndroid: {},', `matchMedia: () => ({ matches: ${narrow} }),`)
      .replace("location: { href:", `location: { search: '${search}', href:`)
      .replace('body: { dataset: {}, appendChild() {} }', 'body: { dataset: {}, classList: { add() {} }, appendChild() {} }');
    await eval(setup + `
      (async () => {
        requests.length = 0;
        assert(vm.runInContext('remoteControlMode && !compactViewMode', context), 'full remote role lost');
        context.setPreviewSources();
        assert(element('visiblePreview').src.endsWith('/stream/visible.mjpg'), 'full remote visible preview missing');
        assert(element('thermalPreview').src.endsWith('/stream/thermal.mjpg'), 'full remote thermal preview missing');
        await context.syncRemoteSettings();
        assert(requests.length === 0, 'full remote view overwrote notebook settings');
        context.setAppMode('calculator');
        assert(!element('resultsView').hidden, 'full remote results unavailable');
        context.setAppMode('csv');
        vm.runInContext('latestRoiRecordable=true; latestRoiComplete=true;', context);
        const start = context.startCsvRecording();
        assert(requests[0].url.endsWith('/api/remote/config'), 'full remote start skipped saved config');
        const saved = { pump_rate_ml_per_s: .42, sample_volume_ml: 20 };
        requests[0].resolve({ ok: true, config: saved }); await settle(); await settle();
        assert(JSON.stringify(JSON.parse(requests[1].options.body)) === JSON.stringify(saved), 'full remote start used phone defaults');
        requests[1].resolve({ ok: true, csv: { state: 'recording', recording: true, session_id: 1 } });
        await start;
        requests.length = 0;
        const pending = context.startCsvRecording();
        const stop = context.stopCsvRecording();
        assert(requests[1].url.endsWith('/api/csv/stop'), 'STOP waited on saved config');
        requests[1].resolve({ ok: true, csv: { state: 'stopped', recording: false, session_id: 1 } });
        await stop;
        requests[0].resolve({ ok: true, config: saved }); await pending;
        assert(requests.length === 2, 'stale config started pump after STOP');
      })();
    `);
  }
  console.log('full remote: saved settings preserved, results available, STOP preempts config OK');
})().catch(error => { console.error(error); process.exitCode = 1; });
