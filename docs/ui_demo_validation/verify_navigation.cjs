const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/tmp/ui-demo-browser/node_modules/playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const visualRoot = process.env.VISUAL_ROOT || path.resolve('website');
const navRoot = process.env.NAV_ROOT || path.resolve('website');
const output = process.env.OUTPUT || '/tmp/ui-demo-browser/evidence';
fs.mkdirSync(output, { recursive: true });
const summary = [];
(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    for (const width of [375, 768, 1024, 1440]) {
      const context = await browser.newContext({ viewport: { width, height: 900 }, reducedMotion: 'reduce', serviceWorkers: 'block' });
      const requests = [];
      const errors = [];
      let power = { supported: true, enabled: true, requested_enabled: true, state: 'on' };
      // No SSE socket or physical collector can be opened in this harness.
      await context.addInitScript(() => {
        window.EventSource = class { addEventListener() {} close() {} };
      });
      await context.route('**/*', async route => {
        const request = route.request();
        const url = new URL(request.url());
        if (url.pathname.startsWith('/api/')) {
          requests.push({ method: request.method(), path: url.pathname, body: request.postData() });
          if (url.pathname === '/api/camera-power') {
            const { enabled } = JSON.parse(request.postData());
            assert.equal(typeof enabled, 'boolean');
            power = { supported: true, enabled, requested_enabled: enabled, state: enabled ? 'on' : 'off' };
            return route.fulfill({ json: { ok: true, camera_power: power } });
          }
          if (url.pathname === '/api/roi-unlock') return route.fulfill({ json: { ok: true, roi: { roi_state: 'setup', roi_locked: false, roi_complete: false, visible_roi: '', thermal_roi: '' } } });
          return route.fulfill({ json: { ok: true, camera_power: power, config: null, csv: { state: 'idle', recording: false } } });
        }
        if (url.hostname !== 'ui-demo.test') return route.fulfill({ status: 204 });
        const name = url.pathname === '/dashboard' ? 'index.html' : url.pathname.slice(1);
        const root = name === 'app.js' ? navRoot : visualRoot;
        const file = path.resolve(root, name);
        if (!file.startsWith(path.resolve(root) + '/') || !fs.existsSync(file)) return route.fulfill({ status: 404 });
        const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.svg': 'image/svg+xml' };
        return route.fulfill({ body: fs.readFileSync(file), contentType: types[path.extname(file)] || 'application/octet-stream' });
      });
      const page = await context.newPage();
      page.on('pageerror', error => errors.push(error.message));
      async function verifyRemoteView(compact) {
        assert.equal(await page.evaluate(() => remoteControlMode), true, 'layout switch lost remote ownership');
        await page.evaluate(() => syncRemoteSettings());
        const drawer = page.locator('.settings-drawer');
        await drawer.evaluate(el => { el.open = true; });
        assert.equal(await page.locator('#pumpTimelineForm').isVisible(), false);
        assert.equal(await page.locator('#chemistryModelForm').isVisible(), false);
        await drawer.evaluate(el => { el.open = false; });
        for (const [id, suffix] of [['visiblePreview', '/stream/visible.mjpg'], ['thermalPreview', '/stream/thermal.mjpg']]) {
          const src = await page.locator('#' + id).getAttribute('src');
          assert.equal(Boolean(src && src.endsWith(suffix)), !compact, `${id}: incorrect stream selection`);
        }
        assert.deepEqual(requests.filter(r => r.method !== 'GET' && r.path !== '/api/chemistry/constants/lookup'), [], 'remote view wrote config/control');
      }
      await page.goto(`https://ui-demo.test/dashboard?remote=${width === 375 ? '0' : '1'}&backend=%2Fproxy&tag=a&tag=b#roi`);
      await page.waitForFunction(() => document.getElementById('viewFullLink')?.href.includes('backend='));
      await page.evaluate(() => document.fonts.ready);
      assert.equal(await page.locator('#titrationTypeSelect').inputValue(), 'strong_acid_strong_base');
      assert.equal(await page.locator('#sampleSubstanceInput').inputValue(), 'hydrochloric acid');
      assert.equal(await page.locator('#sampleVolumeInput').inputValue(), '20.00');
      assert.equal(await page.locator('#sampleConcentrationInput').inputValue(), '0.100');
      assert.equal(await page.locator('#standardConcentrationInput').inputValue(), '0.100');
      assert.equal(await page.locator('#roiAutoSetupButton').evaluate(el => el.parentElement.classList.contains('roi-record-controls')), true);
      assert.equal(await page.locator('.settings-drawer #roiAutoSetupButton').count(), 0);
      assert.equal(await page.locator('#csvCollectionControls .download-button').count(), 0, 'CSV download belongs only in results');
      assert.equal(await page.locator('.roi-record-controls > :last-child').getAttribute('id'), 'roiAutoSetupButton');
      assert.equal(await page.evaluate(() => remoteControlMode), true);
      await page.evaluate(() => syncRemoteSettings());
      for (const id of ['visiblePreview', 'thermalPreview']) {
        for (const event of ['error', 'load', 'error']) {
          await page.locator('#' + id).dispatchEvent(event);
          assert.equal(await page.locator('#' + id).getAttribute('data-stream-state'), event);
        }
      }
      for (const [id, remote, name] of [['viewCompactLink', true, 'compact'], ['viewFullLink', false, 'full']]) {
        await page.locator('#' + id).click();
        await page.waitForFunction(expected => document.body.classList.contains('remote-control-mode') === expected, remote);
        await verifyRemoteView(remote);
        const url = new URL(page.url());
        assert.equal(url.hash, '#roi');
        assert.equal(url.searchParams.get('backend'), '/proxy');
        assert.deepEqual(url.searchParams.getAll('tag'), ['a', 'b']);
        assert.equal(await page.locator('#viewFullLink').isVisible(), true);
        assert.equal(await page.locator('#viewCompactLink').isVisible(), true);
        assert.equal(await page.locator('#serialPumpStopButton').isVisible(), true);
        const rows = await page.evaluate(() => ({
          first: document.querySelector('.roi-record-controls').getBoundingClientRect().bottom,
          pump: document.querySelector('.pump-controls').getBoundingClientRect().top,
          positions: ['serialPumpDispenseButton','serialPumpRetractButton','serialPumpStopButton'].map(id => document.getElementById(id).getBoundingClientRect().top),
        }));
        assert(rows.pump >= rows.first && rows.positions.every(y => Math.abs(y - rows.positions[0]) < 1), 'pump controls must form their own second row');
        if (remote) {
          const stop = await page.locator('#serialPumpStopButton').boundingBox();
          assert(stop.x >= 0 && stop.x + stop.width <= width && stop.y >= 0 && stop.y + stop.height <= 900, `${width}: STOP below initial viewport`);
          const dispense = await page.locator('#serialPumpDispenseButton').boundingBox();
          const panel = await page.locator('#csvPanel').boundingBox();
          assert.equal(await page.locator('#serialPumpStopButton').evaluate(el => getComputedStyle(el).position), 'static');
          assert(Math.abs(stop.width - dispense.width) < 1 && Math.abs(stop.height - dispense.height) < 1, 'STOP must match other pump button sizes');
          assert(stop.y >= panel.y && stop.y + stop.height <= panel.y + panel.height, 'STOP must remain in the control panel');
        }
        await page.evaluate(() => applyLiveMetadata({}));
        assert.equal(await page.locator('#temperatureValue').textContent(), '-');
        const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
        assert.equal(overflow, false, `${width} ${name}: horizontal overflow`);
        await page.screenshot({ path: path.join(output, `${width}-${name}-idle.png`), fullPage: true });
        await page.reload();
        assert.equal(await page.locator('body').evaluate(el => el.classList.contains('remote-control-mode')), remote);
        await verifyRemoteView(remote);
      }
      await page.evaluate(() => updateDemoCsvStatus({
        state: 'stopped', recording: false, session_id: 'browser-fixture', started_epoch_s: 1000,
        injected_volume_ml: 9.82, predicted_equivalence_status: 'available', predicted_equivalence_volume_ml: 9.8,
        sample_concentration_from_predicted_equivalence_M: 0.098,
        auto_stop_state: 'triggered', auto_stop_reason: 'persistent_color_change',
      }));
      assert.equal(await page.locator('#calcFinalVolumeValue').textContent(), '9.820');
      assert.equal(await page.locator('#calcSampleConcentrationValue').textContent(), '0.09800');
      await page.locator('#concentrationCalculationModeButton').click();
      assert.equal(await page.locator('#resultsView').isVisible(), true);
      assert.equal(await page.locator('#calcCsvDownloadLink').isVisible(), true);
      assert.equal(await page.locator('.demo-stage').isVisible(), false, 'results retained redundant live status');
      await page.screenshot({ path: path.join(output, `${width}-full-result-fixture.png`), fullPage: true });
      const motion = requests.filter(r => r.method !== 'GET' && r.path !== '/api/chemistry/constants/lookup');
      assert.deepEqual(motion, [], 'navigation issued control commands');
      // Explicit ROI deletion, distinct from side-effect-free navigation above.
      await page.locator('#csvCollectionModeButton').click();
      await page.evaluate(() => applyRoiStatus({ roi_state: 'setup', roi_locked: false, roi_complete: true, visible_roi: '1,2,3,4', thermal_roi: '5,6,7,8' }));
      const beforeReset = requests.length;
      await page.locator('#roiResetButton').click();
      await page.waitForFunction(() => latestLiveMetadata.visible_roi === '' && latestLiveMetadata.thermal_roi === '');
      assert(requests.slice(beforeReset).some(r => r.path === '/api/roi-unlock' && JSON.parse(r.body).reset === true));
      assert(requests.slice(beforeReset).every(r => !r.path.startsWith('/api/pump/') && !r.path.startsWith('/api/csv/')), 'ROI deletion triggered pump/recording');
      await page.evaluate(() => applyRoiStatus({ roi_state: 'recording', roi_locked: true }));
      assert.equal(await page.locator('#roiResetButton').isDisabled(), true);
      assert.equal(await page.locator('#cameraPowerButton').isDisabled(), true, 'recording allowed camera shutdown');
      await page.evaluate(() => applyRoiStatus({ roi_state: 'setup', roi_locked: false, roi_complete: false }));
      await page.locator('#cameraPowerButton').click();
      await page.waitForFunction(() => document.getElementById('cameraPowerButton').textContent === '카메라 켜기');
      assert.equal(await page.locator('#visiblePreview').getAttribute('src'), null);
      assert.equal(await page.locator('#thermalPreview').getAttribute('src'), null);
      assert.equal(await page.locator('#csvStartButton').isDisabled(), true);
      await page.screenshot({ path: path.join(output, `${width}-full-camera-off.png`), fullPage: true });
      await page.locator('#cameraPowerButton').click();
      await page.waitForFunction(() => document.getElementById('cameraPowerButton').textContent === '카메라 끄기');
      assert((await page.locator('#visiblePreview').getAttribute('src')).endsWith('/stream/visible.mjpg'));
      assert.equal(requests.filter(r => r.path === '/api/camera-power').length, 2);
      // Exercise the actual shared navigation/CSS with a native bridge marker.
      // Native device operations are outside this browser-only regression.
      await page.route('**/android-webview.js', route => route.fulfill({ contentType: 'text/javascript', body: '' }));
      await context.addInitScript(() => { window.AutoTitrationAndroid = {}; });
      await page.reload();
      for (const id of ['viewFullLink', 'viewCompactLink']) {
        assert.equal(await page.locator('#' + id).evaluate(el => el.hidden), true);
        assert.equal(await page.locator('#' + id).isVisible(), false, 'native view link remained clickable');
      }
      assert.equal(await page.locator('#roiResetButton').isVisible(), false, 'unsupported native ROI deletion exposed');
      assert.equal(await page.locator('#cameraPowerButton').isVisible(), false, 'unsupported native camera power exposed');
      assert.deepEqual(errors, [], 'browser runtime errors');
      summary.push({ width, status: 'PASS', screenshots: 4, apiRequests: requests.length, controlCommands: motion.length, runtimeErrors: errors });
      await context.close();
    }
    fs.writeFileSync(path.join(output, 'summary.json'), JSON.stringify({ fixtureOnly: true, noRealNetwork: true, summary }, null, 2));
    console.log(JSON.stringify(summary, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
