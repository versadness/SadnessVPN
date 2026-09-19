const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('C:/Users/Sadness/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/Sadness/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 try{
 const page=await browser.newPage({viewport:{width:1100,height:800}}),errors=[],requests=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(u.pathname.startsWith('/api/')){requests.push({path:u.pathname,body:route.request().postDataJSON()});return route.fulfill({contentType:'application/json',body:'{"ok":true}'});}
  const file=u.pathname==='/'?path.join(root,'ui/templates/index.html'):path.join(root,'ui',u.pathname);
  if(!file.startsWith(path.join(root,'ui'))||!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html'});
 });
 await page.addInitScript(()=>{window.WebSocket=class{static OPEN=1;static CONNECTING=0;constructor(){this.readyState=1;}close(){}};});
 await page.goto('http://127.0.0.1:45680/?desktop=1');
 await page.evaluate(()=>{
  handle({type:'state',appVersion:'2.0.15',coreVersions:'sing-box 1.10.7 · Mihomo 1.19.30 · Xray 26.3.27',status:'off',connected:false,
   groups:[{id:'g',name:'Test',servers:[{remark:'XHTTP test',ui_id:'s',protocol:'vless',transport:'xhttp',reality:true}]}],selGroup:'g',selIndex:0,
   activeProtocol:'vless',appsConfig:{mode:'blacklist',apps:[{exe:'chrome.exe',name:'Chrome',enabled:true},{exe:'discord.exe',name:'Discord',enabled:false}]},
   appSettings:{},tunnelSettings:{core:'auto'}});
  go('routing');
 });
 assert.match(await page.locator('[data-route-exe="chrome.exe"]').textContent(),/После подключения: Напрямую.*Reality: нет/);
 assert.match(await page.locator('[data-route-exe="discord.exe"]').textContent(),/VLESS \/ XHTTP.*Reality: да/);
 await page.evaluate(()=>{handle({type:'status',state:'on',core:'Xray + sing-box'});handle({type:'traffic_stats',totalUp:10,totalDown:20,appRoutes:[
  {exe:'chrome.exe',routes:['direct','proxy'],networks:['tcp'],connections:2},
  {exe:'new.exe',routes:['proxy'],networks:['udp'],connections:1},
  {exe:'<img src=x onerror=window.injected=true>.exe',routes:['unknown'],networks:[],connections:1}
 ]});});
 const mixed=await page.locator('[data-route-exe="chrome.exe"]').textContent();
 assert(mixed.includes('Сейчас:')&&mixed.includes('Напрямую')&&mixed.includes('Через VPN'));
 assert.equal(await page.locator('#observedAppCount').textContent(),'2');
 assert.equal(await page.locator('#observedAppList img').count(),0);
 for(const [width,height] of [[1100,800],[780,620],[390,844]]){
  await page.setViewportSize({width,height});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(root,`build/routing-215-${width}.png`)});
 }
 await page.evaluate(()=>{handle({type:'status',state:'off'});go('settings');syncSettings();});
 assert.equal(await page.locator('#observedAppCount').textContent(),'0');
 await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/tunnel-settings')),page.locator('#coreSelect').selectOption('mihomo')]);
 assert(requests.some(r=>r.path==='/api/tunnel-settings'&&r.body.core==='mihomo'));
 await page.evaluate(()=>{go('servers');renderServers();});
 assert.match(await page.locator('.srv-proto').first().textContent(),/VLESS \/ XHTTP.*Reality: да/);
 assert.deepEqual(errors,[]);
 await page.evaluate(()=>{
  ST.groups=[{id:'task',name:'Моя подписка',servers:[
   {ui_id:'fast',remark:'Игры · Frankfurt',protocol:'hysteria2',transport:'quic',reality:false},
   {ui_id:'media',remark:'Видео · Amsterdam',protocol:'vless',transport:'xhttp',reality:true}]}];
  ST.selGroup='task';ST.selIndex=0;ST.status='off';ST.backendOnline=true;
  ST.appsConfig={mode:'all',apps:[{exe:'chrome.exe',name:'Google Chrome',enabled:true,destination:'server:media'},
    {exe:'Discord.exe',name:'Discord',enabled:true,destination:'server:fast'},
    {exe:'steam.exe',name:'Steam',enabled:true,destination:'direct'}]};
  go('routing');renderRules();
 });
 assert.equal(await page.getByLabel('Маршрут для Google Chrome').inputValue(),'server:media');
 assert.match(await page.locator('[data-route-exe="Discord.exe"]').textContent(),/HYSTERIA2 \/ QUIC/);
 assert.match(await page.locator('[data-route-exe="steam.exe"]').textContent(),/Напрямую/);
 await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/apps/destination')),page.getByLabel('Маршрут для Discord').selectOption('server:media')]);
 assert(requests.some(r=>r.path==='/api/apps/destination'&&r.body.exe==='Discord.exe'&&r.body.destination==='server:media'));
 for(const [width,height] of [[980,700],[1280,800],[780,600]]){
  await page.setViewportSize({width,height});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(root,`build/routing-219-${width}.png`)});
 }
 await page.getByRole('button',{name:'Общий маршрут',exact:true}).click();
 await page.locator('#modeBl').waitFor({state:'visible'});
 await page.getByRole('button',{name:'Приложения и серверы',exact:true}).click();
 await page.getByLabel('Маршрут для Google Chrome').waitFor({state:'visible'});
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,pageErrors:errors,checks:'core selection, XHTTP badge, configured/live/mixed routes, Reality, auto-discovery, disconnect reset, XSS',viewports:3}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
