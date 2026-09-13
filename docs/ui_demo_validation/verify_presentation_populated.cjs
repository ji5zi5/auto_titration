const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/ui-demo-browser/node_modules/playwright');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
(async()=>{
 const browser=await chromium.launch({headless:true});
 const root=process.cwd(); const out='/tmp/ui-demo-worker2/populated'; fs.mkdirSync(out,{recursive:true});
 for(const width of [375,768,1024,1440]) for(const remote of [false,true]) {
  const page=await browser.newPage({viewport:{width,height:768},deviceScaleFactor:1});
  await page.route('**/*',async route=>{
   const url=new URL(route.request().url());
   if(url.pathname.startsWith('/stream/') && url.pathname.endsWith('.mjpg')) {
    return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#263344"/><path d="M0 240H640M320 0V480" stroke="#8094ae"/><rect x="160" y="100" width="320" height="280" fill="none" stroke="#ffffff" stroke-width="4"/><text x="320" y="220" fill="white" font-size="24" text-anchor="middle">UI GEOMETRY FIXTURE</text><text x="320" y="265" fill="white" font-size="18" text-anchor="middle">NOT EXPERIMENT DATA</text></svg>'});
   }
   const name=url.pathname==='/'?'index.html':url.pathname.slice(1);
   const file=path.join(root,'website',name);
   if (url.hostname==='ui.test' && !name.includes('..') && fs.existsSync(file) && fs.statSync(file).isFile()){
    const ext=path.extname(file); await route.fulfill({path:file,contentType:({'.html':'text/html','.css':'text/css','.js':'application/javascript','.woff2':'font/woff2'})[ext]||'application/octet-stream'});
   }else await route.fulfill({status:503,contentType:'application/json',body:'{"error":"isolated UI test: no hardware"}'});
  });
  await page.goto('http://ui.test/?remote='+(remote?'1':'0'));
  await page.waitForTimeout(350);
  await page.evaluate(()=>document.fonts.ready);
  if (!remote) {
   await page.waitForFunction(() => ['visiblePreview', 'thermalPreview'].every(id => document.getElementById(id).naturalWidth > 0));
   const fits = await page.evaluate(() => ['visiblePreview', 'thermalPreview'].map(id => {
    const g = imageDrawGeometry(document.getElementById(id));
    return { id, x: g.offsetX, y: g.offsetY };
   }));
   for (const fit of fits) assert(Math.abs(fit.x) < 1 && Math.abs(fit.y) < 1, `letterboxing remained: ${JSON.stringify(fit)}`);
  }
  const data=await page.evaluate(()=>{
   const rect=id=>{const r=document.getElementById(id).getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,b:r.bottom};};
   return {overflow:document.documentElement.scrollWidth>innerWidth, full:rect('viewFullLink'), compact:rect('viewCompactLink'),stop:rect('serialPumpStopButton'),a:rect('visiblePreview'),b:rect('thermalPreview'),font:getComputedStyle(document.getElementById('demoLiveVolume')).fontSize,remote:document.body.classList.contains('remote-control-mode')};
  });
  assert(!data.overflow,JSON.stringify({width,remote,data}));
  assert(data.full.w>0&&data.compact.w>0&&data.full.h>=44);
  assert.equal(data.remote,remote);
  const expectedRemoteRole = remote || width <= 700;
  assert.equal(await page.evaluate(()=>document.body.classList.contains('remote-controller-mode')), expectedRemoteRole);
  if(expectedRemoteRole) {
   assert.equal(await page.locator('#pumpTimelineForm').isVisible(), false);
   assert.equal(await page.locator('#chemistryModelForm').isVisible(), false);
  }
  if(remote) {
   assert(data.stop.b<=768&&data.stop.y>0);
   await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
   assert(await page.locator('#serialPumpStopButton').evaluate(e=>e.getBoundingClientRect().bottom<=innerHeight));
  } else if(width>=768) assert(Math.abs(data.a.y-data.b.y)<2&&data.a.w>250,JSON.stringify(data));
  await page.screenshot({path:out+'/'+width+'-'+(remote?'compact':'full')+'.png',fullPage:true});
  console.log('PASS',width,remote?'compact':'full',JSON.stringify(data));
  if(!remote) {
   await page.locator('.settings-drawer > summary').click();
   assert.equal(await page.locator('#pumpRateInput').isVisible(), !expectedRemoteRole);
   assert.equal(await page.locator('#chemistryModelForm').isVisible(), !expectedRemoteRole);
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:out+'/'+width+'-settings.png',fullPage:true});
   await page.locator('.settings-drawer > summary').click();
   await page.locator('#concentrationCalculationModeButton').click();
   assert(await page.locator('#resultsView').isVisible());
   assert(await page.locator('#viewFullLink').isVisible());
   assert(await page.locator('#viewCompactLink').isVisible());
   assert(await page.locator('#serialPumpStopButton').isVisible());
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:out+'/'+width+'-results.png',fullPage:true});
   console.log('PASS',width,'settings authority '+(expectedRemoteRole?'remote-readonly':'notebook-editable')+', results visibility and no overflow');
  }
  await page.close();
 }
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
