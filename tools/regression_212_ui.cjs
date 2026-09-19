// Real product assets with isolated API fixtures, never touches VPN/user settings.
const fs=require('fs'), path=require('path'), assert=require('assert/strict');
const {chromium}=require('C:/Users/Sadness/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/Sadness/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 const page=await browser.newPage({viewport:{width:980,height:700}}), errors=[], requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(u.pathname.startsWith('/api/')){requests.push({path:u.pathname,body:route.request().postDataJSON()});return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true})});}
  const file=u.pathname==='/'?path.join(root,'ui/templates/index.html'):path.join(root,'ui',u.pathname);
  if(!file.startsWith(path.join(root,'ui'))||!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html'});
 });
 await page.addInitScript(()=>{window.WebSocket=class{static OPEN=1;static CONNECTING=0;constructor(){this.readyState=1;}close(){}};});
 await page.goto('http://127.0.0.1:45680/?desktop=1');
 await page.evaluate(()=>{
  ST.backendOnline=true;ST.status='off';
  ST.groups=[{id:'g',name:'Aurora VPN',url:'https://private.invalid/NEVER_RENDER_TOKEN',count:13,servers:[],subscription:{provider_name:'Aurora',expire:1800000000,updated_at:1788624000,upload:1024,download:72*1024**3,total:200*1024**3}}];
  ST.wgGroups=[{id:'w',name:'Моя AWG-подписка',url:'https://private.invalid/WG',servers:[],subscription:{error:'Провайдер вернул пустой список серверов. Проверьте подписку у провайдера.'}}];
  renderSubscriptions();go('subscriptions');
 });
 assert.equal(await page.locator('.subscription-card').count(),2);
 assert(!(await page.locator('#subscriptionList').innerHTML()).includes('NEVER_RENDER_TOKEN'));
 for(const [w,h] of [[980,700],[780,600],[390,844]]){
  await page.setViewportSize({width:w,height:h});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(root,`build/subscriptions-212-${w}.png`)});
 }
 await page.setViewportSize({width:980,height:700});
 await page.locator('[data-sub-action="rename"]').first().click();
 assert(await page.locator('#subscriptionDialog').evaluate(el=>el.open));
 await page.locator('#subscriptionName').fill('Новое название');
 await page.locator('#subscriptionConfirm').click();
 await page.waitForFunction(()=>!document.getElementById('subscriptionDialog').open);
 assert(requests.some(r=>r.path==='/api/groups/rename'&&r.body.name==='Новое название'));
 await page.locator('[data-sub-action="delete"]').last().click();
 await page.locator('#subscriptionCancel').click();
 assert(!requests.some(r=>r.path.endsWith('/delete')));
 await page.locator('[data-sub-action="delete"]').last().click();
 await page.locator('#subscriptionConfirm').click();
 await page.waitForFunction(()=>!document.getElementById('subscriptionDialog').open);
 assert(requests.some(r=>r.path==='/api/wg/groups/delete'));
 await page.evaluate(()=>handle({type:'subscription_busy',busy:true}));
 assert(await page.locator('[data-sub-action="refresh"]').first().isDisabled());
 await page.evaluate(()=>{handle({type:'subscription_busy',busy:false});ST.groups[0].name='<img src=x onerror="window.injected=true">';ST.groups[0].subscription.error='<script>window.injected=true</script>';renderSubscriptions();});
 assert.equal(await page.locator('#subscriptionList img, #subscriptionList script').count(),0);
 assert.equal(await page.evaluate(()=>window.injected),undefined);
 await page.evaluate(()=>{ST.status='on';renderSubscriptions();});
 assert(await page.locator('#subscriptionImport button').isDisabled());
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,pageErrors:errors,viewportChecks:3,apiActions:requests.filter(r=>r.path.includes('/groups/')).map(r=>r.path)}));
 await browser.close();
})().catch(error=>{console.error(error);process.exit(1);});
