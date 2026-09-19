function serverTransportLabel(server){
  if(!server)return 'Сервер не выбран';
  const protocol=server.is_awg?'AmneziaWG':server.protocol||'vless';
  const transport=server.transport||'tcp';
  return `${protocol.toUpperCase()}${protocol==='wg'||server.is_awg?'':' / '+transport.toUpperCase()} · Reality: ${server.reality?'да':'нет'}`;
}
function appRouteDetail(app, liveOnly=false){
  const observed=(ST.appRoutes||[]).find(row=>row.exe.toLowerCase()===app.exe.toLowerCase());
  const target=app.enabled!==false?(app.destination||'default'):'default';
  const server=target.startsWith('server:')?ST.groups.flatMap(g=>g.servers||[]).find(s=>s.ui_id===target.slice(7)):selectedServer();
  if(target.startsWith('server:')&&!server)return 'Сервер правила не найден · подключение будет заблокировано до исправления';
  const vpnProtocol=ST.proto==='wg'?(server?.is_awg?'AmneziaWG':'WireGuard'):
    server?`${(server.protocol||'vless').toUpperCase()} / ${(server.transport||'tcp').toUpperCase()}`:'Не выбран';
  let routes, source;
  if(!ST.backendOnline)return 'Статус маршрута неизвестен · нет связи с ядром';
  if(ST.connected&&observed){routes=observed.routes;source='Сейчас';}
  else if(liveOnly)return 'Нет активных соединений';
  else{
    const mode=ST.appsConfig.mode||'all', enabled=app.enabled!==false;
    const proxy=target==='direct'?false:target.startsWith('server:')?true:isNativeAwg()||mode==='all'||(mode==='whitelist'?enabled:!enabled);
    routes=[proxy?'proxy':'direct'];source=ST.connected?'По правилу · нет активных соединений':'После подключения';
  }
  const detail=routes.map(route=>{
    if(route==='direct')return 'Напрямую · протокол VPN: — · Reality: нет';
    if(route==='blocked')return 'Заблокировано · протокол VPN: — · Reality: нет';
    if(route==='unknown')return 'Маршрут не определён ядром · Reality: неизвестно';
    return `Через VPN · ${vpnProtocol} · Reality: ${server?(server.reality?'да':'нет'):'неизвестно'}`;
  }).join(' / ');
  return `${source}: ${detail}${observed&&ST.connected&&observed.networks.length?' · '+observed.networks.join('/').toUpperCase():''}`;
}
function updateRouteDetails(){
  document.querySelectorAll('[data-route-exe]').forEach(el=>{
    const app=(ST.appsConfig.apps||[]).find(a=>a.exe.toLowerCase()===el.dataset.routeExe.toLowerCase());
    if(app)el.textContent=appRouteDetail(app);
  });
  const container=document.getElementById('observedAppList');if(!container)return;
  const configured=new Set((ST.appsConfig.apps||[]).map(a=>a.exe.toLowerCase()));
  const rows=ST.connected&&ST.backendOnline?(ST.appRoutes||[]).filter(a=>!configured.has(a.exe.toLowerCase())):[];
  document.getElementById('observedAppCount').textContent=rows.length;
  const html=rows.length?rows.map(a=>`<div class="observed-app glass"><strong>${esc(a.exe)}</strong><small>${esc(appRouteDetail(a,true))}</small></div>`).join(''):
    '<div class="page-sub">Здесь автоматически появятся приложения, чей трафик ядро смог связать с процессом.</div>';
  if(container.innerHTML!==html)container.innerHTML=html;
}
