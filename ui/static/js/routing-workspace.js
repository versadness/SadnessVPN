// Group routing controls by purpose; selectors are built with DOM APIs so
// subscription labels are always text, never executable markup.
(function(){
  const page=document.getElementById('page-routing');
  const apps=document.createElement('section');apps.className='route-panel';apps.id='routeApps';
  // «Общий маршрут» больше не отдельная вкладка: выбор режима стоит прямо над
  // списком правил, потому что это одно решение, а не два разных экрана.
  for(const selector of ['.awg-limit','.mode-cards','.rules-bar','.control-row','.scroll']){
    const element=page.querySelector(selector);if(element)apps.append(element);
  }
  const nav=document.createElement('nav');nav.className='route-tabs';nav.setAttribute('aria-label','Разделы маршрутизации');
  const appsTab=document.createElement('button');appsTab.type='button';appsTab.textContent='Приложения и серверы';
  appsTab.dataset.panel='routeApps';nav.append(appsTab);
  // Обработчик делегирован и живёт здесь: этот файл загружается раньше
  // routing-editor.js, который добавляет свою вкладку тем же data-panel.
  nav.addEventListener('click',event=>{
    const button=event.target.closest('button');if(!button||!button.dataset.panel)return;
    for(const panel of page.querySelectorAll(':scope > .route-panel'))panel.hidden=panel.id!==button.dataset.panel;
    for(const child of nav.children)child.setAttribute('aria-pressed',String(child===button));
  });
  const intro=document.createElement('div');intro.className='route-intro glass';
  const title=document.createElement('strong');title.textContent='Каждому приложению — свой маршрут';
  const note=document.createElement('p');note.textContent='Выберите режим, затем задайте отдельные правила для приложений, доменов и адресов. Разные серверы работают одновременно в режиме TUN и в обычном WireGuard; к AmneziaWG правила не применяются. Меняйте назначения при отключённом VPN.';
  intro.append(title,note);apps.prepend(intro);
  page.append(nav,apps);appsTab.click();
  const original=renderRules;
  renderRules=function(){
    original();
    page.querySelectorAll('.rule-row').forEach(row=>{
      const exe=row.querySelector('[data-route-exe]')?.dataset.routeExe;
      const app=ST.appsConfig.apps.find(a=>a.exe===exe);if(!app)return;
      const label=document.createElement('label');label.className='route-destination';
      const text=document.createElement('span');text.textContent='Назначение';label.append(text);
      const select=document.createElement('select');select.className='inp';select.setAttribute('aria-label','Маршрут для '+(app.name||exe));
      const option=(parent,value,text)=>{const o=document.createElement('option');o.value=value;o.textContent=text;parent.append(o);};
      option(select,'default','Основной маршрут');option(select,'direct','Напрямую · без VPN');
      for(const group of ST.groups){
        const optgroup=document.createElement('optgroup');optgroup.label=group.name;
        for(const server of group.servers||[])if(server.ui_id)option(optgroup,'server:'+server.ui_id,server.remark+' · '+(server.protocol||'vless').toUpperCase());
        select.append(optgroup);
      }
      const target=app.destination||'default';
      if(![...select.options].some(o=>o.value===target))option(select,target,'⚠ Сервер больше не найден');
      select.value=target;select.disabled=!ST.backendOnline||ST.status!=='off'||ST.proto==='wg';
      select.addEventListener('change',async()=>{
        select.disabled=true;
        try{const result=await api('/api/apps/destination',{exe,destination:select.value});
          if(!result.ok){select.value=target;toast(result.error||'Не удалось сохранить маршрут','err');}
          else{app.destination=select.value;renderRules();}
        }finally{select.disabled=!ST.backendOnline||ST.status!=='off'||ST.proto==='wg';}
      });
      label.append(select);row.querySelector('.rule-meta').append(label);
      if(target!=='default'&&app.enabled!==false){const badge=row.querySelector('.rule-badge');badge.textContent=target==='direct'?'Напрямую':'Свой сервер';}
    });
  };
})();
