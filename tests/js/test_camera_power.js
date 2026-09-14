const fs = require('node:fs');
let harness = fs.readFileSync('tests/js/test_web_request_lifecycle.js', 'utf8')
  .split('(async () => {\n  await testPumpLifecycle();')[0]
  .replace('AutoTitrationAndroid: {},', '');
eval(harness + `
(async () => {
  for (const id of ['visiblePreview','thermalPreview']) Object.assign(element(id), {
    getAttribute(name) { return this[name] || null; }, removeAttribute(name) { delete this[name]; }
  });
  requests.length = 0;
  context.setPreviewSources();
  context.applyCameraPowerStatus({supported:true,enabled:true,state:'on'});
  const off = context.toggleCameraPower();
  assert(requests[0].url.endsWith('/api/camera-power'),'missing power endpoint');
  assert(JSON.parse(requests[0].options.body).enabled===false,'wrong OFF command');
  await context.toggleCameraPower();
  assert(requests.length===1,'duplicate power request');
  requests[0].resolve({ok:true,camera_power:{supported:true,enabled:true,requested_enabled:false,state:'stopping'}});
  await off;
  assert(element('cameraPowerButton').disabled,'transition button enabled');
  assert(!element('visiblePreview').src && !element('thermalPreview').src,'OFF did not disconnect previews');
  assert(element('csvStartButton').disabled,'recording allowed while camera unavailable');
  const beforeRoi = requests.length;
  assert(await context.enterRoiSetupMode() === false,'ROI setup allowed on a stopped camera');
  assert(requests.length === beforeRoi,'stopped camera setup sent ROI/settings request');
  context.refreshRoiOverlays();
  assert(element('visibleRoiOverlay').style.display === 'none','stale ROI overlay remains while OFF');
  context.applyCameraPowerStatus({supported:true,enabled:false,state:'off'});
  assert(element('cameraPowerButton').textContent==='카메라 켜기','no ON action');
  context.applyCameraPowerStatus({supported:true,enabled:true,state:'on'});
  assert(element('visiblePreview').src.endsWith('/stream/visible.mjpg'),'visible stream did not return');
  vm.runInContext("latestCsvStatus={recording:true};",context);
  context.updateCameraPowerButton();
  assert(element('cameraPowerButton').disabled,'camera OFF enabled while recording');
  requests.length=0;
  await context.toggleCameraPower();
  assert(requests.length===0,'recording sent camera power command');
  vm.runInContext('latestCsvStatus=null;',context);
  const stale=context.toggleCameraPower();
  const request=requests[0];
  context.resetDemoViewForBackend();
  request.resolve({ok:true,camera_power:{supported:true,enabled:false,state:'off'}});
  await stale;
  assert(vm.runInContext('cameraPowerStatus===null',context),'old backend power response accepted');
  console.log('camera power: confirmed states, preview disconnect, recording guard, dedupe and backend fence OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
`);
