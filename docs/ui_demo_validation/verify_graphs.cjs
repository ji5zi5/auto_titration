// Real collector serialization -> browser SSE callback -> visible canvas pixels.
// All network requests are intercepted. No physical collector or pump is contacted.
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/ui-demo-browser/node_modules/playwright');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const frameCount = Number(process.env.GRAPH_FRAME_COUNT || 81);
const fps = Number(process.env.GRAPH_FPS || 4);
const fixture = JSON.parse(execFileSync('python3', ['-m', 'tests.graph_payload_fixture', String(frameCount), String(fps)], { encoding:'utf8', maxBuffer:32*1024*1024 }));
const retained = Math.min(frameCount, 1500);
const output = process.env.OUTPUT || '/tmp/graph-validation';
fs.mkdirSync(output, { recursive:true });
(async () => {
  const browser = await chromium.launch({ headless:true });
  const summary = [];
  try {
    for (const [width, legacy] of [[1024,false],[390,false],[1024,true]]) {
      const context = await browser.newContext({viewport:{width,height:900}, serviceWorkers:'block'});
      const errors = [], requests = [], downloads = [];
      await context.addInitScript(() => {
        window.setInterval = () => 0;
        window.EventSource = class {
          constructor() { window.testEvents = this; this.listeners = {}; }
          addEventListener(name, callback) { this.listeners[name] = callback; }
          close() {}
        };
      });
      await context.route('**/*', async route => {
        const req=route.request(), url=new URL(req.url());
        if (url.pathname.startsWith('/api/')) {
          requests.push({path:url.pathname,method:req.method()});
          return route.fulfill({json:{ok:true,config:null,candidates:[],csv:{state:'idle',recording:false}}});
        }
        if (url.hostname !== 'graphs.test') return route.fulfill({status:204});
        const file=path.resolve('website',url.pathname === '/' ? 'index.html' : url.pathname.slice(1));
        if (!file.startsWith(path.resolve('website')+'/') || !fs.existsSync(file)) return route.fulfill({status:404});
        return route.fulfill({body:fs.readFileSync(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css','.woff2':'font/woff2'})[path.extname(file)] || 'application/octet-stream'});
      });
      const page = await context.newPage();
      page.on('pageerror', e=>errors.push(e.message));
      page.on('download', d=>downloads.push(d));
      await page.goto('http://graphs.test/?remote=0');
      await page.waitForTimeout(150);
      const result = await page.evaluate(({fixture,legacy}) => {
        const emit = payload => {
          const data = {...payload};
          if (legacy) delete data.csv_session_id;
          window.testEvents.listeners.live({data:JSON.stringify(data)});
        };
        applyCsvStatus(fixture.initial, {source:'post'});
        fixture.frames.forEach(emit);
        const beforeStop = demoViewState.samples.length;
        emit(fixture.finalizing);
        emit(fixture.stopped);
        const pixels = (id, rgb) => {
          const canvas=document.getElementById(id);
          const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
          let count=0;
          for(let i=0;i<data.length;i+=4) {
            if(data[i+3]>200 && rgb.every((c,k)=>Math.abs(data[i+k]-c)<10)) count++;
          }
          return count;
        };
        return {
          beforeStop, afterStop:demoViewState.samples.length,
          first:demoViewState.samples[0], last:demoViewState.samples.at(-1),
          colorPixels:pixels('colorTrendCanvas',[0,102,204]),
          thermalPixels:pixels('thermalTrendCanvas',[181,71,8]),
          resultVisible:!document.getElementById('resultsView').hidden,
          status:document.getElementById('previewStatus').textContent,
          emptyColor:!document.getElementById('colorTrendEmpty').hidden,
          emptyThermal:!document.getElementById('thermalTrendEmpty').hidden,
          result:demoViewState.result,
        };
      }, {fixture,legacy});
      await page.locator('#resultsView').screenshot({path:path.join(output,`${width}-${legacy?'legacy':'current'}-results.png`)});
      summary.push({width,legacy,...result,errors,downloads:downloads.length});
      fs.writeFileSync(path.join(output,'summary.json'),JSON.stringify(summary,null,2));
      assert.equal(result.beforeStop,retained,'collector frames never reached the graph');
      assert.equal(result.afterStop,retained,'stop discarded graph history');
      assert.equal(result.resultVisible,true,'results did not open');
      assert.equal(result.first.x,fixture.frames.at(-retained).csv_recording_elapsed_s);
      assert.equal(result.last.x,fixture.frames.at(-1).csv_recording_elapsed_s);
      assert(result.colorPixels>100,'color trace not painted');
      assert(result.thermalPixels>100,'thermal trace not painted');
      assert.equal(result.emptyColor,false); assert.equal(result.emptyThermal,false);
      assert.equal(result.result.concentrationM,.099);
      assert.equal(downloads.length,0,'stop auto-downloaded CSV');
      assert.deepEqual(errors,[]);
      assert(!requests.some(r=>r.method !== 'GET' && (r.path.startsWith('/api/pump/') || r.path.startsWith('/api/csv/'))), 'verification sent a control request');
      await context.close();
    }
    console.log(JSON.stringify(summary,null,2));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
