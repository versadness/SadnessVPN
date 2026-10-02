let ST={connected:false,status:'off',backendOnline:false,server:'',proto:'vless',groups:[],selGroup:null,selIndex:null,wgGroups:[],selWgGroup:null,selWgIndex:null,appsConfig:{mode:'all',apps:[]},settings:{},tunnel:{},pings:{},wgPings:{},stars:{},hwid:'',zapStrategies:[],zapSel:null,zapRunning:false,zapState:'off',zapActive:null,srvSort:'default'};
let ws=null, wsRetry=0, wsTimer=null, autoConnectAttempted=false,manualConnect=false;
let sessionStart=null, sessionTimerInt=null, sessionBaseSec=0;
let modalReturnFocus=null;
if(new URLSearchParams(location.search).has('desktop'))document.documentElement.classList.add('custom-frame');
// Записи текущей сессии подключения (полный журнал — /api/diagnostics).
const logBuffer=[];
// sessionStart — абсолютный момент начала сессии, а не точка последней
// синхронизации. Прежняя схема складывала серверную базу с локальным
// отсчётом, и при двух источниках событий статистики секунды удваивались.
// Теперь показание целиком выводится из одной отметки времени.
function startSessionTimer(baseSec){
  const startedAt=Date.now()-(Number(baseSec)||0)*1000;
  // Подстраиваемся под сервер только при заметном расхождении, иначе
  // каждое обновление статистики дёргало бы цифру на доли секунды.
  if(sessionStart===null||Math.abs(startedAt-sessionStart)>1500) sessionStart=startedAt;
  if(!sessionTimerInt) sessionTimerInt=setInterval(tickSession,1000);
  tickSession();
}
function tickSession(){ if(sessionStart==null) return; const el=document.getElementById('stSession'); if(!el) return; el.textContent=fmtTime((Date.now()-sessionStart)/1000); }
function stopSessionTimer(){ sessionStart=null; if(sessionTimerInt){ clearInterval(sessionTimerInt); sessionTimerInt=null; } const el=document.getElementById('stSession'); if(el) el.textContent='00:00'; }
const PRESET_SET=[['telegram.exe','Telegram'],['Discord.exe','Discord'],['chrome.exe','Google Chrome'],['firefox.exe','Mozilla Firefox'],['steam.exe','Steam'],['spotify.exe','Spotify'],['opera.exe','Opera']];
async function requestJson(path,{method='POST',body=null,timeoutMs=10000}={}){ const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs),options={method,signal:controller.signal,headers:{}};if(method!=='GET'){options.headers['Content-Type']='application/json';options.body=JSON.stringify(body||{});}try{const r=await fetch(path,options);let data;try{data=await r.json();}catch(_){data={ok:false,error:`HTTP ${r.status}: некорректный ответ`};}if(!r.ok&&data.ok!==false)data={...data,ok:false,error:data.error||`HTTP ${r.status}`};return data;}catch(e){return {ok:false,error:e.name==='AbortError'?'Превышено время ожидания ответа':'Нет связи с приложением'};}finally{clearTimeout(timer);} }
function api(path,body,timeoutMs=10000){ return requestJson(path,{method:'POST',body,timeoutMs}); }
function apiGet(path,timeoutMs=10000){ return requestJson(path,{method:'GET',timeoutMs}); }
// Кнопками окна управляет Electron: renderer/js/shell-bridge.js подменяет эти
// функции. В обычном браузере окном владеет сам браузер.
function winMin(){} function winMax(){} function winClose(){}
function setBackendOnline(online){ ST.backendOnline=online; if(!online)applyStatus(); }
function connectWS(){ if(ws&&(ws.readyState===WebSocket.OPEN||ws.readyState===WebSocket.CONNECTING))return; clearTimeout(wsTimer); const scheme=location.protocol==='https:'?'wss':'ws'; ws=new WebSocket(`${scheme}://${location.host}/ws`); ws.onopen=()=>{wsRetry=0;setBackendOnline(false);}; ws.onmessage=ev=>{try{handle(JSON.parse(ev.data));}catch(e){addLog('Некорректное сообщение интерфейса: '+e,'warn');}}; ws.onerror=()=>ws.close(); ws.onclose=()=>{setBackendOnline(false);const delay=Math.min(15000,1000*Math.pow(1.7,wsRetry++));wsTimer=setTimeout(connectWS,delay);}; }
function handle(d){ switch(d.type){
  case 'state': ST.subscriptionBusy=!!d.subscriptionBusy;ST.backendOnline=true;ST.connected=!!d.connected;ST.status=d.status||'off';ST.server=d.server||'';ST.proto=d.activeProtocol||'vless';ST.groups=d.groups||[];ST.selGroup=d.selGroup;ST.selIndex=d.selIndex;ST.wgGroups=d.wgGroups||[];ST.selWgGroup=d.selWgGroup;ST.selWgIndex=d.selWgIndex;ST.appsConfig=d.appsConfig||{mode:'all',apps:[]};ST.settings=d.appSettings||{};ST.tunnel=d.tunnelSettings||{};ST.core=d.core||'';ST.appRoutes=[];ST.stars=Object.fromEntries((ST.settings.favorite_servers||[]).map(id=>[id,true]));ST.hwid=d.hwid||'';ST.tunnelPing={label:d.ping||'—',color:d.pingColor||'dim'};ST.zapStrategies=d.zapretStrategies||[];ST.zapRunning=!!d.zapretRunning;ST.zapState=d.zapretState||(ST.zapRunning?'on':'off');ST.zapActive=d.zapretStrategy;ST.zapSel=ST.zapSel||d.zapretSelected||d.zapretStrategy;ST.zapGameFilter=d.zapretGameFilter||null;ST.zapGameFilterSummary=d.zapretGameFilterSummary||null;ST.zapCoverage=d.zapretCoverage||null;ST.tgProxy=d.tgProxy||null;renderTgProxy(true);applyPlatform(d.platform);document.getElementById('tbVer').textContent='v'+(d.appVersion||'…');document.getElementById('aboutVer').textContent='v'+(d.appVersion||'…');document.getElementById('engineVer').textContent=d.coreVersions||('Mihomo '+(d.engineVersion||'…'));applyStatus();renderServers();renderWg();renderRules();renderModeCards();renderZapret();renderGameFilter();syncSettings();applyAppearance();if(d.stats)applyStats(d.stats);maybeAutoConnect();break;
  case 'subscription_busy': ST.subscriptionBusy=!!d.busy;if(!d.busy)ST.subProgress=null;renderSubscriptions();break;
  case 'subscription_progress': ST.subProgress={id:d.id,name:d.name,position:d.position,total:d.total};renderSubscriptions();break;
  case 'subscriptions_done': ST.subProgress=null;renderSubscriptions();notifySubscriptionsDone(d);break;
  case 'status': ST.status=d.state;if(d.state!=='on')ST.activeRoute=null;if(d.core)ST.core=d.core;if(d.state!=='on')ST.appRoutes=[];ST.connected=d.state==='on'||d.state==='error';if(d.server)ST.server=d.server;if(d.state==='off'){applyTraffic._t=null;applyTraffic._d=0;applyTraffic._u=0;}applyStatus();break;
  case 'operation_error': toast(d.message||d.error||'Ошибка операции','err');break;
  case 'routing_repaired': toast(d.message||'Маршруты переключены на основной VPN');break;
  // Буфер окна повторяет журнал сессии: очищается вместе с ним и не
  // принимает системные записи.
  case 'log': if(d.session!==false)addLog(d.msg,d.tag);break;
  case 'session_log_reset': logBuffer.length=0;break;
  // Резерв: ядро перевело трафик на запасной сервер или вернуло на выбранный.
  case 'active_server': ST.activeRoute=d.backup?d:null;applyStatus();toast(d.message,d.backup?'':'ok');break;
  case 'groups_updated': ST.groups=d.groups||[];ST.selGroup=d.selGroup;ST.selIndex=d.selIndex;renderServers();applyStatus();break;
  case 'wg_groups_updated': if(d.activeProtocol)ST.proto=d.activeProtocol;ST.wgGroups=d.wgGroups||[];ST.selWgGroup=d.selWgGroup;ST.selWgIndex=d.selWgIndex;renderWg();applyStatus();break;
  // appRoutes/ruleRoutes приходят только когда изменились — отсутствие полей
  // означает «как было», а не «маршрутов нет».
  case 'traffic_stats': applyTraffic(d);if(d.appRoutes){ST.appRoutes=d.appRoutes;updateRouteDetails();}if(d.ruleRoutes&&window.updateAdvancedRuleObservations)window.updateAdvancedRuleObservations(d.ruleRoutes);break;
  case 'stats': applyStats(d);break;
  case 'ping': ST.tunnelPing={label:d.value,color:d.color};renderHomePing();break;
  case 'ping_result': {const key=d.sid||`${d.gid}:${d.index}`;ST.pings[key]={label:d.label,color:d.color};updatePing('ping',key);renderHomePing();break;}
  case 'wg_ping_result': {const key=d.sid||`${d.gid}:${d.index}`;ST.wgPings[key]={label:d.label,color:d.color};updatePing('wping',key);break;}
  case 'ping_done': document.getElementById('pingBtn').classList.remove('scanning');if(ST.srvSort==='ping')renderServers();toast('Проверка серверов завершена','ok');break;
  case 'wg_ping_done': {if(ST.srvSort==='ping')renderWg();const btn=document.getElementById('wgPingBtn');if(btn)btn.classList.remove('scanning');toast('Проверка WG серверов завершена','ok');break;}
  case 'apps_config': ST.appsConfig=d.config;renderRules();renderModeCards();updateRouteDetails();applyStatus();break;
  case 'settings_updated': Object.assign(ST.tunnel,d.settings);syncSettings();renderServers();renderWg();renderRules();break;
  case 'app_settings_updated': Object.assign(ST.settings,d.settings);ST.stars=Object.fromEntries((ST.settings.favorite_servers||[]).map(id=>[id,true]));syncSettings();renderServers();break;
  case 'appearance_updated': ST.settings[d.kind==='avatar'?'avatar_file':'wallpaper_file']=d.file||'';applyAppearance(d.kind,d.url);break;
  case 'socks5_creds': ST.tunnel.socks5_user=d.user;ST.tunnel.socks5_pass=d.pass;document.getElementById('s5user').value=d.user;document.getElementById('s5pass').value=d.pass;break;
  case 'zapret_game_filter': ST.zapGameFilter=d.game_filter||null;renderGameFilter();break;
  case 'tgproxy_status': ST.tgProxy=d;renderTgProxy();break;
  case 'zapret_status': ST.zapRunning=!!d.running;ST.zapActive=d.strategy||null;ST.zapState=d.state||(ST.zapRunning?'on':'off');applyZapret(ST.zapState);break;
} }
function applyStatus(){ const btn=document.getElementById('connectBtn'),arc=document.getElementById('powerArc'),title=document.getElementById('statusTitle'),desc=document.getElementById('statusDesc'),lbl=document.getElementById('powerLbl'),dot=document.getElementById('tbDot'),tbSt=document.getElementById('tbState');btn.classList.remove('on','connecting');arc?.classList.remove('spin');title.classList.remove('on');dot.classList.remove('on');tbSt.classList.remove('on');btn.disabled=!ST.backendOnline||ST.status==='stopping';let connectionText='Не подключено';if(!ST.backendOnline){title.textContent='Статус неизвестен';desc.textContent='Нет связи с приложением · проверка состояния';lbl.textContent='Нет связи';connectionText='Нет связи с приложением';stopSessionTimer();}else if(ST.status==='error'){title.textContent='Ошибка туннеля';desc.textContent='Служба может быть активна · повторите отключение';lbl.textContent='Ошибка туннеля · нажмите, чтобы отключить';connectionText='Остановка не подтверждена';}else if(ST.status==='stopping'){btn.classList.add('connecting');arc?.classList.add('spin');title.textContent='Отключение…';desc.textContent='Ожидаем остановки туннеля';lbl.textContent='Отключение…';connectionText='Отключение…';}else if(ST.status==='connecting'){btn.classList.add('connecting');arc?.classList.add('spin');title.textContent='Подключение…';desc.textContent='Поднимаем туннель';lbl.textContent='Подключение… нажмите, чтобы отменить';connectionText='Подключение…';}else if(ST.status==='on'||ST.connected){btn.classList.add('on');title.classList.add('on');dot.classList.add('on');tbSt.classList.add('on');title.textContent='Туннель включён';desc.textContent=ST.activeRoute?.backup?`Резерв: трафик идёт через «${stripFlagEmoji(ST.activeRoute.name)}» — «${stripFlagEmoji(ST.activeRoute.selected)}» не отвечает`:'Интерфейс активен · доступность сети проверяется отдельно';lbl.textContent='Подключено · нажмите, чтобы отключить';connectionText=ST.server?('Подключено · '+stripFlagEmoji(ST.server)):'Подключено';if(sessionStart===null)startSessionTimer(0);}else{title.textContent='Не защищено';desc.textContent='Проведите ползунок или нажмите на него';lbl.textContent='Проведите или нажмите, чтобы подключить';document.getElementById('stDown').textContent='0.0';document.getElementById('stUp').textContent='0.0';stopSessionTimer();}btn.setAttribute('aria-label',lbl.textContent);tbSt.textContent=connectionText;document.querySelectorAll('[data-connection-state]').forEach(el=>{el.textContent=connectionText;el.classList.toggle('on',ST.connected&&ST.backendOnline);});const srv=selectedServer();const srvName=srv?(stripFlagEmoji(srv.remark)||'Без имени'):'Не выбран';document.getElementById('hcServer').textContent=srvName;const hcFlag=document.getElementById('hcServerFlag');if(hcFlag)hcFlag.innerHTML=srv?flagImg(ccFor(srv.remark)):'';document.getElementById('hcMode').textContent=({all:'Весь ПК',whitelist:'Только выбранные',blacklist:'Кроме выбранных'})[ST.appsConfig.mode]||'Весь ПК';document.getElementById('tgTun').classList.toggle('on',ST.proto!=='wg');document.getElementById('tgWg').classList.toggle('on',ST.proto==='wg');const pb=document.getElementById('protoBadge'),pr=(srv&&srv.protocol)?srv.protocol:ST.proto;pb.className='proto-badge '+(pr==='wg'?'wg':(srv&&srv.is_awg?'awg':'vless'));pb.textContent=(srv?.is_awg?'AWG':(pr||'vless')).toUpperCase();renderModeCards();syncCapabilities();renderRules();if(typeof renderSubscriptions==='function')renderSubscriptions();updateRouteDetails();renderHomeDash();}
function selectedServer(){ if(ST.proto==='wg'){ const g=ST.wgGroups.find(g=>g.id===ST.selWgGroup); return g&&g.servers[ST.selWgIndex]||null; } const g=ST.groups.find(g=>g.id===ST.selGroup); return g&&g.servers[ST.selIndex]||null; }
async function toggleConnect(automatic=false){ if(!automatic)manualConnect=true;if(!ST.backendOnline||ST.status==='stopping')return;if(ST.connected||ST.status==='on'||ST.status==='connecting'){const r=await api('/api/disconnect');if(!r.ok)toast(r.error||'Не удалось отключиться','err');return;}if(!selectedServer()){toast('Сначала выбери сервер','err');go(ST.proto==='wg'?'wg':'servers');return;}const r=await api('/api/connect',{protocol:ST.proto,auto:automatic===true});if(!r.ok)toast(r.error||'Не удалось подключиться','err');else if(r.warning)toast(r.warning);}
async function setProto(p){if(ST.connected||ST.status==='connecting'||ST.status==='stopping'){toast('Сначала отключите активный туннель','err');return;}const r=await api('/api/protocol',{protocol:p});if(!r.ok){toast(r.error||'Не удалось сменить протокол','err');return;}ST.proto=p;applyStatus();}
// Пресеты Smart DNS: подменяют ответы для разблокировки сервисов.
// Кнопка включает Comss — Xbox требует регистрации IP и у пользователей
// с динамическим адресом перестаёт работать молча.
const SMART_DNS_PRESETS=['xbox','xbox_dot','comss','comss_dot'];
async function toggleSecureDns(){ if(isNativeAwg()||ST.connected||ST.status==='connecting'||ST.status==='stopping'){toast('AI-DNS настраивается до подключения TUN/WireGuard','err');return;} const next=SMART_DNS_PRESETS.includes(ST.tunnel.dns_preset)?'cf_google':'comss_dot';const r=await api('/api/tunnel-settings',{dns_preset:next});if(!r.ok){toast(r.error||'Не удалось изменить AI-DNS','err');return;}ST.tunnel.dns_preset=next;syncSettings();toast(SMART_DNS_PRESETS.includes(next)?'AI-DNS включён · применится при подключении':'AI-DNS выключен','ok'); }
async function refreshPublicIp(){ const value=document.getElementById('ipVal'),note=document.getElementById('ipNote');value.textContent='Проверяю…';note.textContent='Определение внешнего адреса';const r=await api('/api/network/ip',{},15000);if(r.ok){value.textContent=r.ip;const version=r.version?`IPv${r.version}`:'IP';note.textContent=ST.connected?`${version} при работающем туннеле`:`Текущий внешний ${version}`;}else{value.textContent='Не определён';note.textContent=r.error||'Ошибка проверки';toast(note.textContent,'err');} }
function maybeAutoConnect(){ if(autoConnectAttempted||!ST.settings.autoconn)return;autoConnectAttempted=true;setTimeout(()=>{if(!manualConnect&&ST.backendOnline&&ST.status==='off'&&ST.settings.autoconn&&selectedServer())toggleConnect(true);},300); }
function fmtBytes(n){ n=n||0; if(n<1024)return n+' B'; const u=['KB','MB','GB','TB']; let i=-1; do{n/=1024;i++;}while(n>=1024&&i<u.length-1); return n.toFixed(1)+' '+u[i]; }
function fmtTime(sec){ sec=Math.floor(sec||0); const h=String(Math.floor(sec/3600)).padStart(2,'0'),m=String(Math.floor(sec%3600/60)).padStart(2,'0'),s=String(sec%60).padStart(2,'0'); return h!=='00'?`${h}:${m}:${s}`:`${m}:${s}`; }
function applyStats(s){ const sess=s.session_time??s.sessionSeconds??s.session;if(sess!==undefined&&(s.connected??ST.connected))startSessionTimer(sess);else if(!(s.connected??ST.connected))stopSessionTimer();const tu=s.today?.up??s.today_up??s.todayUp??0,td=s.today?.down??s.today_down??s.todayDown??0,au=s.total?.up??s.total_up??s.totalUp??0,ad=s.total?.down??s.total_down??s.totalDown??0;document.getElementById('statTodayUp').textContent='↑ '+fmtBytes(tu);const today=document.getElementById('stToday');if(today)today.textContent=fmtBytes(tu+td);document.getElementById('statTodayDn').textContent='↓ '+fmtBytes(td);document.getElementById('statTotalUp').textContent='↑ '+fmtBytes(au);document.getElementById('statTotalDn').textContent='↓ '+fmtBytes(ad); }
function applyTraffic(d){ const now=Date.now()/1000; if(applyTraffic._t){ const dt=now-applyTraffic._t; if(dt>0){ const dn=(d.totalDown-applyTraffic._d)*8/1e6/dt,up=(d.totalUp-applyTraffic._u)*8/1e6/dt; document.getElementById('stDown').textContent=Math.max(0,dn).toFixed(1);setGauge(Math.max(0,dn)); document.getElementById('stUp').textContent=Math.max(0,up).toFixed(1); } } applyTraffic._t=now; applyTraffic._d=d.totalDown; applyTraffic._u=d.totalUp; }
const FLAG_CODES=new Set('ad ae af ag ai al am ao aq ar as at au aw ax az ba bb bd be bf bg bh bi bj bl bm bn bo bq br bs bt bv bw by bz ca cc cd cf cg ch ci ck cl cm cn co cp cr cu cv cw cx cy cz de dg dj dk dm do dz ec ee eg eh er es et eu fi fj fk fm fo fr ga gb gd ge gf gg gh gi gl gm gn gp gq gr gs gt gu gw gy hk hm hn hr ht hu ic id ie il im in io iq ir is it je jm jo jp ke kg kh ki km kn kp kr kw ky kz la lb lc li lk lr ls lt lu lv ly ma mc md me mf mg mh ml mm mn mo mp mq mr ms mt mu mv mw mx my mz na nc ne nf ng ni nl no np nr nu nz om pa pc pe pf pg ph pk pl pm pn pr ps pt pw py qa re ro rs ru rw sa sb sc sd se sg sh si sj sk sl sm sn so sr ss st sv sx sy sz tc td tf tg th tj tk tl tm tn to tr tt tv tw tz ua ug um un us uy uz va vc ve vg vi vn vu wf ws xk xx ye yt za zm zw'.split(' '));
const COUNTRY_ALIASES={usa:'us','u.s.a.':'us','united states of america':'us',uk:'gb','u.k.':'gb',england:'gb',scotland:'gb',wales:'gb',uae:'ae','u.a.e.':'ae','south korea':'kr','north korea':'kp','czech republic':'cz',turkey:'tr','russian federation':'ru','viet nam':'vn'};
function normalizedCountryName(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[_|,;:()[\]{}]+/g,' ').replace(/\s+/g,' ').trim();}
function buildCountryNames(){const names=[];for(const [name,code] of Object.entries(COUNTRY_ALIASES))names.push([normalizedCountryName(name),code]);if(typeof Intl.DisplayNames==='function'){for(const locale of ['en','ru']){try{const display=new Intl.DisplayNames([locale],{type:'region'});for(const code of FLAG_CODES){if(code==='xx')continue;const label=display.of(code.toUpperCase());if(label&&label.toUpperCase()!==code.toUpperCase())names.push([normalizedCountryName(label),code]);}}catch(_){}}}return names.filter(([name])=>name).sort((a,b)=>b[0].length-a[0].length);}
const COUNTRY_NAMES=buildCountryNames();
function cleanName(name){ return String(name||'').replace(/[\u{1F1E6}-\u{1F1FF}]{1,2}/gu,'').replace(/[\u{1D400}-\u{1D7FF}\u{1F100}-\u{1F1FF}]/gu,'').trim(); }
function ccFor(name){if(!name)return'xx';const flag=[...name].filter(c=>c.codePointAt(0)>=0x1F1E6&&c.codePointAt(0)<=0x1F1FF);if(flag.length>=2){const code=flag.slice(0,2).map(c=>String.fromCharCode(c.codePointAt(0)-0x1F1E6+97)).join('');if(FLAG_CODES.has(code))return code;}const normalized=normalizedCountryName(name);for(const [country,code] of COUNTRY_NAMES){if((` ${normalized} `).includes(` ${country} `))return code;}const codeMatch=String(name).match(/(?:^|[^A-Z])([A-Z]{2})(?=$|[^A-Z])/);const code=codeMatch?.[1]?.toLowerCase();return code&&FLAG_CODES.has(code)?code:'xx';}
// Шрифты Windows не рисуют эмодзи-флаги: вместо 🇩🇪 в подписи появляются
// буквы «DE». Убираем их из текста и рисуем настоящий SVG из /static/flags.
function stripFlagEmoji(name){return String(name||'').replace(/[\u{1F1E6}-\u{1F1FF}]/gu,'').replace(/\s{2,}/g,' ').trim();}
function flagImg(code){const safe=FLAG_CODES.has(String(code||'').toLowerCase())?String(code).toLowerCase():'xx';return `<img src="/static/flags/4x3/${safe}.svg" alt="" draggable="false">`;}
function serverKey(server,gid,idx){ return server&&server.ui_id?server.ui_id:`${gid}:${idx}`; }
function renderServers(){ const grid=document.getElementById('srvGrid'),q=(document.getElementById('srvSearch').value||'').toLowerCase(),sort=ST.srvSort;let rows=[];ST.groups.forEach(g=>(g.servers||[]).forEach((s,i)=>rows.push({g:g.id,i,s,key:serverKey(s,g.id,i)})));if(q){const names=new Map(ST.groups.map(g=>[g.id,`${g.name||''} ${g.subscription?.provider_name||''}`.toLowerCase()]));rows=rows.filter(r=>(r.s.remark||'').toLowerCase().includes(q)||(names.get(r.g)||'').includes(q));}if(sort==='name')rows.sort((a,b)=>(a.s.remark||'').localeCompare(b.s.remark||'','ru'));if(sort==='ping')rows.sort((a,b)=>(parseInt(ST.pings[a.key]?.label)||999999)-(parseInt(ST.pings[b.key]?.label)||999999));document.getElementById('srvEmpty').classList.toggle('hidden',rows.length>0);grid.innerHTML=renderServerGroups(ST.groups,rows,'servers',q+'|'+sort,renderProxyServerRow,!!q); }
function renderProxyServerRow(r){const sel=r.g===ST.selGroup&&r.i===ST.selIndex,p=ST.pings[r.key],star=!!ST.stars[r.key],nm=cleanName(r.s.remark)||'Без имени';return `<div class="srv-row glass ${sel?'sel':''}" role="button" tabindex="0" data-action="select-server" data-gid="${esc(r.g)}" data-index="${r.i}"><span class="flag-code" aria-hidden="true">${flagImg(ccFor(r.s.remark||''))}</span><div class="srv-meta"><div class="srv-name">${esc(nm)}</div><div class="srv-proto">${esc(serverTransportLabel(r.s))}</div></div><div class="srv-actions"><span class="ping ${p?p.color:'dim'}" data-ping-id="${esc(r.key)}">${p?p.label:'—'}</span><button class="mini-btn star ${star?'on':''}" aria-label="${star?'Убрать из избранного':'Добавить в избранное'}" data-action="toggle-star" data-sid="${esc(r.key)}"><svg viewBox="0 0 24 24" fill="${star?'currentColor':'none'}"><path d="M12 3l2.5 6 6.5.5-5 4.2 1.6 6.3L12 17l-5.6 3 1.6-6.3-5-4.2 6.5-.5z"/></svg></button><button class="mini-btn probe" aria-label="Проверить соединение через сервер" title="Проверить соединение" data-action="probe-server" data-gid="${esc(r.g)}" data-index="${r.i}"><svg viewBox="0 0 24 24"><path d="M12 20v-6M12 4v4M5 12a7 7 0 0114 0"/><circle cx="12" cy="11" r="1.5"/></svg></button><button class="mini-btn del" aria-label="Удалить сервер" data-action="delete-server" data-gid="${esc(r.g)}" data-index="${r.i}"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg></button></div></div>`;}
function updatePing(pfx,key){ const el=[...document.querySelectorAll(`[data-ping-id]`)].find(item=>item.dataset.pingId===key),p=(pfx==='ping'?ST.pings:ST.wgPings)[key];if(el&&p){el.textContent=p.label;el.className='ping '+p.color;} }
// Пока VPN работает через Mihomo (TUN), сервер меняется на лету — без
// переподключения. В WireGuard и во время подключения/отключения — нельзя.
async function selectServer(gid,idx){ if(ST.status==='connecting'||ST.status==='stopping'){toast('Дождитесь завершения подключения или отключения','err');return;} if(ST.connected&&ST.proto==='wg'){toast('Сейчас подключён WireGuard: сменить сервер на лету можно только в режиме TUN','err');return;} const live=ST.connected;const previous=[ST.selGroup,ST.selIndex,ST.proto];ST.selGroup=gid;ST.selIndex=idx;ST.proto='vless';renderServers();applyStatus();const r=await api('/api/servers/select',{group_id:gid,index:idx});if(!r.ok){[ST.selGroup,ST.selIndex,ST.proto]=previous;renderServers();applyStatus();toast(r.error||'Не удалось выбрать сервер','err');return;} if(r.live||live){ST.activeRoute=null;applyStatus();toast(`Сервер переключён на «${stripFlagEmoji(selectedServer()?.remark||'')}» без переподключения`,'ok');} }
async function toggleStar(serverId){ const previous=!!ST.stars[serverId];ST.stars[serverId]=!previous;renderServers();const favorites=Object.keys(ST.stars).filter(id=>ST.stars[id]);const r=await api('/api/app-settings',{key:'favorite_servers',value:favorites});if(!r.ok){ST.stars[serverId]=previous;renderServers();toast(r.error||'Не удалось сохранить избранное','err');}else{ST.settings.favorite_servers=favorites;} }
// Проверка соединения, а не порта: запрос уходит через outbound самого ядра.
let probeBusy=false;
async function probeServer(gid,idx,button){
  if(probeBusy){toast('Проверка уже выполняется');return;}
  probeBusy=true;button?.classList.add('scanning');
  toast('Проверяем соединение через сервер…');
  try{
    // Проверка поднимает отдельное ядро и ждёт ответа сервера до ~35 с.
    const r=await api('/api/servers/probe',{group_id:gid,index:idx},45000);
    if(!r.ok){toast(r.error||'Не удалось проверить сервер','err');return;}
    toast(r.label+(r.detail?' · '+r.detail:''),r.state==='connected'?'ok':'err');
  }catch(_){toast('Не удалось проверить сервер','err');}
  finally{probeBusy=false;button?.classList.remove('scanning');}
}
async function delServer(gid,idx){ if(!confirm('Удалить выбранный сервер?'))return;const r=await api('/api/servers/delete',{group_id:gid,index:idx});if(!r.ok)toast(r.error||'Ошибка удаления','err');else toast('Сервер удалён','ok'); }
async function addServer(){ const el=document.getElementById('addLink'); const link=el.value.trim(); if(!link){toast('Вставь ссылку','err');return;} if(link.startsWith('http')){ const r=await api('/api/servers/import',{url:link}); if(r.ok){el.value='';toast('Подписка добавляется…','ok');}else toast(r.error||'Ошибка','err'); return; } const r=await api('/api/servers/add',{link}); if(r.ok){el.value='';toast('Сервер добавлен','ok');}else toast(r.error||'Ошибка','err'); }
async function pingAll(){ const btn=document.getElementById('pingBtn');btn.classList.add('scanning');const r=await api('/api/ping/all');if(!r.ok){btn.classList.remove('scanning');toast(r.error||'Не удалось запустить проверку','err');} }
async function refreshSubs(){ const total=ST.groups.filter(g=>g.url).length+ST.wgGroups.filter(g=>g.url).length;if(!total){toast('Нет подписок для обновления');return;}/* Одна очередь на бэкенде: параллельные запросы получали 409, и обновлялась только первая подписка. */const r=await api('/api/groups/refresh-all',{});if(r.ok)toast(`Обновляю подписки: ${r.queued||total}…`);else toast(r.error||'Обновление не запущено','err'); }
// Возможности ОС: на Linux пока нет Zapret, AmneziaWG и встроенного обновления
// (engine/platform_info.py). Недоступное скрывается или помечается.
function applyPlatform(platform){
  ST.platform=platform||{os:'windows',zapret:true,amneziawg:true,updates:true};
  const root=document.documentElement;
  root.classList.toggle('os-linux',ST.platform.os==='linux');
  root.classList.toggle('no-zapret',!ST.platform.zapret);
  root.classList.toggle('no-updates',!ST.platform.updates);
  const awg=document.querySelector('#page-wg .notice');
  if(awg&&!ST.platform.amneziawg)awg.innerHTML='<b>AmneziaWG</b> пока недоступен на Linux — обычный WireGuard работает через ядро VPN.';
}
// Итог приходит после сохранения результата. Одно уведомление на всю очередь,
// в том числе на автообновление при запуске.
function notifySubscriptionsDone(d){
  const results=d.results||[];if(!d.total)return;
  if(d.total===1&&results[0]){
    const r=results[0],name=`«${r.name||'Подписка'}»`;
    if(r.result==='updated')toast(`Подписка ${name} обновлена · серверов: ${r.accepted}`,'ok');
    else if(r.result==='unchanged')toast(`Подписка ${name} без изменений`,'ok');
    else toast(`Подписка ${name} не обновлена: ${r.error||'ошибка'}`,'err');
    return;
  }
  const parts=[];
  if(d.updated)parts.push(`обновлено ${d.updated}`);
  if(d.unchanged)parts.push(`без изменений ${d.unchanged}`);
  if(d.failed)parts.push(`с ошибкой ${d.failed}`);
  toast((d.auto?'Подписки при запуске: ':'Подписки: ')+(parts.join(' · ')||'нет результата'),d.failed?'err':'ok');
}
function renderWg(){ const grid=document.getElementById('wgGrid');let rows=[];ST.wgGroups.forEach(g=>(g.servers||[]).forEach((s,i)=>rows.push({g:g.id,i,s,key:serverKey(s,g.id,i)})));if(ST.srvSort==='name')rows.sort((a,b)=>(a.s.remark||'').localeCompare(b.s.remark||'','ru'));if(ST.srvSort==='ping')rows.sort((a,b)=>(parseInt(ST.wgPings[a.key]?.label)||999999)-(parseInt(ST.wgPings[b.key]?.label)||999999));document.getElementById('wgEmpty').classList.toggle('hidden',rows.length>0);grid.innerHTML=renderServerGroups(ST.wgGroups,rows,'wg',ST.srvSort,renderWgServerRow,false); }
function renderWgServerRow(r){const sel=r.g===ST.selWgGroup&&r.i===ST.selWgIndex,p=ST.wgPings[r.key],nm=cleanName(r.s.remark)||'WG сервер';return `<div class="srv-row glass ${sel?'sel':''}" role="button" tabindex="0" data-action="select-wg" data-gid="${esc(r.g)}" data-index="${r.i}"><span class="flag-code" aria-hidden="true">${flagImg(ccFor(r.s.remark||''))}</span><div class="srv-meta"><div class="srv-name">${esc(nm)}</div><div class="srv-proto">${r.s.is_awg?'AmneziaWG · нативный':'WireGuard'}</div></div><div class="srv-actions">${r.s.is_awg?'<span class="awg-tag">AWG</span>':''}<span class="ping ${p?p.color:'dim'}" data-ping-id="${esc(r.key)}">${p?p.label:'—'}</span><button class="mini-btn del" aria-label="Удалить WG сервер" data-action="delete-wg" data-gid="${esc(r.g)}" data-index="${r.i}"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg></button></div></div>`;}
async function selectWg(gid,idx){ if(ST.connected||ST.status==='connecting'||ST.status==='stopping'){toast('Сначала отключите VPN','err');return;} const previous=[ST.selWgGroup,ST.selWgIndex,ST.proto];ST.selWgGroup=gid;ST.selWgIndex=idx;ST.proto='wg';renderWg();applyStatus();const r=await api('/api/wg/servers/select',{group_id:gid,index:idx});if(!r.ok){[ST.selWgGroup,ST.selWgIndex,ST.proto]=previous;renderWg();applyStatus();toast(r.error||'Не удалось выбрать WG сервер','err');} }
async function delWg(gid,idx){ if(!confirm('Удалить выбранный WG сервер?'))return;const r=await api('/api/wg/servers/delete',{group_id:gid,index:idx});if(!r.ok)toast(r.error||'Ошибка удаления','err');else toast('WG сервер удалён','ok'); }
// Импорт .conf файлами: выбор через диалог или перетаскивание на поле конфига.
// Имя файла становится названием сервера.
async function wgAddFiles(files){
  const list=[...(files||[])];document.getElementById('wgFile').value='';if(!list.length)return;
  let added=0;const failed=[];
  for(const file of list){
    if(file.size>65536){failed.push(`${file.name}: файл больше 64 КБ`);continue;}
    let conf='';try{conf=(await file.text()).trim();}catch(_){failed.push(`${file.name}: не удалось прочитать`);continue;}
    if(!conf){failed.push(`${file.name}: пустой файл`);continue;}
    const r=await api('/api/wg/servers/add',{conf,name:file.name.replace(/\.(conf|txt)$/i,'')});
    if(r.ok)added+=r.added||0;else failed.push(`${file.name}: ${r.error||'ошибка'}`);
  }
  if(added)toast(`Добавлено серверов: ${added}`+(failed.length?` · не добавлено файлов: ${failed.length}`:''),failed.length?'':'ok');
  else toast(failed[0]||'Не удалось добавить конфиг','err');
  failed.forEach(line=>addLog('Импорт WG: '+line,'warn'));
}
async function wgAdd(){ const el=document.getElementById('wgConf'); const conf=el.value.trim(); if(!conf){toast('Вставь конфиг','err');return;} const r=await api('/api/wg/servers/add',{conf}); if(r.ok){el.value='';toast(`Добавлено серверов: ${r.added}`,'ok');}else toast(r.error||'Ошибка','err'); }
async function wgImport(){ const el=document.getElementById('wgSubUrl'); const url=el.value.trim(); if(!url.startsWith('http')){toast('Нужна http(s) ссылка','err');return;} const r=await api('/api/wg/servers/import',{url}); if(r.ok){el.value='';toast('WG подписка добавляется…','ok');}else toast(r.error||'Ошибка','err'); }
async function wgPingAll(){ const btn=document.getElementById('wgPingBtn');if(btn)btn.classList.add('scanning');const r=await api('/api/wg/ping/all');if(!r.ok){if(btn)btn.classList.remove('scanning');toast(r.error||'Не удалось запустить проверку WG','err');} }
function renderModeCards(){
  const awg=isNativeAwg(), m=awg?'all':(ST.appsConfig.mode||'all');
  [['modeAll','all'],['modeWl','whitelist'],['modeBl','blacklist']].forEach(([id,value])=>{
    const el=document.getElementById(id),active=m===value;
    el.classList.toggle('active',active);el.setAttribute('aria-pressed',String(active));
    el.disabled=awg||ST.connected||ST.status==='connecting'||ST.status==='stopping';
    el.title=awg?'Нативный AmneziaWG работает для всего компьютера':ST.connected?'Отключите VPN для смены режима':'';
  });
  const note=document.getElementById('routeNote');
  note.textContent=!ST.backendOnline?'Нет связи':ST.status==='connecting'?'Подключение…':!ST.connected?'VPN отключён':({all:'VPN для всего ПК',whitelist:'VPN для выбранных',blacklist:'VPN с исключениями'})[m];
  note.classList.toggle('connected',ST.connected&&ST.backendOnline);
  const visualMode=document.getElementById('routeVisualMode');if(visualMode)visualMode.textContent=awg?'AmneziaWG · весь ПК':({all:'Весь трафик',whitelist:'Выбранные приложения',blacklist:'Кроме выбранных'})[m];
  const action=document.getElementById('ruleModeAction');if(action)action.textContent=currentRuleAction();
}
async function setMode(m){ if(isNativeAwg()||ST.connected||ST.status==='connecting'||ST.status==='stopping'){toast('Смена режима доступна без активного туннеля, для TUN/WireGuard','err');return;} const previous=ST.appsConfig.mode;ST.appsConfig.mode=m;renderModeCards();renderRules();applyStatus();const r=await api('/api/apps/mode',{mode:m});if(!r.ok){ST.appsConfig.mode=previous;renderModeCards();renderRules();applyStatus();toast(r.error||'Не удалось изменить режим','err');} }
function renderRules(){ const list=document.getElementById('ruleList'),q=(document.getElementById('ruleSearch')?.value||'').toLowerCase(),mode=ST.appsConfig.mode||'all';let apps=ST.appsConfig.apps||[];document.getElementById('rulesCount').textContent=apps.length;if(q)apps=apps.filter(a=>(a.name||a.exe||'').toLowerCase().includes(q));document.getElementById('ruleEmpty').classList.toggle('hidden',apps.length>0);list.innerHTML=apps.map(a=>{const enabled=a.enabled!==false,badge=!enabled?'Выключено':isNativeAwg()?'Не применяется к AWG':mode==='blacklist'?'Напрямую':mode==='whitelist'?'Через VPN':'Список не используется',badgeClass=!enabled?'off':mode==='blacklist'?'direct':'';return `<div class="rule-row glass"><div class="rule-ico">💻</div><div class="rule-meta"><div class="rule-name">${esc(a.name||a.exe)}</div><div class="rule-type">${esc(a.exe)}</div><small class="rule-route-detail" data-route-exe="${esc(a.exe)}">${esc(appRouteDetail(a))}</small></div><span class="rule-badge ${badgeClass}">${badge}</span><button class="toggle ${enabled?'on':''}" ${ST.status!=='off'?'disabled':''} aria-label="${enabled?'Отключить':'Включить'} правило" data-action="toggle-app" data-exe="${esc(a.exe)}"></button><button class="mini-btn" aria-label="Переименовать правило" data-action="edit-app" data-exe="${esc(a.exe)}" data-name="${esc(a.name||a.exe)}"><svg viewBox="0 0 24 24"><path d="M17 3l4 4-11 11H6v-4z"/></svg></button><button class="mini-btn del" ${ST.status!=='off'?'disabled':''} aria-label="Удалить правило" data-action="remove-app" data-exe="${esc(a.exe)}"><svg viewBox="0 0 24 24"><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></svg></button></div>`;}).join(''); }
async function toggleApp(exe,el){ const next=!el.classList.contains('on');el.classList.toggle('on',next);const r=await api('/api/apps/toggle',{exe,enabled:next});if(!r.ok){el.classList.toggle('on',!next);toast(r.error||'Не удалось изменить правило','err');} }
async function removeApp(exe){ if(!confirm(`Удалить правило для ${exe}?`))return;const r=await api('/api/apps/remove',{exe});if(!r.ok)toast(r.error||'Ошибка удаления','err');else toast('Правило удалено','ok'); }
function openModal(id){const modal=document.getElementById(id);if(!modal)return;modal._returnFocus=document.activeElement;modal.classList.add('open');modal.setAttribute('aria-hidden','false');document.body.classList.add('modal-open');requestAnimationFrame(()=>modal.querySelector('input,button')?.focus());}
function closeModal(id){const modal=document.getElementById(id);if(!modal)return;modal.classList.remove('open');modal.setAttribute('aria-hidden','true');if(!document.querySelector('.modal-backdrop.open'))document.body.classList.remove('modal-open');const target=modal._returnFocus;if(target&&document.contains(target))target.focus();}
function modalBackdropClose(event,id){if(event.target===event.currentTarget)closeModal(id);}
function currentRuleAction(){if(isNativeAwg())return 'Не применяется к AWG';const mode=ST.appsConfig.mode||'all';return mode==='whitelist'?'Через VPN':mode==='blacklist'?'Без VPN':'Список не используется';}
function promptRule(){document.getElementById('ruleExe').value='';document.getElementById('ruleName').value='';document.getElementById('ruleModeAction').textContent=currentRuleAction();openModal('ruleModal');requestAnimationFrame(()=>document.getElementById('ruleExe').focus());}
async function saveRule(){const exeInput=document.getElementById('ruleExe'),nameInput=document.getElementById('ruleName'),button=document.getElementById('saveRuleBtn');let exe=exeInput.value.trim();if(!exe){toast('Укажите процесс приложения','err');exeInput.focus();return;}if(/[\\/:*?"<>|]/.test(exe)){toast('Укажите только имя процесса, без пути','err');exeInput.focus();return;}if(!exe.toLowerCase().endsWith('.exe'))exe+='.exe';const name=nameInput.value.trim()||exe.replace(/\.exe$/i,'');button.disabled=true;try{const r=await api('/api/apps/add',{exe,name});if(r.ok){closeModal('ruleModal');toast('Правило добавлено','ok');}else toast(r.error||'Не удалось добавить правило','err');}finally{button.disabled=false;}}
// Единственная реализация списка процессов живёт в process-picker.js:
// один источник данных (/api/apps/catalog) и один дочерний <dialog>.
async function openProcessPicker(anchor){
  const choice=await window.openProcessPicker({mode:'process',anchor:anchor||document.activeElement,current:document.getElementById('ruleExe').value.trim()});
  if(!choice)return;
  document.getElementById('ruleExe').value=choice.value;
  const name=document.getElementById('ruleName');
  if(!name.value.trim())name.value=choice.name||choice.value.replace(/\.exe$/i,'');
}
async function editRule(exe,name){ const nv=prompt('Новое имя правила:',name);if(!nv||nv.trim()===name)return;const r=await api('/api/apps/rename',{exe,name:nv.trim()});toast(r.ok?'Правило переименовано':(r.error||'Не удалось переименовать'),r.ok?'ok':'err'); }
async function exportRules(){ const r=await api('/api/apps/export');toast(r.ok?`Правила сохранены: ${r.path}`:(r.error||'Не удалось экспортировать'),r.ok?'ok':'err'); }
async function addPresetSet(){ let n=0; for(const [exe,name] of PRESET_SET){ const r=await api('/api/apps/add',{exe,name}); if(r.ok) n++; } toast(n?`Добавлено правил: ${n}`:'Все уже добавлены','ok'); }
async function savePorts(){ const socks=parseInt(document.getElementById('portSocks').value),http=parseInt(document.getElementById('portHttp').value),r=await api('/api/settings',{socks,http});if(r.ok){ST.settings.socks=socks;ST.settings.http=http;}else syncSettings();toast(r.ok?'Порты сохранены':(r.error||'Не удалось сохранить порты'),r.ok?'ok':'err'); }
async function updateTunnel(payload){ if((ST.connected||ST.status==='connecting'||ST.status==='stopping')&&Object.keys(payload).some(k=>k!=='server_sort')){toast('Отключите туннель перед изменением сетевых настроек','err');syncSettings();return false;} const r=await api('/api/tunnel-settings',payload);if(!r.ok){toast(r.error||'Не удалось сохранить настройку','err');syncSettings();return false;}Object.assign(ST.tunnel,payload);syncSettings();return true; }
async function tglTunnel(el,key){ const next=!el.classList.contains('on');el.classList.toggle('on',next);if(!await updateTunnel({[key]:next}))el.classList.toggle('on',!next); }
async function saveTunnelField(key,val){ if(await updateTunnel({[key]:val}))toast('Настройка сохранена','ok'); }
async function setPref(key,val){ await updateTunnel({[key]:val}); }
async function setPing(key,val){ const previous=ST.tunnel[key],r=await api('/api/ping-settings',{[key]:val});if(!r.ok){ST.tunnel[key]=previous;syncSettings();toast(r.error||'Не удалось сохранить настройку пинга','err');return;}ST.tunnel[key]=val;syncSettings(); }
async function setPingVal(key,val){ await setPing(key,val); }
async function tglSetting(el,key){ const next=!el.classList.contains('on');if(key==='lan'&&next&&!confirm('LAN-прокси откроет защищённые логином и паролем SOCKS5/HTTP порты для локальной сети. Продолжить?'))return;el.classList.toggle('on',next);const r=await api('/api/app-settings',{key,value:next});if(!r.ok){el.classList.toggle('on',!next);toast(r.error||'Не удалось сохранить настройку','err');return;}ST.settings[key]=next;if(key==='startup'&&next){const trayResult=await api('/api/app-settings',{key:'silent',value:true});if(trayResult.ok)ST.settings.silent=true;toast('Автозапуск включён · приложение будет стартовать в трее','ok');}syncSettings();if(key==='lan')toast('Настройка LAN применится после переподключения','ok'); }
async function regenSocks5(){ const r=await api('/api/socks5/regenerate');if(r.ok){ST.tunnel.socks5_user=r.user;ST.tunnel.socks5_pass=r.pass;document.getElementById('s5user').value=r.user;document.getElementById('s5pass').value=r.pass;toast('Новые данные SOCKS5 созданы','ok');}else toast(r.error||'Не удалось создать данные','err'); }
function togglePassword(btn){ const input=document.getElementById('s5pass'),show=input.type==='password';input.type=show?'text':'password';btn.title=show?'Скрыть пароль':'Показать пароль'; }
async function regenHwid(){ if(!confirm('Новый ID может отвязать подписку от текущего ключа. Меняйте его только по требованию продавца. Продолжить?'))return;const r=await api('/api/hwid/regenerate');if(r.ok){ST.hwid=r.hwid;document.getElementById('hwidVal').value=r.hwid;toast('Новый локальный ID создан','ok');}else toast(r.error||'Не удалось создать новый ID','err'); }
async function copyHwid(){ const v=document.getElementById('hwidVal').value;if(!v)return;try{await navigator.clipboard.writeText(v);toast('Локальный ID скопирован','ok');}catch(_){toast('Не удалось скопировать ID','err');} }
async function resetStats(which){ if(!confirm(which==='today'?'Сбросить статистику за сегодня?':'Полностью удалить всю статистику?'))return;const r=await api(which==='today'?'/api/stats/reset-today':'/api/stats/reset-all');toast(r.ok?'Статистика сброшена':(r.error||'Не удалось сбросить статистику'),r.ok?'ok':'err'); }
async function tglAnim(el){ await tglSetting(el,'animations'); }
/* Custom dropdowns */
function closeDropdowns(){document.querySelectorAll('.dd.open').forEach(d=>{d.classList.remove('open');d.closest('.set-row')?.classList.remove('dd-open');d.querySelector('.dd-trigger')?.setAttribute('aria-expanded','false');});}
function ddToggle(id){ const el=document.getElementById(id),willOpen=!el.classList.contains('open');closeDropdowns();if(willOpen){el.classList.add('open');el.closest('.set-row')?.classList.add('dd-open');}el.querySelector('.dd-trigger')?.setAttribute('aria-expanded',String(willOpen)); }
document.addEventListener('click',e=>{ if(!e.target.closest('.dd')) closeDropdowns(); });
async function setServerSort(v){ if(await updateTunnel({server_sort:v})){ST.srvSort=v;renderServers();renderWg();} }
async function pickSort(v,_lbl,_el){ closeDropdowns();await setServerSort(v); }
async function pickDns(v,_lbl,_el){ closeDropdowns();if(v==='custom'&&!(ST.tunnel.custom_dns||'').trim()){toast('Сначала укажите адреса в поле «Свой DNS»','err');document.getElementById('customDns')?.focus();return;}await updateTunnel({dns_preset:v}); }
function segSet(id,val){ document.querySelectorAll(`#${id} button`).forEach(b=>b.classList.toggle('on',b.dataset.v===val)); }
function syncSettings(){
  const s=ST.settings,t=ST.tunnel;
  document.body.classList.toggle('reduce-effects',s.animations===false);

  document.querySelectorAll('.toggle[data-sk]').forEach(el=>{const enabled=s[el.dataset.sk]===true;el.classList.toggle('on',enabled);el.setAttribute('role','switch');el.setAttribute('aria-checked',String(enabled));});
  document.querySelectorAll('.toggle[data-tk]').forEach(el=>el.classList.toggle('on',!!t[el.dataset.tk]));
  if(s.socks)document.getElementById('portSocks').value=s.socks;
  if(s.http)document.getElementById('portHttp').value=s.http;
  if(t.socks5_user!==undefined)document.getElementById('s5user').value=t.socks5_user||'';
  if(t.socks5_pass!==undefined)document.getElementById('s5pass').value=t.socks5_pass||'';
  if(t.ping_url)document.getElementById('pingUrl').value=t.ping_url;
  if(t.ping_timeout)document.getElementById('pingTimeout').value=t.ping_timeout;
  segSet('segPing',t.ping_type||'tcp');segSet('segIp',t.preferred_ip||'auto');
  ST.srvSort=t.server_sort||'default';segSet('segSort',ST.srvSort);
  const sortMap={default:'По умолчанию',ping:'По пингу',name:'По имени'};
  document.getElementById('ddSortLbl').textContent=sortMap[ST.srvSort]||sortMap.default;
  document.querySelectorAll('#ddSort .dd-item').forEach(i=>i.classList.toggle('on',i.dataset.v===ST.srvSort));
  const dnsMap={cf_google:'Cloudflare + Google',cloudflare:'Cloudflare (1.1.1.1)',google:'Google (8.8.8.8)',adguard:'AdGuard',xbox:'Xbox · Smart DNS',xbox_dot:'Xbox · Smart DNS',comss:'Comss · Smart DNS',comss_dot:'Comss · Smart DNS',quad9:'Quad9',custom:'Свой DNS'};
  const customDns=document.getElementById('customDns');if(customDns&&document.activeElement!==customDns)customDns.value=t.custom_dns||'';
  const dv=t.dns_preset||'cf_google';document.getElementById('ddDnsLbl').textContent=dnsMap[dv]||dv;
  document.querySelectorAll('#ddDns .dd-item').forEach(i=>i.classList.toggle('on',i.dataset.v===dv));
  const geminiOn=SMART_DNS_PRESETS.includes(dv);document.getElementById('tgSecureDns').classList.toggle('on',geminiOn);document.getElementById('geminiDnsLabel').textContent=geminiOn?'AI-DNS · выбран':'AI-DNS';syncCapabilities();
  document.getElementById('hwidVal').value=ST.hwid||'';
  const startup=document.getElementById('autostartState');startup.classList.toggle('on',!!s.startup);startup.querySelector('strong').textContent=s.startup?'Автозапуск активен':'Запуск вручную';startup.querySelector('small').textContent=s.startup?(s.silent?'Стартует вместе с Windows в системном трее':'Стартует вместе с Windows'):'Автозапуск Windows отключён';
}

function applyAppearance(kind,url){
  const avatarUrl=kind==='avatar'?url:(ST.settings.avatar_file?`/api/appearance/avatar?v=${Date.now()}`:'');
  const wallpaperUrl=kind==='wallpaper'?url:(ST.settings.wallpaper_file?`/api/appearance/wallpaper?v=${Date.now()}`:'');
  if(kind!=='wallpaper')document.querySelectorAll('#sidebarAvatar,#avatarPreview').forEach(el=>{el.style.backgroundImage=avatarUrl?`url("${avatarUrl}")`:'';el.classList.toggle('has-image',!!avatarUrl);});
  if(kind!=='avatar'){const layer=document.getElementById('customWallpaper'),preview=document.getElementById('wallpaperPreview');layer.style.backgroundImage=wallpaperUrl?`url("${wallpaperUrl}")`:'';layer.classList.toggle('active',!!wallpaperUrl);document.documentElement.classList.toggle('has-wallpaper',!!wallpaperUrl);preview.style.backgroundImage=wallpaperUrl?`url("${wallpaperUrl}")`:'';preview.classList.toggle('has-image',!!wallpaperUrl);}
}

async function uploadAppearance(kind,input){
  const file=input.files&&input.files[0];if(!file)return;const form=new FormData();form.append('file',file);
  try{const response=await fetch(`/api/appearance/${kind}`,{method:'POST',body:form});const result=await response.json();if(!result.ok)throw new Error(result.error||'Не удалось загрузить изображение');ST.settings[kind==='avatar'?'avatar_file':'wallpaper_file']=result.file||'';applyAppearance(kind,result.url);toast(kind==='avatar'?'Аватар обновлён':'Фон приложения обновлён','ok');}catch(error){toast(error.message,'err');}finally{input.value='';}
}
async function resetAppearance(kind){const result=await api(`/api/appearance/${kind}/reset`);if(!result.ok){toast(result.error||'Не удалось сбросить оформление','err');return;}ST.settings[kind==='avatar'?'avatar_file':'wallpaper_file']='';applyAppearance(kind,'');toast(kind==='avatar'?'Аватар сброшен':'Фон сброшен','ok');}

async function copyLogs(){
  const result=await apiGet('/api/diagnostics');
  if(!result.ok){toast(result.error||'Журнал недоступен','err');return;}
  if(result.empty){toast('Подключений ещё не было — журнал пуст');return;}
  try{await navigator.clipboard.writeText(result.text);toast('Скопирован журнал последнего подключения','ok');}
  catch(_){toast('Нет доступа к буферу обмена','err');}
}
async function copySystemLogs(){
  const result=await apiGet('/api/diagnostics/system');
  if(!result.ok){toast(result.error||'Журнал недоступен','err');return;}
  try{await navigator.clipboard.writeText(result.text);toast('Скопирован системный журнал · до 4 МБ','ok');}
  catch(_){toast('Нет доступа к буферу обмена','err');}
}
function renderZapret(){
  const list=document.getElementById('zapList'),strats=ST.zapStrategies||[],count=document.getElementById('zapCount');
  if(count)count.textContent=String(strats.length);
  if(!strats.some(s=>s.id===ST.zapSel))ST.zapSel=strats[0]?.id||null;
  const groups=new Map();
  for(const strategy of strats){const category=strategy.category||'Другие';if(!groups.has(category))groups.set(category,[]);groups.get(category).push(strategy);}
  const card=s=>`<div class="zap-card glass ${s.id===ST.zapSel?'sel':''} ${s.experimental?'experimental':''}" role="button" tabindex="0" title="${esc(s.source_file||s.name||s.id)}" data-action="select-zapret" data-id="${esc(s.id)}"><div class="zap-ico">${esc(s.icon||'✦')}</div><div class="zap-card-body"><div class="zap-name">${esc(s.name||s.id)}</div><div class="zap-sub">${esc(s.desc||'Стратегия обхода DPI')}</div><div class="zap-tags">${(s.tags||['Discord','YouTube']).map(t=>`<span class="zap-tag">${esc(t)}</span>`).join('')}</div></div><div class="zap-radio"></div></div>`;
  list.innerHTML=[...groups].map(([category,items])=>`<section class="zap-group"><div class="zap-group-head"><span>${esc(category)}</span><b>${items.length}</b></div>${items.map(card).join('')}</section>`).join('')||'<div class="empty"><b>Нет стратегий</b><p>Добавь winws.exe и WinDivert64.sys в папку bin/</p></div>';
  applyZapret(ST.zapState);
  filterZapret();
}
function applyZapret(state){ ST.zapState=state;const t=document.getElementById('zapT'),d=document.getElementById('zapD'),btn=document.getElementById('zapBtn'),head=document.getElementById('zapHeadState');const active=state==='on',busy=state==='starting'||state==='stopping';document.getElementById('zapStatus').classList.toggle('on',active);btn.disabled=state==='stopping';btn.classList.toggle('running',active||busy);t.textContent=active?'Активен':state==='starting'?'Запуск…':state==='stopping'?'Остановка…':'Не активен';d.textContent=active?'Работает: '+(ST.zapStrategies.find(s=>s.id===ST.zapActive)?.name||ST.zapActive||'Zapret'):state==='starting'?'Можно отменить запуск':state==='stopping'?'Ожидаем остановки процесса':'Выберите стратегию и нажмите «Запустить»';btn.textContent=active?'■ Остановить':state==='starting'?'Отменить запуск':state==='stopping'?'Остановка…':'▶ Запустить выбранную стратегию';head.textContent=t.textContent;head.classList.toggle('on',active); }
async function toggleZapret(){ if(ST.zapState==='stopping')return;const stop=ST.zapRunning||ST.zapState==='starting';applyZapret(stop?'stopping':'starting');const r=stop?await api('/api/zapret/stop'):ST.zapSel?await api('/api/zapret/start',{strategy_id:ST.zapSel}):{ok:false,error:'Выбери стратегию'};if(!r.ok){applyZapret(ST.zapRunning?'on':'off');toast(r.error||'Не удалось изменить состояние Zapret','err');} }
// Игровой фильтр Zapret: отдельный блок настроек на странице Zapret.
// Наружу показываем только эффективную настройку — сырую команду winws нет.
const GF_MODE_LABELS={off:'Выключен',udp:'Только UDP',tcp:'Только TCP',both:'TCP + UDP'};
const GF_IPSET_LABELS={list:'Только адреса из списка',all:'Все адреса'};
const GF_SCOPE_LABELS={standard:'Стандартный охват стратегии',extended:'Расширенный системный охват',custom:'Пользовательские фильтры'};
function gameFilterInputs(){return {scope:document.getElementById('gfScope'),mode:document.getElementById('gfMode'),ipset:document.getElementById('gfIpset'),tcp_start:document.getElementById('gfTcpStart'),tcp_end:document.getElementById('gfTcpEnd'),udp_start:document.getElementById('gfUdpStart'),udp_end:document.getElementById('gfUdpEnd')};}
function renderGameFilter(){
  const gf=ST.zapGameFilter||{scope:'standard',mode:'off',ipset:'list',tcp_start:1024,tcp_end:65535,udp_start:1024,udp_end:65535},f=gameFilterInputs();
  if(!f.scope)return;
  const scope=gf.scope||'standard';
  f.scope.value=scope;f.mode.value=gf.mode||'off';f.ipset.value=gf.ipset||'list';
  for(const key of ['tcp_start','tcp_end','udp_start','udp_end'])f[key].value=gf[key];
  // Стандартный охват — это ровно стратегия: лишние поля только путают.
  // Расширенный использует проверенные диапазоны, поэтому их не редактируют.
  document.getElementById('gfModeField').hidden=scope==='standard';
  document.getElementById('gfIpsetField').hidden=scope==='standard';
  document.getElementById('gfRanges').hidden=scope!=='custom';
  const cov=ST.zapCoverage||null;
  document.getElementById('gfScopeNote').textContent=(cov&&cov.notes&&cov.notes[0])||'';
  const on=(gf.mode||'off')!=='off',tcp=['tcp','both'].includes(gf.mode),udp=['udp','both'].includes(gf.mode);
  const range=(a,b)=>a===b?String(a):`${a}–${b}`;
  document.getElementById('gfSummary').textContent=GF_SCOPE_LABELS[scope]||scope;
  const list=(items,empty)=>items&&items.length?items.join(', '):empty;
  const rows=[
    ['Охват',GF_SCOPE_LABELS[scope]||scope],
    ['Обрабатываемые протоколы',cov?list(cov.protocols,'—'):'—'],
    ['Охваченные порты',cov?cov.ports_label:'—'],
    ['Ограничение по сайтам',cov?list(cov.hostlists.concat(cov.domains),'нет — обрабатываются любые домены'):'—'],
    ['Ограничение по адресам',cov?list(cov.ipsets,'нет — обрабатываются любые адреса'):'—'],
    ['Исключения',cov?list(cov.excludes,'нет'):'—'],
    ['Игровой фильтр',on?`${GF_MODE_LABELS[gf.mode]} · TCP ${tcp?range(gf.tcp_start,gf.tcp_end):'—'} · UDP ${udp?range(gf.udp_start,gf.udp_end):'—'}`:'выключен'],
    ['Профиль Zapret',(ST.zapStrategies||[]).find(s=>s.id===(ST.zapSel||ST.zapActive))?.name||'не выбран'],
    ['Изменения применяются','после перезапуска обхода'],
  ];
  document.getElementById('gfEffective').innerHTML=rows.map(([k,v])=>`<div class="gf-row"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
  document.getElementById('gfCoverageNotes').innerHTML=(cov?cov.notes.slice(1):[]).map(n=>`<li>${esc(n)}</li>`).join('');
  document.getElementById('zapGameFilter').classList.toggle('gf-on',scope!=='standard');
}
let gameFilterBusy=false;
async function saveGameFilter(){
  if(gameFilterBusy)return;
  const f=gameFilterInputs(),error=document.getElementById('gfError');
  const payload={scope:f.scope.value,mode:f.mode.value,ipset:f.ipset.value};
  for(const key of ['tcp_start','tcp_end','udp_start','udp_end']){
    const raw=f[key].value.trim(),numeric=Number(raw);
    if(!raw||!Number.isInteger(numeric)||numeric<1||numeric>65535){error.textContent='Порт должен быть целым числом от 1 до 65535';return;}
    payload[key]=numeric;
  }
  for(const proto of ['tcp','udp'])if(payload[proto+'_start']>payload[proto+'_end']){error.textContent=proto.toUpperCase()+': начало диапазона не может быть больше конца';return;}
  error.textContent='';gameFilterBusy=true;
  try{
    const result=await api('/api/zapret/game-filter',{game_filter:payload});
    if(!result.ok){error.textContent=result.error||'Не удалось сохранить охват обхода';renderGameFilter();return;}
    ST.zapGameFilter=result.game_filter;ST.zapGameFilterSummary=result.summary||null;ST.zapCoverage=result.coverage||null;renderGameFilter();toast('Охват обхода сохранён','ok');
  }catch(_){error.textContent='Не удалось сохранить охват обхода';}
  finally{gameFilterBusy=false;}
}
async function refreshCoverage(){
  const id=ST.zapSel||ST.zapActive;if(!id)return;
  try{const r=await fetch('/api/zapret/coverage?strategy_id='+encodeURIComponent(id));const d=await r.json();if(d.ok){ST.zapCoverage=d.coverage;renderGameFilter();}}catch(_){}
}
// Telegram WS Proxy на странице Zapret. Порт в поле не перезаписывается
// событиями, пока пользователь его редактирует.
let tgProxyBusy=false;
function renderTgProxy(resetPort){
  const p=ST.tgProxy;if(!p)return;
  const on=p.state==='on',port=document.getElementById('tgpPort');
  if(resetPort||document.activeElement!==port)port.value=p.port;
  document.getElementById('tgpSecret').value='dd'+p.secret;
  document.getElementById('tgpSummary').textContent=on?`Работает на ${p.host}:${p.port}`:'Выключен';
  const head=document.getElementById('tgpHeadState');head.textContent=on?'Работает':'Выключен';head.classList.toggle('on',on);
  document.getElementById('tgProxy').classList.toggle('gf-on',on);
  const moved=on&&Number(port.value)!==p.port;
  const btn=document.getElementById('tgpBtn');btn.classList.toggle('running',on&&!moved);btn.disabled=tgProxyBusy;
  btn.textContent=tgProxyBusy?'Подождите…':moved?'↻ Перезапустить на новом порту':on?'■ Остановить прокси':'▶ Запустить прокси';
  document.getElementById('tgpOpen').disabled=!on;
}
async function tgProxyRequest(path,body){
  const error=document.getElementById('tgpError');tgProxyBusy=true;error.textContent='';renderTgProxy();
  try{const r=await api(path,body,15000);if(r.state)ST.tgProxy={...ST.tgProxy,...r};if(!r.ok)error.textContent=r.error||'Не удалось изменить состояние прокси';return r;}
  finally{tgProxyBusy=false;renderTgProxy();}
}
async function toggleTgProxy(){
  if(tgProxyBusy)return;
  if(ST.tgProxy?.state==='on'&&Number(document.getElementById('tgpPort').value)===ST.tgProxy.port){await tgProxyRequest('/api/tgproxy/stop');return;}
  const raw=document.getElementById('tgpPort').value.trim(),port=Number(raw);
  if(!raw||!Number.isInteger(port)||port<1024||port>65535){document.getElementById('tgpError').textContent='Порт должен быть целым числом от 1024 до 65535';return;}
  const r=await tgProxyRequest('/api/tgproxy/start',{port});if(r.ok)toast('Telegram-прокси запущен · добавьте его в Telegram','ok');
}
async function regenTgProxySecret(){
  if(tgProxyBusy)return;
  const r=await tgProxyRequest('/api/tgproxy/secret');if(r.ok)toast('Новый ключ создан · добавьте прокси в Telegram заново','ok');
}
async function openTgProxy(){ const r=await api('/api/tgproxy/open');if(!r.ok)toast(r.error||'Не удалось открыть Telegram','err'); }
async function copyTgProxyLink(){ const link=ST.tgProxy?.link;if(!link)return;try{await navigator.clipboard.writeText(link);toast('Ссылка на прокси скопирована','ok');}catch(_){toast('Не удалось скопировать ссылку','err');} }
const NAV_LABELS={home:'Главная',servers:'Серверы',wg:'WireGuard',routing:'Маршрутизация',settings:'Настройки',zapret:'Zapret',telegram:'Telegram'};
document.querySelectorAll('.nav').forEach(n=>{n.onclick=()=>go(n.dataset.page);n.setAttribute('role','button');n.tabIndex=0;n.setAttribute('aria-label',NAV_LABELS[n.dataset.page]||n.dataset.page);n.title=NAV_LABELS[n.dataset.page]||n.dataset.page;});
const wgPingButton=document.querySelector('#page-wg .page-head .icon-btn');if(wgPingButton){wgPingButton.id='wgPingBtn';wgPingButton.setAttribute('aria-label','Проверить задержку WG серверов');wgPingButton.title='Проверить пинг WG';}
const BUTTON_LABELS={refreshSubs:'Обновить подписки',copyHwid:'Скопировать HWID',regenHwid:'Создать новый HWID',regenSocks5:'Создать логин и пароль',resetStats:'Сбросить статистику'};document.querySelectorAll('button:not([aria-label])').forEach(button=>{const text=button.textContent.trim(),handler=button.getAttribute('onclick')||'',name=Object.keys(BUTTON_LABELS).find(item=>handler.startsWith(item+'('));if(text)button.setAttribute('aria-label',text);else if(name)button.setAttribute('aria-label',BUTTON_LABELS[name]);});
document.querySelectorAll('.toggle:not(button)').forEach(el=>{el.setAttribute('role','switch');el.tabIndex=0;el.setAttribute('aria-checked',String(el.classList.contains('on')));const label=el.closest('.set-row')?.querySelector('.set-name')?.textContent;if(label)el.setAttribute('aria-label',label);});
const switchObserver=new MutationObserver(records=>records.forEach(({target})=>{if(target.matches('[role="switch"]'))target.setAttribute('aria-checked',String(target.classList.contains('on')));}));document.querySelectorAll('[role="switch"]').forEach(el=>switchObserver.observe(el,{attributes:true,attributeFilter:['class']}));
document.addEventListener('keydown',event=>{if((event.key==='Enter'||event.key===' ')&&event.target.matches('[role="button"],[role="switch"]')){event.preventDefault();event.target.click();}});
document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;if(document.getElementById('processPicker')?.open)return;if(document.getElementById('ruleModal').classList.contains('open'))closeModal('ruleModal');else closeDropdowns();});
document.addEventListener('click',event=>{const target=event.target.closest('[data-action]');if(!target)return;event.stopPropagation();const action=target.dataset.action,idx=Number(target.dataset.index);if(action==='more-rows'){rowLimits[target.dataset.list].limit+=100;target.dataset.list==='wg'?renderWg():renderServers();}else if(action==='select-server')selectServer(target.dataset.gid,idx);else if(action==='toggle-star')toggleStar(target.dataset.sid);else if(action==='delete-server')delServer(target.dataset.gid,idx);else if(action==='probe-server')probeServer(target.dataset.gid,idx,target);else if(action==='select-wg')selectWg(target.dataset.gid,idx);else if(action==='delete-wg')delWg(target.dataset.gid,idx);else if(action==='toggle-app')toggleApp(target.dataset.exe,target);else if(action==='edit-app')editRule(target.dataset.exe,target.dataset.name);else if(action==='remove-app')removeApp(target.dataset.exe);else if(action==='select-zapret'){ST.zapSel=target.dataset.id;renderZapret();renderGameFilter();refreshCoverage();}});
function go(page){ document.querySelectorAll('.nav').forEach(n=>n.classList.toggle('on',n.dataset.page===page)); document.querySelectorAll('.page').forEach(p=>p.classList.remove('active')); const el=document.getElementById('page-'+page); if(el) el.classList.add('active'); }
function esc(s){ return String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function addLog(msg,tag){const t=new Date().toTimeString().slice(0,8);logBuffer.push(`[${t}] [${String(tag||'log').toUpperCase()}] ${String(msg||'')}`);while(logBuffer.length>1000)logBuffer.shift();}
let _tt; function toast(msg,kind){ const el=document.getElementById('toast'); el.textContent=msg; el.className='show '+(kind||''); clearTimeout(_tt); _tt=setTimeout(()=>el.className='',2600); }
connectWS();
function isNativeAwg(){return ST.proto==='wg'&&!!selectedServer()?.is_awg;}
function syncCapabilities(){
  const awg=isNativeAwg(),locked=ST.connected||ST.status==='connecting'||ST.status==='stopping', selected=SMART_DNS_PRESETS.includes(ST.tunnel.dns_preset);
  const dns=document.getElementById('tgSecureDns');dns.disabled=awg||locked;
  dns.classList.toggle('on',!awg&&selected);
  document.getElementById('geminiDnsLabel').textContent=awg?'DNS из AWG':selected?(ST.connected?'AI-DNS · действует':'AI-DNS · выбран'):'AI-DNS';
  dns.title=awg?'DNS берётся из конфигурации AmneziaWG':locked?'Для изменения отключите туннель':'Smart DNS для TUN/WireGuard: запросы идут к нему напрямую, мимо туннеля, иначе подмена ответов не работает';
  document.getElementById('hcMode').textContent=awg?'Весь ПК · AWG':({all:'Весь ПК',whitelist:'Только выбранные',blacklist:'Кроме выбранных'})[ST.appsConfig.mode]||'Весь ПК';
  document.querySelectorAll('.awg-limit').forEach(el=>el.classList.toggle('hidden',!awg));
  document.querySelectorAll('#portSocks,#portHttp,#s5user,#s5pass,#ddDns,#customDns,[data-tk]').forEach(el=>{
    const container=el.closest('.set-row,.port-card')||el;
    container.classList.toggle('unavailable',awg);
    container.title=awg?'Не применяется к нативному AmneziaWG':'';
    if(el.matches('input,button'))el.disabled=awg||locked;
    if(el.matches('[role="switch"]')){el.setAttribute('aria-disabled',String(awg||locked));el.tabIndex=awg||locked?-1:0;}
  });
  const dd=document.getElementById('ddDns');dd.classList.toggle('unavailable',awg||locked);
}
function filterZapret(){
  const query=(document.getElementById('zapSearch')?.value||'').toLocaleLowerCase();
  document.querySelectorAll('#page-zapret [data-action="select-zapret"]').forEach(el=>el.hidden=!el.textContent.toLocaleLowerCase().includes(query));
}
function jumpSetting(index){
  const section=document.querySelectorAll('#page-settings .sec')[index];
  const pane=document.querySelector('#page-settings>.scroll');
  if(section&&pane)pane.scrollTo({top:section.offsetTop-pane.offsetTop,behavior:'smooth'});
}
const settingNav=document.getElementById('settingNav');
document.querySelectorAll('#page-settings .sec').forEach((section,index)=>{
  const label=section.querySelector('.sec-lbl')?.textContent;
  if(!label)return;const button=document.createElement('button');button.type='button';button.textContent=label;
  button.onclick=()=>jumpSetting(index);settingNav.append(button);
});
document.addEventListener('click',event=>{
  if(event.target.closest('.unavailable,[aria-disabled="true"]')){
    event.preventDefault();event.stopImmediatePropagation();
    toast('Эта настройка не применяется к текущему туннелю','err');
  }
},true);
// Bounded DOM size: search/sort applies to the full collection, rendering is paginated.
const rowLimits={servers:{key:'',limit:100},wg:{key:'',limit:100}};
function setWindowMaximized(value){const button=document.querySelector('.win-btns button:nth-child(2)');if(!button)return;button.setAttribute('aria-label',value?'Восстановить размер окна':'Развернуть окно');button.title=button.getAttribute('aria-label');button.querySelector('svg').innerHTML=value?'<path d="M4 2h6v6M2 4h6v6H2z"/>':'<rect x="2.5" y="2.5" width="7" height="7" rx="1"/>';}
function limitedRows(rows,list,key){const state=rowLimits[list];if(state.key!==key){state.key=key;state.limit=100;}return rows.slice(0,state.limit);}
function moreRowsButton(rows,list){return rows.length>rowLimits[list].limit?`<button class="btn secondary load-more" data-action="more-rows" data-list="${list}">Показать ещё · ${rowLimits[list].limit} из ${rows.length}</button>`:'';}
// Keep Tab inside the topmost dialog. Nested dialogs restore their own opener.
document.addEventListener('keydown',event=>{
  if(event.key!=='Tab')return;
  const modal=[...document.querySelectorAll('.modal-backdrop.open')].at(-1);if(!modal)return;
  const items=[...modal.querySelectorAll('button,input,textarea,select,[tabindex="0"]')].filter(el=>!el.disabled&&el.getClientRects().length);
  if(!items.length){event.preventDefault();return;}
  const first=items[0],last=items.at(-1);
  if(event.shiftKey&&(document.activeElement===first||!modal.contains(document.activeElement))){event.preventDefault();last.focus();}
  else if(!event.shiftKey&&(document.activeElement===last||!modal.contains(document.activeElement))){event.preventDefault();first.focus();}
});
document.querySelectorAll('.dd').forEach(dd=>{
  const trigger=dd.querySelector('.dd-trigger'),items=[...dd.querySelectorAll('.dd-item')];if(!trigger)return;
  trigger.tabIndex=0;trigger.setAttribute('role','button');trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
  const name=dd.closest('.set-row')?.querySelector('.set-name')?.textContent||'Сортировка';trigger.setAttribute('aria-label',name);
  items.forEach(item=>{item.tabIndex=-1;item.setAttribute('role','option');});
  dd.addEventListener('keydown',event=>{
    if(['ArrowDown','ArrowUp','Home','End'].includes(event.key)){event.preventDefault();if(!dd.classList.contains('open'))ddToggle(dd.id);let i=items.indexOf(document.activeElement);i=event.key==='Home'?0:event.key==='End'?items.length-1:event.key==='ArrowUp'?(i-1+items.length)%items.length:(i+1)%items.length;items[i]?.focus();}
    else if((event.key==='Enter'||event.key===' ')&&items.includes(event.target)){event.preventDefault();event.target.click();trigger.focus();}
    else if(event.key==='Escape'){event.preventDefault();closeDropdowns();trigger.focus();}
    else if(event.key==='Tab')closeDropdowns();
  });
});
document.querySelectorAll('input,textarea').forEach(el=>{
  if(el.labels?.length||el.getAttribute('aria-label'))return;
  const name=el.closest('.set-row,.port-card')?.querySelector('.set-name,.port-title')?.textContent||el.placeholder||el.id;
  el.setAttribute('aria-label',name);
});
if(document.documentElement.classList.contains('custom-frame')){
  const bar=document.querySelector('.titlebar');bar.classList.remove('pywebview-drag-region');
}
/* Главный экран: страна сервера, пинг, спидометр и ползунок подключения. */
const GAUGE_LENGTH=345.6,GAUGE_STEPS=[50,100,250,500,1000,2500];
let gaugeMax=GAUGE_STEPS[0];
function setGauge(mbps){
  const arc=document.getElementById('gaugeArc');if(!arc)return;
  const value=Math.max(0,Number(mbps)||0);
  // Шкала только растёт в течение сессии: иначе стрелка прыгала бы при каждом всплеске.
  while(value>gaugeMax&&gaugeMax<GAUGE_STEPS.at(-1))gaugeMax=GAUGE_STEPS[GAUGE_STEPS.indexOf(gaugeMax)+1];
  arc.setAttribute('stroke-dashoffset',String(GAUGE_LENGTH*(1-Math.min(value,gaugeMax)/gaugeMax)));
  document.getElementById('gaugeMax').textContent=String(gaugeMax);
}
function homeCountryName(server){
  const code=ccFor(server.remark||'');
  if(code!=='xx'&&typeof Intl.DisplayNames==='function'){
    try{const name=new Intl.DisplayNames(['ru'],{type:'region'}).of(code.toUpperCase());if(name&&name.toUpperCase()!==code.toUpperCase())return name;}catch(_){}
  }
  return stripFlagEmoji(server.remark)||'Без имени';
}
function homeRouteText(server){
  const name=stripFlagEmoji(server.remark)||'Без имени';
  if(server.is_awg)return `${name} · AmneziaWG`;
  if(ST.proto==='wg')return `${name} · WireGuard`;
  const protocol=({vless:'VLESS',vmess:'VMess',trojan:'Trojan',ss:'Shadowsocks',hysteria2:'Hysteria 2'})[server.protocol||'vless']||String(server.protocol||'').toUpperCase();
  const transport=String(server.transport||'tcp').toUpperCase();
  return `${name} · ${protocol} · ${transport}${server.reality?' · Reality':''}`;
}
function renderHomePing(){
  const chip=document.getElementById('homePing');if(!chip)return;
  const server=selectedServer();
  const live=ST.connected&&ST.tunnelPing&&ST.tunnelPing.label&&ST.tunnelPing.label!=='—'?ST.tunnelPing:null;
  const listed=server?(ST.proto==='wg'?ST.wgPings:ST.pings)[serverKey(server,ST.proto==='wg'?ST.selWgGroup:ST.selGroup,ST.proto==='wg'?ST.selWgIndex:ST.selIndex)]:null;
  const ping=live||(listed&&listed.label!=='—'?listed:null);
  chip.hidden=!ping;
  if(ping){chip.textContent=(live?'● ':'')+ping.label.replace('ms',' мс');chip.className='dash-chip '+(ping.color==='green'?'good':ping.color==='yellow'?'yellow':ping.color==='red'||ping.color==='err'?'red':'');chip.title=live?'Задержка через туннель':'Последняя проверка из списка серверов';}
}
function renderHomeDash(){
  const dash=document.querySelector('.home-dash');if(!dash)return;
  const on=ST.backendOnline&&(ST.status==='on'||ST.connected)&&ST.status!=='error';
  dash.classList.toggle('is-on',on);
  const server=selectedServer();
  document.getElementById('homeCountry').textContent=server?homeCountryName(server):'Сервер не выбран';
  document.getElementById('hcServer').textContent=server?homeRouteText(server):'Выберите сервер в списке';
  const slide=document.getElementById('connectBtn');
  slide.disabled=!ST.backendOnline||ST.status==='stopping';
  if(!on){gaugeMax=GAUGE_STEPS[0];setGauge(0);document.getElementById('stDown').textContent='0.0';document.getElementById('stUp').textContent='0.0';}
  renderHomePing();
}
// Ползунок: нажатие и клавиатура работают как кнопка, перетаскивание дальше
// 60% дорожки тоже переключает. После перетаскивания щелчок не повторяется.
(function(){
  const slide=document.getElementById('connectBtn');if(!slide)return;
  const knob=slide.querySelector('.dash-slide-knob');let drag=null;
  const reset=()=>{drag=null;slide.classList.remove('dragging');knob.style.transform='';};
  slide.addEventListener('pointerdown',e=>{if(slide.disabled||e.button!==0)return;drag={x:e.clientX,travel:slide.clientWidth-knob.offsetWidth-12,moved:false};slide.setPointerCapture(e.pointerId);});
  slide.addEventListener('pointermove',e=>{if(!drag)return;const dx=e.clientX-drag.x;if(!drag.moved&&Math.abs(dx)<6)return;drag.moved=true;slide.classList.add('dragging');
    const on=slide.classList.contains('on');knob.style.transform=`translateX(${on?Math.min(0,Math.max(-drag.travel,dx)):Math.max(0,Math.min(drag.travel,dx))}px)`;});
  slide.addEventListener('pointerup',e=>{if(!drag)return;const {moved,travel,x}=drag;const dx=e.clientX-x,on=slide.classList.contains('on');reset();if(!moved)return;
    slide.dataset.dragged='1';if((!on&&dx>travel*.6)||(on&&dx<-travel*.6))toggleConnect();});
  slide.addEventListener('pointercancel',reset);
  slide.addEventListener('click',e=>{if(slide.dataset.dragged){delete slide.dataset.dragged;e.preventDefault();e.stopImmediatePropagation();}},true);
})();
