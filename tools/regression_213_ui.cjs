// Isolated product UI: subscription grouping, identity mapping and clean state.
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('C:/Users/Sadness/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/Sadness/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 const page=await browser.newPage({viewport:{width:980,height:700}}),errors=[],requests=[];
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
  ST.backendOnline=true;ST.status='off';ST.selGroup='b';ST.selIndex=0;
  const servers=prefix=>[{ui_id:prefix+'1',remark:'Germany | Frankfurt',protocol:'vless'},{ui_id:prefix+'2',remark:'Finland | Helsinki',protocol:'trojan'}];
  ST.groups=[{id:'a',name:'Sadness VPN',url:'https://example.invalid/SECRET_A',servers:servers('a')},{id:'b',name:'Вторая подписка',url:'https://example.invalid/SECRET_B',servers:servers('b')},{id:'manual',name:'Вручную',servers:[{ui_id:'m',remark:'Личный сервер',protocol:'vless'}]}];
  ST.wgGroups=[{id:'wa',name:'WG Home',url:'https://example.invalid/SECRET',servers:[{ui_id:'w1',remark:'Home'}]},{id:'wb',name:'AWG Travel',url:'https://example.invalid/SECRET',servers:[{ui_id:'w2',remark:'Travel',is_awg:true}]}];
  renderServers();renderWg();applyStatus();go('servers');
 });
 assert.equal(await page.locator('#srvGrid .server-subgroup').count(),3);
 assert.equal(await page.locator('#srvGrid .srv-row').count(),5);
 assert(!(await page.locator('#srvGrid').innerHTML()).includes('SECRET'));
 assert.equal(await page.locator('[data-server-group="b"] .server-subgroup-selected').count(),1);
 await page.evaluate(()=>{ST.srvSort='name';renderServers();});
 assert.deepEqual(await page.locator('#srvGrid .srv-row').evaluateAll(es=>es.map(e=>[e.dataset.gid,Number(e.dataset.index)])),[['a',1],['a',0],['b',1],['b',0],['manual',0]]);
 await page.locator('[data-server-group="b"] .srv-row').first().click();
 assert(requests.some(r=>r.path==='/api/servers/select'&&r.body.group_id==='b'&&r.body.index===1));
 await page.locator('[data-server-group="a"] .server-subgroup-head').click();
 assert.equal(await page.locator('[data-server-group="a"] .srv-row').count(),0);
 assert.equal(await page.locator('[data-server-group="a"] .server-subgroup-head').getAttribute('aria-expanded'),'false');
 await page.keyboard.press('Enter');
 assert.equal(await page.locator('[data-server-group="a"] .srv-row').count(),2);
 await page.locator('#srvSearch').fill('Вторая');
 assert.equal(await page.locator('#srvGrid .server-subgroup').count(),1);
 assert.equal(await page.locator('#srvGrid .srv-row').count(),2);
 await page.locator('#srvSearch').fill('Frankfurt');
 assert.equal(await page.locator('#srvGrid .server-subgroup').count(),2);
 assert.equal(await page.locator('#srvGrid .srv-row').count(),2);
 await page.locator('#srvSearch').fill('');
 for(const [width,height] of [[980,700],[780,600],[390,844]]){
  await page.setViewportSize({width,height});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.screenshot({path:path.join(root,`build/server-groups-213-${width}.png`)});
 }
 await page.evaluate(()=>{go('wg');renderWg();});
 assert.equal(await page.locator('#wgGrid .server-subgroup').count(),2);
 await page.locator('[data-server-group="wb"] .srv-row').click();
 assert(requests.some(r=>r.path==='/api/wg/servers/select'&&r.body.group_id==='wb'&&r.body.index===0));
 await page.evaluate(()=>{go('servers');ST.groups[0].name='<img src=x onerror="window.injected=true">';renderServers();});
 assert.equal(await page.locator('.server-subgroup-head img').count(),0);
 assert.equal(await page.evaluate(()=>window.injected),undefined);
 await page.evaluate(()=>{ST.groups=[{id:'many',name:'Many',servers:Array.from({length:205},(_,i)=>({ui_id:'s'+i,remark:'Server '+i}))}];renderServers();});
 assert.equal(await page.locator('#srvGrid .srv-row').count(),100);
 await page.locator('[data-group-action="more"]').click();
 assert.equal(await page.locator('#srvGrid .srv-row').count(),200);
 await page.locator('[data-group-action="more"]').click();
 assert.equal(await page.locator('#srvGrid .srv-row').count(),205);
 await page.evaluate(()=>{ST.groups=[];ST.wgGroups=[];renderServers();renderWg();renderSubscriptions();});
 assert.equal(await page.locator('.srv-row,.subscription-card,.server-subgroup').count(),0);
 assert.deepEqual(errors,[]);
 console.log(JSON.stringify({passed:true,groups:'proxy + WG + manual',checks:'sorting, original indexes, collapse/keyboard, search, XSS, pagination, clean state',viewports:3,pageErrors:errors}));
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1);});
