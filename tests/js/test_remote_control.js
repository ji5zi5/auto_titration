const fs = require('fs');
let harness = fs.readFileSync('tests/js/test_web_request_lifecycle.js','utf8').split('(async () => {\n  await testPumpLifecycle();')[0];
harness = harness.replace("AutoTitrationAndroid: {},","matchMedia: () => ({ matches: true }),")
  .replace("body: { dataset: {}, appendChild() {} }","body: { dataset: {}, classList: { add() {} }, appendChild() {} }");
eval(harness + `
(async()=>{
 requests.length=0;
 vm.runInContext('latestRoiRecordable=true;latestRoiComplete=true;', context);
 assert(vm.runInContext('remoteControlMode',context),'phone not remote');
 const saved={pump_rate_ml_per_s:.42,titration_type:'weak_acid_strong_base',auto_stop_enabled:true,sample_volume_ml:20};
 const start=context.startCsvRecording();
 assert(requests.length===1 && requests[0].url.endsWith('/api/remote/config'),'missing server configuration fetch');
 requests[0].resolve({ok:true,config:saved});await settle();await settle();
 assert(requests.length===2,'no start request after config');
 assert(JSON.stringify(JSON.parse(requests[1].options.body))===JSON.stringify(saved),'phone defaults overwrote saved config');
 requests[1].resolve({ok:true,csv:{state:'recording',recording:true,session_id:1}});
 await start;await settle();
 context.setAppMode('calculator');
 assert(!element('csvStartButton').hidden,'remote controls hidden after result switch');
 requests.length=0;
 const pending=context.startCsvRecording();
 assert(requests[0].url.endsWith('/api/remote/config'),'expected config');
 const stop=context.stopCsvRecording();
 assert(requests[1].url.endsWith('/api/csv/stop'),'stop waited for settings');
 requests[1].resolve({ok:true,csv:{state:'stopped',recording:false,session_id:1}});
 await stop;
 requests[0].resolve({ok:true,config:saved});await pending;
 assert(requests.length===2,'cancelled config started motor');
 assert(autoDownloadClicks===0,'phone auto-downloaded');
 console.log('remote saved settings and STOP preemption OK');
})().catch(e=>{console.error(e);process.exitCode=1;});
`);
