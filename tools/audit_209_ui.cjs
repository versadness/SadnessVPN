// Product HTML/CSS/JS in an isolated browser. No requests reach the real VPN API.
const fs=require('fs'),path=require('path');
const {chromium}=require('C:/Users/Sadness/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..');
const results=[];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Users/Sadness/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe'});
 const page=await browser.newPage({viewport:{width:964,height:661}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/*',async route=>{
  const u=new URL(route.request().url());
  if(u.pathname.startsWith('/api/'))return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,user:'GENERATED_USER',pass:'GENERATED_PASS'})});
  const file=u.pathname==='/'?path.join(root,'ui/templates/index.html'):path.join(root,'ui',u.pathname);
  if(!file.startsWith(path.join(root,'ui'))||!fs.existsSync(file))return route.fulfill({status:404,body:''});
  return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html'});
 });
 await page.addInitScript(()=>{
  window.WebSocket=class{static OPEN=1;static CONNECTING=0;constructor(){this.readyState=1;}close(){}};
 });
 await page.goto('http://127.0.0.1:45680/?desktop=1');
 await page.evaluate(()=>{
  handle({type:'state',status:'off',connected:false,activeProtocol:'vless',appVersion:'2.0.9',
   groups:[{id:'g',servers:[{ui_id:'p1',remark:'Alpha',protocol:'vless'},{ui_id:'p2',remark:'Beta',protocol:'trojan'}]}],selGroup:'g',selIndex:0,
   wgGroups:[{id:'w',servers:[{ui_id:'w1',remark:'WG slow'},{ui_id:'w2',remark:'WG fast'},{ui_id:'w3',remark:'Native AWG',is_awg:true}]}],selWgGroup:'w',selWgIndex:0,
   appsConfig:{mode:'whitelist',apps:[{exe:'test.exe',name:'Test',enabled:true}]},
   appSettings:{socks:1080,http:8080,startup:false,silent:false,autoconn:false,lan:false,favorite_servers:[]},
   tunnelSettings:{server_sort:'default',dns_preset:'cf_google',socks5_user:'OLD_USER',socks5_pass:'OLD_PASS',ping_timeout:3000},
   zapretStrategies:[{id:'a',category:'Main',name:'General ALT 1'},{id:'b',category:'Main',name:'General ALT 2'}]});
  setBackendOnline(true);
 });
 async function test(caseName,fn){results.push({case:caseName,evidence:await page.evaluate(fn)});}
 await test('backend_disconnect_status',()=>{ST.connected=true;ST.status='on';applyStatus();setBackendOnline(false);return {title:statusTitle.textContent,top:tbState.textContent,connectDisabled:connectBtn.disabled};});
 await test('wg_sort_after_ping',()=>{ST.connected=false;ST.status='off';ST.srvSort='ping';renderWg();handle({type:'wg_ping_result',sid:'w1',label:'200 мс',color:'yellow'});handle({type:'wg_ping_result',sid:'w2',label:'10 мс',color:'green'});handle({type:'wg_ping_done'});return [...document.querySelectorAll('#wgGrid .srv-name')].map(e=>e.textContent);});
 await test('generated_credentials_state',async()=>{go('settings');await regenSocks5();handle({type:'socks5_creds',user:'GENERATED_USER',pass:'GENERATED_PASS'});const before=s5user.value;syncSettings();return {before,after:s5user.value};});
 await test('zapret_change_selection_while_running',()=>{ST.zapRunning=true;ST.zapSel='a';renderZapret();document.querySelector('[data-id="b"]').click();return {selection:ST.zapSel,status:zapT.textContent,button:zapBtn.textContent};});
 await test('zapret_search',()=>{zapSearch.value='NO_MATCH';filterZapret();return [...document.querySelectorAll('.zap-card')].map(e=>({hidden:e.hidden,display:getComputedStyle(e).display}));});
 await test('rule_toggle_connected',()=>{ST.connected=true;ST.status='on';ST.proto='vless';applyStatus();return {disabled:document.querySelector('#ruleList .toggle').disabled,modeDisabled:modeWl.disabled};});
 await test('dns_legacy_preset_label',()=>{ST.connected=false;ST.status='off';ST.tunnel.dns_preset='quad9';syncSettings();return {actual:ST.tunnel.dns_preset,label:ddDnsLbl.textContent};});
 await test('keyboard_dropdown',()=>[...document.querySelectorAll('.dd-trigger')].map(e=>({id:e.parentElement.id,tabIndex:e.tabIndex,role:e.getAttribute('role')})));
 await test('dynamic_button_aria',()=>{ST.status='on';ST.connected=true;applyStatus();return {visible:powerLbl.textContent,aria:connectBtn.getAttribute('aria-label')};});
 await page.evaluate(()=>{ST.connected=false;ST.status='off';ST.proto='vless';applyStatus();go('routing');promptRule();ruleExe.focus();});
 const focus=[];
 for(let i=0;i<14;i++){await page.keyboard.press('Tab');focus.push(await page.evaluate(()=>({id:document.activeElement.id,inside:!!document.activeElement.closest('.modal-backdrop.open')})));}
 results.push({case:'modal_focus_trap',evidence:focus});
 await page.evaluate(()=>{closeModal('ruleModal');zapSearch.value='';filterZapret();});
 for(const [width,height] of [[964,661],[764,561],[1384,861],[620,440]]){
  await page.setViewportSize({width,height});
  for(const pg of ['home','servers','wg','routing','settings','zapret']){
   await page.evaluate(p=>go(p),pg);
   const info=await page.evaluate(()=>{const p=document.querySelector('.page.active'),r=p.getBoundingClientRect();return {page:p.id,overflowX:p.scrollWidth>p.clientWidth+1,overflowY:p.scrollHeight>p.clientHeight+1,rect:{w:r.width,h:r.height},focusable:[...p.querySelectorAll('button,input,[tabindex="0"]')].length};});
   results.push({case:'layout',viewport:[width,height],evidence:info});
  }
 }
 await page.setViewportSize({width:764,height:561});
 await page.evaluate(()=>{go('settings');document.querySelector('#page-settings>.scroll').scrollTop=0;});
 await page.screenshot({path:path.join(root,'build/audit-209-settings-min.png')});
 await test('setting_navigation',()=>[...document.querySelectorAll('#settingNav button')].map(b=>({text:b.textContent,width:b.getBoundingClientRect().width})));
 await test('settings_input_labels',()=>[...document.querySelectorAll('#page-settings input:not([type="file"])')].filter(e=>!e.getAttribute('aria-label')&&!e.labels?.length).map(e=>e.id));
 await page.evaluate(()=>{go('home');ST.groups[0].servers[0].remark='VeryLongServerNameWithoutSpaces'.repeat(30);applyStatus();});
 await test('long_server_name',()=>({pageOverflow:document.querySelector('.page.active').scrollWidth>document.querySelector('.page.active').clientWidth,cardOverflow:hcServer.scrollWidth>hcServer.clientWidth,title:getComputedStyle(hcServer).textOverflow}));
 await page.screenshot({path:path.join(root,'build/audit-209-long-name.png')});
 await test('import_wg_protocol_state',()=>{ST.proto='vless';handle({type:'wg_groups_updated',wgGroups:[{id:'new',servers:[{remark:'New AWG',is_awg:true}]}],selWgGroup:'new',selWgIndex:0});return {frontendProtocol:ST.proto,selectedGroup:ST.selWgGroup};});
 await test('auto_connect_manual_race',async()=>{const original=window.setTimeout,oldApi=window.api,calls=[];let pending;window.setTimeout=(fn)=>{pending=fn;return 1;};window.api=async path=>{calls.push(path);return {ok:true};};ST.settings.autoconn=true;autoConnectAttempted=false;ST.connected=false;ST.status='off';maybeAutoConnect();ST.status='connecting';if(pending)await pending();window.setTimeout=original;window.api=oldApi;return calls;});
 await page.evaluate(()=>{ST.settings.autoconn=false;ST.proto='vless';ST.connected=false;ST.status='off';ST.groups[0].servers[0].remark='Alpha';setBackendOnline(true);applyStatus();});
 await page.setViewportSize({width:764,height:561});
 for(const pg of ['home','routing']){
  await page.evaluate(p=>go(p),pg);
  await page.screenshot({path:path.join(root,`build/audit-209-${pg}-min.png`)});
  await test('bottom_controls_'+pg,()=>[...document.querySelectorAll('.page.active button')].filter(e=>{const r=e.getBoundingClientRect();return r.height&&r.bottom>innerHeight;}).map(e=>({id:e.id,text:e.textContent.trim(),bottom:e.getBoundingClientRect().bottom})));
 }
 await page.evaluate(()=>go('settings'));
 await page.locator('#ddSort .dd-trigger').evaluate(e=>e.focus());
 await page.keyboard.press('Enter');
 results.push({case:'sort_keyboard_open',evidence:await page.locator('#ddSort').evaluate(e=>e.classList.contains('open'))});
 await page.evaluate(()=>{go('servers');ST.srvSort='default';});
 for(const count of [100,1000,5000]){
  const timing=await page.evaluate(n=>{ST.groups=[{id:'load',servers:Array.from({length:n},(_,i)=>({ui_id:'server'+i,remark:'Germany '+i,protocol:'vless'}))}];const start=performance.now();renderServers();void srvGrid.offsetHeight;return performance.now()-start;},count);
  results.push({case:'server_render_load',count,milliseconds:timing});
 }
 results.push({case:'page_errors',evidence:errors});
 fs.writeFileSync(path.join(root,'build/audit-209-ui-results.json'),JSON.stringify(results,null,2));
 console.log(JSON.stringify({cases:results.length,pageErrors:errors,resultsFile:'build/audit-209-ui-results.json',load:results.filter(r=>r.case==='server_render_load')},null,2));
 await browser.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
