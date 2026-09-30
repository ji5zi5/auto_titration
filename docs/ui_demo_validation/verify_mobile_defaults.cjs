// Hardware-free browser regression: all API requests are intercepted.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || '/tmp/ui-demo-browser/node_modules/playwright');
const fs=require('fs'), path=require('path'), assert=require('assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true});
 try {
  let desktopDefaults;
  for(const width of [1024,375]) {
   const context=await browser.newContext({viewport:{width,height:900},serviceWorkers:'block'});
   let config=null; const writes=[], errors=[];
   await context.addInitScript(()=>{window.EventSource=class{addEventListener(){} close(){}}; window.setInterval=()=>0;});
   await context.route('**/*',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.pathname === '/api/csv') return route.fulfill({
     contentType:'text/csv', headers:{'Content-Disposition':'attachment; filename="experiment.csv"'},
     body:'time_s,visible_color_delta\n0,1\n',
    });
    if(url.pathname.startsWith('/api/')) {
     if(req.method()==='POST') writes.push({path:url.pathname,body:JSON.parse(req.postData())});
     if(url.pathname==='/api/remote/config') {
      if(req.method()==='POST') { const body=JSON.parse(req.postData()); config=body.only_if_missing?body.config:body; }
      return route.fulfill({json:{ok:true,config,defaults_allowed:config===null}});
     }
     if(url.pathname==='/api/csv/start') return route.fulfill({json:{ok:true,csv:{state:'recording',recording:true,session_id:1}}});
     return route.fulfill({json:{ok:true,csv:{state:'idle',recording:false},candidates:[]}});
    }
    if(url.hostname!=='mobile.test') return route.fulfill({status:204});
    const file=path.resolve('website',url.pathname==='/'?'index.html':url.pathname.slice(1));
    if(!file.startsWith(path.resolve('website')+'/')||!fs.existsSync(file)) return route.fulfill({status:404});
    return route.fulfill({body:fs.readFileSync(file),contentType:({'.html':'text/html','.js':'text/javascript','.css':'text/css'})[path.extname(file)]||'application/octet-stream'});
   });
   const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
   await page.goto('http://mobile.test/');
   const payload=await page.evaluate(()=>buildPumpTimelineStartPayload());
   if(width===1024) {
    desktopDefaults=payload;
    const downloads=[];
    page.on('download',download=>downloads.push(download));
    await page.evaluate(()=>{
     applyCsvStatus({state:'recording',recording:true,session_id:1,started_epoch_s:1000,row_count:1});
     applyCsvStatus({state:'stopped',recording:false,session_id:1,started_epoch_s:1000,row_count:2});
     completeCsvStop(latestCsvStatus);
    });
    assert.equal(await page.locator('#resultsView').isVisible(),true);
    await page.waitForTimeout(200);
    assert.equal(downloads.length,0,'stop must not download automatically');
    const download=page.waitForEvent('download');
    await page.locator('#calcCsvDownloadLink').click();
    await download;
    assert.equal(downloads.length,1,'manual CSV button must download once');
   }
   else {
    assert.deepEqual(payload,desktopDefaults,'mobile defaults differ from notebook');
    await page.evaluate(()=>{latestRoiRecordable=true;latestRoiComplete=true;updateCsvControlButtons();});
    await page.locator('#csvStartButton').click();
    await page.waitForFunction(()=>latestCsvStatus?.recording===true);
    assert.deepEqual(writes.find(w=>w.path==='/api/csv/start').body,desktopDefaults);
    assert.equal(writes.filter(w=>w.path==='/api/csv/start').length,1);
    assert.equal(await page.locator('#pumpTimelineForm').isVisible(),false);
   }
   assert.deepEqual(errors,[]); console.log(JSON.stringify({width,defaultsMatch:true,runtimeErrors:errors,mockedStart:writes.some(w=>w.path==='/api/csv/start')}));
   await context.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
