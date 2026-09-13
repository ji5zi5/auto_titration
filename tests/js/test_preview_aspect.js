const fs = require('node:fs');
const harness = fs.readFileSync('tests/js/test_web_request_lifecycle.js', 'utf8')
  .split('(async () => {\n  await testPumpLifecycle();')[0];
eval(harness + `
  const frames = new Map();
  for (const [id, width, height] of [['visiblePreview', 640, 480], ['thermalPreview', 192, 256]]) {
    const frame = { style: {} };
    frames.set(id, frame);
    Object.assign(element(id), { naturalWidth: width, naturalHeight: height, closest: () => frame });
  }
  context.refreshRoiOverlays();
  assert(frames.get('visiblePreview').style.aspectRatio === '640 / 480', 'visible frame ratio not fitted');
  assert(frames.get('thermalPreview').style.aspectRatio === '192 / 256', 'portrait thermal frame ratio not fitted');
  element('visiblePreview').naturalWidth = 0;
  context.refreshRoiOverlays();
  assert(frames.get('visiblePreview').style.aspectRatio === '640 / 480', 'missing image reset valid geometry');
  vm.runInContext('roiDrag = {};', context);
  element('thermalPreview').naturalWidth = 256;
  context.refreshRoiOverlays();
  assert(frames.get('thermalPreview').style.aspectRatio === '192 / 256', 'frame resized during ROI drag');
  console.log('preview aspect: natural dimensions, missing image and ROI drag stability OK');
`);
