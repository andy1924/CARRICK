const {test,expect}=require('playwright/test');
const fs=require('fs');
const path=require('path');
const schedule=path.join(__dirname,'../../data/samples/pump-station.xer');
const password='Isolated-fixture-password-2026';
const scan=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1kAAAAASUVORK5CYII=','base64');
let errors=[];
test.beforeEach(async({page})=>{
  errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/app');
  await expect(page.locator('#auth-form')).toHaveAttribute('data-setup',/true|false/);
  if(await page.locator('#auth-form').getAttribute('data-setup')==='true')await page.locator('#auth-name').fill('Fixture Owner');
  await page.locator('#auth-email').fill('owner@example.test');await page.locator('#auth-password').fill(password);await page.locator('#auth-submit').click();
  await expect(page.locator('#auth-panel')).toBeHidden();await expect(page.locator('#metrics .metric')).toHaveCount(4);await expect(page.locator('#workspace-status')).toBeHidden();
});
test.afterEach(()=>expect(errors,'No dashboard runtime errors').toEqual([]));
async function importSchedule(page){await page.locator('[data-view="schedule"]').click();await page.locator('#schedule-file').setInputFiles(schedule);await expect(page.locator('#import-schedule')).toBeEnabled();await expect(page.locator('#schedule-result-count')).toHaveText('12 activities');await page.locator('[data-view="capture"]').click();await page.locator('#report-date').fill('2026-10-01');await page.locator('#ai-mode').uncheck();}
async function approve(page,id){await page.locator('[data-view="review"]').click();const card=page.locator('.review-card').filter({has:page.locator(`.candidate-choice[value="${id}"]`)}).first();await card.locator('.candidate-select').selectOption(id);await card.locator('.decision-reason').fill('Fixture planner checked source and dependencies');await expect(card.locator('.approve-button')).toBeEnabled();await card.locator('.approve-button').click();await expect(card).toHaveCount(0);}
async function submitText(page,text){await page.locator('[data-view="capture"]').click();await page.locator('#report-text').fill(text);await page.locator('#report-form button[type=submit]').click();await expect(page.locator('#report-text')).toHaveValue('');}

test('dashboard initializes and schedule import displays activities',async({page})=>{await importSchedule(page);await page.locator('[data-view="overview"]').click();await expect(page.locator('#schedule-chip')).toContainText('12 activities');});
test('text review, approval, CSV and XER exports, and XER reimport',async({page})=>{
  await importSchedule(page);await submitText(page,'Main foundation concrete pour finished today');await approve(page,'CV-102');await page.locator('[data-view="exports"]').click();await page.locator('#create-export').click();await expect(page.locator('#export-result')).toContainText('Your export is ready');
  const [csv]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'Download progress CSV →'}).click()]);expect(fs.readFileSync(await csv.path(),'utf8')).toContain('CV-102,actual_finish,2026-10-01');
  const [xer]=await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'Download updated XER →'}).click()]);const content=fs.readFileSync(await xer.path());expect(content.toString()).toContain('TK_Complete');
  await page.locator('[data-view="schedule"]').click();await page.locator('#schedule-file').setInputFiles({name:'reviewed-progress.xer',mimeType:'application/octet-stream',buffer:content});await expect(page.locator('#schedule-title')).toHaveText('reviewed-progress.xer');await expect(page.locator('#schedule-result-count')).toHaveText('12 activities');
});
test('scan upload and native microphone recording reach review and export',async({page})=>{
  await importSchedule(page);await page.locator('#document-file').setInputFiles({name:'site-scan.png',mimeType:'image/png',buffer:scan});await expect(page.locator('#document-pages textarea')).toHaveValue('North pipeline welding started today');await page.locator('#document-submit').click();await expect(page.locator('#document-review')).toBeHidden();await approve(page,'PI-301');
  await page.locator('[data-view="capture"]').click();await page.locator('#voice-record').click();await expect(page.locator('#voice-record')).toHaveText('Stop recording');await page.waitForTimeout(1100);await page.locator('#voice-record').click();await expect(page.locator('#voice-preview')).toBeVisible();await page.locator('#voice-transcribe').click();await expect(page.locator('#voice-text')).toHaveValue('South pipeline welding started today');await page.locator('#voice-use').click();await page.locator('#report-form button[type=submit]').click();await expect(page.locator('#report-text')).toHaveValue('');await approve(page,'PI-302');
  await page.locator('[data-view="exports"]').click();await expect(page.locator('#export-count')).toContainText('2 approved events');await page.locator('#create-export').click();await expect(page.locator('#export-result')).toContainText('2 approved events');
});
test('offline outbox survives reload and syncs once connectivity returns',async({page,context})=>{
  await importSchedule(page);await page.evaluate(()=>navigator.serviceWorker.ready);await page.waitForFunction(()=>!!navigator.serviceWorker.controller);await context.setOffline(true);await page.locator('#report-text').fill('Low voltage cable installation started today');await page.locator('#report-form button[type=submit]').click();await expect(page.locator('#device-reports-list')).toContainText('Waiting to sync');await page.reload();await expect(page.locator('#connection-banner')).toContainText('Working offline');await page.locator('[data-view="capture"]').click();await expect(page.locator('#device-reports-list')).toContainText('Waiting to sync');await context.setOffline(false);await page.locator('#sync-now').click();await expect(page.locator('#device-reports-list')).toContainText('No reports or attachments');await page.locator('[data-view="history"]').click();await expect(page.locator('#history-list')).toContainText('Low voltage cable installation started today');
});
test('AI failure retains submission and standard matching recovers it',async({page})=>{
  await importSchedule(page);await page.locator('#ai-mode').check();await page.locator('#report-text').fill('PROVIDER_DOWN Hydrotest North Pipeline started today');await page.locator('#report-form button[type=submit]').click();await expect(page.locator('#device-reports-list')).toContainText('Mock provider is unavailable');await page.locator('[data-fallback-report]').click();await expect(page.locator('#device-reports-list')).toContainText('No reports or attachments');await page.locator('[data-view="history"]').click();await expect(page.locator('#history-list')).toContainText('PROVIDER_DOWN Hydrotest');
});
test('failed OCR keeps its original and supports reviewed manual transcription',async({page})=>{
  await importSchedule(page);await page.locator('#document-file').setInputFiles({name:'unavailable-scan.png',mimeType:'image/png',buffer:scan});await expect(page.locator('#document-pages')).toContainText('Original retained');await page.locator('#document-pages textarea').fill('North pipeline welding started today');await page.locator('#document-submit').click();await expect(page.locator('#document-review')).toBeHidden();await approve(page,'PI-301');
});
test('server-retained report can recover after device outbox is cleared',async({page})=>{
  await importSchedule(page);await page.locator('#ai-mode').check();await page.locator('#report-text').fill('PROVIDER_DOWN Low voltage cable installation started today');await page.locator('#report-form button[type=submit]').click();await expect(page.locator('#device-reports-list')).toContainText('Mock provider is unavailable');
  await page.evaluate(async()=>{for(const item of await window.CarrickOffline.list('outbox'))await window.CarrickOffline.remove('outbox',item.id);});await page.reload();await expect(page.locator('#auth-panel')).toBeHidden();await page.locator('[data-view="capture"]').click();await expect(page.locator('#server-recovery-list')).toContainText('Saved on server');await page.locator('[data-standard-server]').click();await expect(page.locator('#server-recovery-list')).not.toContainText('Saved on server');await page.locator('[data-view="history"]').click();await expect(page.locator('#history-list')).toContainText('PROVIDER_DOWN Low voltage');
});
test('offline report requires explicit rebind after a new schedule import',async({page,context,browser})=>{
  await importSchedule(page);await context.setOffline(true);await page.locator('#report-text').fill('Low voltage cable installation started today');await page.locator('#report-form button[type=submit]').click();await expect(page.locator('#device-reports-list')).toContainText('Waiting to sync');
  const otherContext=await browser.newContext();const other=await otherContext.newPage();await other.goto('/app');await expect(other.locator('#auth-form')).toHaveAttribute('data-setup','false');await other.locator('#auth-email').fill('owner@example.test');await other.locator('#auth-password').fill(password);await other.locator('#auth-submit').click();await expect(other.locator('#auth-panel')).toBeHidden();
  await other.evaluate(async content=>{await fetch('/api/schedules/import',{method:'POST',headers:{'Content-Type':'application/json',...window.CarrickAuth.headers()},body:JSON.stringify({filename:'revised.xer',content})});},fs.readFileSync(schedule,'utf8'));await otherContext.close();
  await context.setOffline(false);await page.locator('#sync-now').click();await expect(page.locator('#device-reports-list')).toContainText('Schedule changed');await expect(page.locator('#schedule-chip')).toContainText('revised.xer');page.on('dialog',dialog=>dialog.accept());await page.locator('[data-rebind-report]').click();await expect(page.locator('#device-reports-list')).toContainText('No reports or attachments');await page.locator('[data-view="history"]').click();await expect(page.locator('#history-list')).toContainText('Low voltage cable installation started today');
});
test('retained scan supports manual recovery after device drafts are lost',async({page})=>{
  await importSchedule(page);await page.locator('#document-file').setInputFiles({name:'unavailable-scan.png',mimeType:'image/png',buffer:scan});await expect(page.locator('#document-pages')).toContainText('Original retained');
  await page.evaluate(async()=>{for(const draft of await window.CarrickOffline.list('drafts'))await window.CarrickOffline.remove('drafts',draft.id);});await page.reload();await expect(page.locator('#auth-panel')).toBeHidden();await page.locator('[data-view="capture"]').click();await expect(page.locator('#server-recovery-list')).toContainText('Saved original');await page.locator('[data-open-source]').click();await expect(page.locator('#document-pages')).toContainText('Original retained');await page.locator('#document-pages textarea').fill('North pipeline welding started today');await page.locator('#document-submit').click();await expect(page.locator('#document-review')).toBeHidden();await approve(page,'PI-301');
});
test('initial owner inherits legacy device drafts without deleting the original',async({page})=>{
  await page.evaluate(async()=>{
    await window.CarrickOffline.remove('snapshots','legacy-imported');
    await new Promise((resolve,reject)=>{const request=indexedDB.open('carrick-device',1);request.onupgradeneeded=()=>{for(const name of ['drafts','outbox','snapshots'])if(!request.result.objectStoreNames.contains(name))request.result.createObjectStore(name,{keyPath:'id'});};request.onsuccess=()=>{const db=request.result,tx=db.transaction('drafts','readwrite');tx.objectStore('drafts').put({id:'legacy-recording',kind:'voice',filename:'legacy-recording.webm',blob:new Blob(['retained audio']),savedAt:new Date().toISOString()});tx.oncomplete=()=>{db.close();resolve();};tx.onerror=()=>reject(tx.error);};request.onerror=()=>reject(request.error);});
  });
  await page.reload();await expect(page.locator('#auth-panel')).toBeHidden();await page.locator('[data-view="capture"]').click();await expect(page.locator('#device-reports-list')).toContainText('legacy-recording.webm');
  const contents=await page.evaluate(async()=>{const draft=await window.CarrickOffline.get('drafts','legacy-recording');return draft.blob.text();});expect(contents).toBe('retained audio');
  await page.evaluate(()=>window.CarrickOffline.remove('drafts','legacy-recording'));await page.reload();await expect(page.locator('#auth-panel')).toBeHidden();await page.locator('[data-view="capture"]').click();await expect(page.locator('#device-reports-list')).not.toContainText('legacy-recording.webm');
});
test('failed workspace load has a persistent retry and no false empty-state metrics',async({page})=>{
  await page.evaluate(()=>window.CarrickOffline.remove('snapshots','workspace'));
  await page.route('**/api/events',route=>route.fulfill({status:503,contentType:'text/html',body:'Temporary upstream failure'}));
  await page.reload();await expect(page.locator('#auth-panel')).toBeHidden();await expect(page.locator('#workspace-status-title')).toHaveText('Workspace could not load');await expect(page.locator('#metrics .value')).toHaveText(['—','—','—','—']);await expect(page.locator('#welcome')).toBeHidden();
  await page.unroute('**/api/events');await page.locator('#workspace-retry').click();await expect(page.locator('#workspace-status')).toBeHidden();await expect(page.locator('#workspace-updated')).toContainText('Updated');
});
test('planner edits survive refresh and failed checks never enable approval',async({page})=>{
  await importSchedule(page);await submitText(page,'North pipeline welding started today');await page.locator('[data-view="review"]').click();
  const card=page.locator('.review-card').filter({has:page.locator('.candidate-choice[value="PI-301"]')}).first();
  await card.locator('.candidate-select').selectOption('PI-301');await card.locator('.decision-reason').fill('Keep this planner note');await expect(card.locator('.approve-button')).toBeEnabled();
  await page.locator('#workspace-refresh').click();await expect(page.locator('#workspace-status')).toBeHidden();await expect(card.locator('.decision-reason')).toHaveValue('Keep this planner note');await expect(card.locator('.candidate-select')).toHaveValue('PI-301');
  await page.route('**/api/events/*/checks',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Checks temporarily unavailable'})}));await card.locator('.candidate-select').selectOption('PI-302');await expect(card.locator('.proposal-checks')).toContainText('Checks temporarily unavailable');await expect(card.locator('.approve-button')).toBeDisabled();
  await page.evaluate(()=>{window.CarrickOffline.setReachable(false);window.CarrickOffline.setReachable(true);});await expect(card.locator('.approve-button')).toBeDisabled();
  await page.unroute('**/api/events/*/checks');await card.getByRole('button',{name:'Retry checks'}).click();await expect(card.locator('.approve-button')).toBeEnabled();await expect(card.locator('.decision-reason')).toHaveValue('Keep this planner note');
});
test('sign-in recovers from invalid remembered context and unavailable server',async({page,browser})=>{
  await page.evaluate(()=>sessionStorage.setItem('carrick-session-context','invalid-json'));await page.reload();await expect(page.locator('#auth-panel')).toBeHidden();await expect(page.locator('#workspace-status')).toBeHidden();
  const context=await browser.newContext();const login=await context.newPage();const failures=[];login.on('pageerror',error=>failures.push(error.message));await login.route('**/api/auth/**',route=>route.abort());await login.goto('/app');await expect(login.locator('#auth-retry')).toBeVisible();await expect(login.locator('#auth-submit')).toBeDisabled();await login.unroute('**/api/auth/**');await login.locator('#auth-retry').click();await expect(login.locator('#auth-submit')).toBeEnabled();await expect(login.locator('#auth-form')).toHaveAttribute('data-setup','false');expect(failures).toEqual([]);await context.close();
});
test('submission locks report edits and reconnect preserves standard matching',async({page})=>{
  await importSchedule(page);await page.evaluate(()=>window.dispatchEvent(new Event('carrick-reconnected')));await expect(page.locator('#workspace-status')).toBeHidden();await expect(page.locator('#ai-mode')).not.toBeChecked();
  let release,attempts=0;await page.route('**/api/reports',async route=>{attempts++;await new Promise(resolve=>release=resolve);await route.continue();});
  await page.locator('#report-text').fill('North pipeline welding started today');await page.locator('#report-form button[type=submit]').click();
  try{await expect(page.locator('#report-form')).toHaveAttribute('aria-busy','true');await expect(page.locator('#report-text')).toBeDisabled();await expect(page.locator('#report-form button[type=submit]')).toBeDisabled();await expect.poll(()=>attempts).toBe(1);}finally{release?.();}
  await expect(page.locator('#report-text')).toBeEnabled();await expect(page.locator('#report-text')).toHaveValue('');expect(attempts).toBe(1);
});
test('supervisor cannot approve or export and another project stays inaccessible',async({page,browser})=>{
  await importSchedule(page);
  await page.locator('#access-open').click();await page.locator('#member-name').fill('Fixture Supervisor');await page.locator('#member-email').fill('supervisor@example.test');await page.locator('#member-password').fill(password);await page.locator('#member-role').selectOption('supervisor');await page.locator('#member-form button').click();await expect(page.locator('#access-message')).toContainText('Project access saved');await page.locator('#access-close').click();
  const ownedProject=await page.evaluate(()=>window.CarrickAuth.project.id);
  const other=await page.evaluate(async()=>{const response=await fetch('/api/projects',{method:'POST',headers:{'Content-Type':'application/json',...window.CarrickAuth.headers()},body:JSON.stringify({name:'Private second project'})});return response.json();});
  const context=await browser.newContext();const supervisor=await context.newPage();await supervisor.goto('/app');await supervisor.locator('#auth-email').fill('supervisor@example.test');await supervisor.locator('#auth-password').fill(password);await supervisor.locator('#auth-submit').click();await expect(supervisor.locator('#auth-panel')).toBeHidden();
  const result=await supervisor.evaluate(async({ownedProject,other})=>{
    const headers={'Content-Type':'application/json',...window.CarrickAuth.headers(),'X-Carrick-Project':ownedProject};
    return {export:(await fetch('/api/exports',{method:'POST',headers,body:'{}'})).status,private:(await fetch('/api/events',{headers:{...headers,'X-Carrick-Project':other.id}})).status};
  },{ownedProject,other});expect(result.export).toBe(403);expect(result.private).toBe(403);await context.close();
});
