const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('C:/Users/Sadness/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root=path.resolve(__dirname,'..');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.SADNESS_TEST_CHROMIUM || undefined});
 try{
  const page=await browser.newPage({viewport:{width:980,height:700}}),errors=[],calls=[];
  let updateState={status:'unconfigured',version:'2.0.20',message:'Сервер обновлений ещё не настроен'};
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const u=new URL(route.request().url());
   if(u.pathname.startsWith('/api/')){
    const body=route.request().postDataJSON();calls.push({path:u.pathname,body});
    let result={ok:true};
    if(u.pathname==='/api/routing/rules')result.rules=body?.rules||[];
    if(u.pathname==='/api/routing/conflicts')result.conflicts=Object.fromEntries((body?.rules||[]).filter(r=>r.id==='conflict-b').map(r=>[r.id,[{id:'conflict-a',relation:'covered',different_destination:true}]]));
    if(['/api/updates/check','/api/updates/state'].includes(u.pathname))Object.assign(result,updateState);
    return route.fulfill({contentType:'application/json',body:JSON.stringify(result)});
   }
   const file=u.pathname==='/'?path.join(root,'ui/templates/index.html'):path.join(root,'ui',u.pathname);
   if(!file.startsWith(path.join(root,'ui'))||!fs.existsSync(file))return route.fulfill({status:404,body:''});
   return route.fulfill({body:fs.readFileSync(file),contentType:file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':'text/html'});
  });
  await page.addInitScript(()=>{window.WebSocket=class{static OPEN=1;constructor(){this.readyState=1;}close(){}};});
  await page.goto('http://127.0.0.1:45680/?desktop=1');
  await page.evaluate(()=>{handle({type:'state',appVersion:'2.0.20',status:'off',connected:false,groups:[{id:'a',name:'Подписка · Тест',servers:[{ui_id:'s1',remark:'Amsterdam',protocol:'vless',type:'xhttp',security:'reality'}]}],selGroup:'a',selIndex:0,appsConfig:{mode:'all',apps:[],rules:[]},appSettings:{socks:1080,http:8080},tunnelSettings:{}});go('settings');});
  await page.locator('#settingNav button[data-category=all]').click();
  const gaps=await page.evaluate(()=>{
   const rows=[...document.querySelector('#coreName').closest('.settings-group').children].filter(n=>!n.classList.contains('sec'));
   return rows.slice(1).map((n,i)=>n.getBoundingClientRect().top-rows[i].getBoundingClientRect().bottom);
  });
  assert(gaps.length>=2&&gaps.every(gap=>gap>=9),'Settings cards must not touch');
  await page.screenshot({path:path.join(root,'build/settings-220-all-spacing.png')});
  await page.locator('#settingNav button[data-category=appearance]').click();
  await page.locator('#portSocks').waitFor({state:'hidden'});
  await page.getByLabel('Поиск по настройкам').fill('SOCKS5');
  await page.locator('#portSocks').waitFor({state:'visible'});
  assert.equal(await page.locator('#portSocks').inputValue(),'1080');
  await page.getByLabel('Поиск по настройкам').fill('zz-nothing');
  await page.locator('#page-settings .settings-empty').waitFor({state:'visible'});
  await page.getByLabel('Поиск по настройкам').fill('');
  await page.locator('#portSocks').waitFor({state:'hidden'});
  await page.locator('#settingNav button[data-category=updates]').click();
  await page.getByRole('button',{name:'Проверить обновления',exact:true}).click();
  assert.equal(calls.filter(c=>c.path==='/api/updates/check'&&c.body.automatic===true).length,1);
  updateState={status:'available',version:'2.0.20',available_version:'2.0.21',channel:'beta',can_download:true,suppress_notice:true,message:'Доступна новая версия',notes:[]};
  await page.getByRole('button',{name:'Проверить обновления',exact:true}).click();
  assert.equal(await page.locator('.update-notice').count(),0);
  await page.getByRole('button',{name:'Скачать',exact:true}).waitFor({state:'visible'});
  updateState={...updateState,status:'error',message:'Ошибка загрузки'};
  await page.getByRole('button',{name:'Проверить обновления',exact:true}).click();
  await page.getByRole('button',{name:'Повторить загрузку',exact:true}).waitFor({state:'visible'});
  await page.reload();await page.evaluate(()=>go('settings'));
  assert.equal(await page.locator('#settingNav [data-category=updates]').getAttribute('aria-pressed'),'true');
  await page.screenshot({path:path.join(root,'build/settings-220-updates.png')});
  await page.evaluate(()=>go('routing'));
  assert.deepEqual(await page.locator('.route-tabs button').allTextContents(),['Приложения и серверы','Готовые наборы']);
  assert.equal(await page.locator('.route-visual').count(),0);
  assert.equal(await page.locator('.mode-cards').isVisible(),true);
  await page.locator('.rules-bar').getByRole('button',{name:'Новое правило',exact:true}).click();
  await page.getByRole('button',{name:'По суффиксу',exact:true}).click();
  await page.getByLabel('Значение',{exact:true}).fill('example.com');
  await page.getByLabel('Название · необязательно').fill('<img src=x onerror=alert(1)>');
  await page.getByLabel('Действие',{exact:true}).selectOption('direct');
  assert.equal(await page.getByLabel('Через сервер',{exact:true}).isDisabled(),true);
  await page.screenshot({path:path.join(root,'build/rule-editor-220.png')});
  await page.locator('.routing-editor').getByRole('button',{name:'Сохранить',exact:true}).click();
  await page.locator('.routing-editor').waitFor({state:'hidden'});
  assert.equal(await page.locator('.custom-rule-list img').count(),0);
  assert.match(await page.locator('.custom-rule-list').textContent(),/Напрямую/);
  assert(calls.some(c=>c.path==='/api/routing/rules'&&c.body.rules[0].kind==='suffix'&&c.body.rules[0].destination==='direct'));
  for(const [width,height]of [[980,700],[780,600],[1280,800]]){
   await page.setViewportSize({width,height});await page.evaluate(()=>go('settings'));await page.locator('#settingNav [data-category=network]').click();
   assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.screenshot({path:path.join(root,`build/settings-220-${width}.png`)});
  }
  const bulk=await page.evaluate(()=>{
    const start=performance.now();
    ST.appsConfig.rules=Array.from({length:1000},(_,i)=>({id:'rule-'+i,kind:'suffix',value:'site'+i+'.example',name:'Длинное название правила '+i,destination:'direct',enabled:true}));
    renderRules();go('routing');document.querySelector('[data-panel=routeApps]').click();
    return {ms:Math.round(performance.now()-start),count:document.querySelectorAll('.custom-rule-list .custom-rule').length};
  });
  assert.equal(bulk.count,1000);
  await page.getByLabel('Поиск по правилам').fill('site999.example');
  assert.equal(await page.locator('.custom-rule-list .custom-rule').count(),1);
  assert.equal(await page.locator('.custom-rule-list .custom-rule').getAttribute('draggable'),'false');
  await page.getByLabel('Поиск по правилам').fill('');
  await page.evaluate(()=>go('routing'));
  await page.locator('[data-panel=routePresets]').click();
  assert.equal(await page.locator('#routePresets .preset-set').count(),7);
  assert.equal(await page.locator('#routePresets').textContent().then(t=>/оррент/i.test(t)),false);
  await page.locator('[data-panel=routeApps]').click();
  await page.setViewportSize({width:780,height:480});
  await page.locator('.rules-bar').getByRole('button',{name:'Новое правило',exact:true}).click();
  const modalBounds=await page.locator('.routing-editor').boundingBox();
  assert(modalBounds.y>=0&&modalBounds.y+modalBounds.height<=480);
  await page.screenshot({path:path.join(root,'build/rule-editor-221-short.png')});
  await page.locator('.routing-editor').getByRole('button',{name:'Отмена',exact:true}).click();
  await page.evaluate(()=>{
    ST.groups=[{name:'Тест',servers:[{ui_id:'s1',remark:'Сервер теста',protocol:'vless'}]}];
    ST.appsConfig.rules=[{id:'conflict-a',name:'Основное правило',kind:'suffix',value:'example.com',destination:'direct',enabled:true},{id:'conflict-b',name:'Поддомен',kind:'suffix',value:'a.example.com',destination:'proxy',enabled:true}];renderRules();
  });
  await page.getByText('Перекрыто предыдущим правилом «Основное правило» — другой выход.',{exact:true}).waitFor();
  // Готовые наборы: крупные сборники добавляются целиком, торрент-набора нет.
  page.on('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'Готовые наборы',exact:true}).click();
  await page.locator('#routePresets .preset-set').first().getByRole('button',{name:'Добавить набор',exact:true}).click();
  await page.waitForTimeout(300);
  assert(calls.some(c=>c.path==='/api/routing/rules'&&c.body.rules.some(r=>r.value==='Telegram.exe'&&r.destination==='proxy')));
  assert(calls.some(c=>c.path==='/api/routing/rules'&&c.body.rules.filter(r=>r.kind==='suffix'||r.kind==='process').length>=20));
  console.log(JSON.stringify({bulkRules:bulk,shortWindow:true}));
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,checks:'cross-tab search, retained settings, manual/startup update check, DIRECT form, saved route, XSS, 3 viewports'}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1)});
