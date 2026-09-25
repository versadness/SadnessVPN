(function(){
  const page=document.getElementById('page-routing'),nav=page.querySelector('.route-tabs');
  const kinds={process:['Программа','Имя приложения .exe, например Telegram.exe'],geosite:['GeoSite','Категория из локальной базы GeoSite'],suffix:['По суффиксу','Домен и поддомены, например example.com'],keyword:['Слово в домене','Часть имени домена, например example'],geoip:['GeoIP','Код страны или категория IP'],cidr:['IP-CIDR','IP или сеть, например 192.0.2.0/24']};
  const kindIcons={process:'💻',geosite:'🗂',suffix:'🌐',keyword:'🔤',geoip:'📍',cidr:'🧭'};
  function el(tag,text,cls){const e=document.createElement(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;}
  // Отдельной вкладки «Мои правила» больше нет: правила любого типа живут в
  // одном списке вместе с приложениями, под общим поиском и счётчиком.
  const presetPanel=el('section',null,'route-panel');presetPanel.id='routePresets';
  const list=el('div',null,'custom-rule-list');
  const scroll=page.querySelector('#routeApps .scroll');
  scroll.insertBefore(list,document.getElementById('ruleList').nextSibling);
  page.append(presetPanel);presetPanel.hidden=true;
  const presetsTab=el('button','Готовые наборы');presetsTab.type='button';presetsTab.dataset.panel='routePresets';nav.append(presetsTab);
  const oldPreset=page.querySelector('.preset-card');if(oldPreset)presetPanel.append(oldPreset);
  const search=document.getElementById('ruleSearch');
  const addButton=page.querySelector('.rules-bar .btn-primary');
  const modal=el('dialog',null,'routing-editor');modal.setAttribute('aria-labelledby','routingEditorTitle');
  const title=el('h2','Новое правило');title.id='routingEditorTitle';const form=el('form');form.method='dialog';
  const typeGrid=el('div',null,'rule-type-grid'),hint=el('p',null,'set-desc');
  const value=el('input');value.className='inp';value.required=true;value.maxLength=253;value.id='routeValue';
  // «Список» раньше ничего не объясняла и раскрывала перечень процессов прямо
  // в форме. Теперь это явная кнопка, открывающая общий дочерний диалог.
  const picker=el('button','Выбрать из запущенных','btn btn-ghost route-pick-btn');picker.type='button';
  const pickerHint=el('p',null,'set-desc route-pick-hint');
  const picked=el('p',null,'set-desc route-picked');picked.hidden=true;
  const name=el('input');name.className='inp';name.maxLength=256;name.id='routeName';name.placeholder='Заполнится автоматически';
  const action=el('select');action.className='inp';action.id='routeAction';for(const [v,t]of [['proxy','Через VPN'],['direct','Без VPN']]){const o=el('option',t);o.value=v;action.append(o);}
  const server=el('select');server.className='inp';server.id='routeServer';
  const error=el('p',null,'route-error');error.setAttribute('role','alert');
  const valueError=el('p',null,'route-error');valueError.id='routeValueError';valueError.setAttribute('aria-live','polite');value.setAttribute('aria-describedby',valueError.id);
  const serverError=el('p',null,'route-error');serverError.id='routeServerError';serverError.setAttribute('aria-live','polite');server.setAttribute('aria-describedby',serverError.id);
  const cancel=el('button','Отмена','btn btn-ghost');cancel.type='button';const save=el('button','Сохранить','btn btn-primary');save.type='submit';
  const footer=el('div',null,'modal-actions');footer.append(cancel,save);
  const label=(text,id)=>{const l=el('label',text,'form-label');l.htmlFor=id;return l;};
  // Структура вместо сплошного потока: каждая группа — отдельный flex-блок с
  // предсказуемым gap, а прокрутка живёт только у тела формы. Кнопки действий
  // остаются снаружи прокрутки и достижимы на любом размере окна.
  const group=(...nodes)=>{const g=el('div',null,'form-group');g.append(...nodes);return g;};
  const valueRow=el('div',null,'route-value-row');valueRow.append(value,picker);
  const body=el('div',null,'route-form-body');
  body.append(
    group(typeGrid,hint),
    group(label('Значение','routeValue'),valueRow,pickerHint,picked,valueError),
    group(label('Название · необязательно','routeName'),name),
    group(label('Действие','routeAction'),action),
    group(label('Через сервер','routeServer'),server,serverError),
  );
  form.className='route-form';
  form.append(body,error,footer);modal.append(title,form);document.body.append(modal);
  let kind='process',editing=null,initial='',busy=false,dragging=null,validationTimer=null,validationId=0,validated='';
  const snapshot=()=>JSON.stringify([kind,value.value,name.value,action.value,server.value]);
  const validationKey=()=>JSON.stringify([kind,value.value,action.value,server.value]);
  function validity(){save.disabled=busy||!value.value.trim()||validated!==validationKey();server.disabled=busy||action.value==='direct';}
  function validate(){
    const id=++validationId,key=validationKey();validated='';clearTimeout(validationTimer);valueError.textContent='';serverError.textContent='';value.removeAttribute('aria-invalid');server.removeAttribute('aria-invalid');validity();
    if(!value.value.trim())return;
    validationTimer=setTimeout(async()=>{try{const response=await api('/api/routing/validate',{kind,value:value.value,destination:action.value==='direct'?'direct':server.value});if(id!==validationId)return;if(response.ok){validated=key;}else{const target=response.field==='server'?serverError:valueError;target.textContent=response.error||'Некорректное значение';(response.field==='server'?server:value).setAttribute('aria-invalid','true');}}catch(_){if(id===validationId)valueError.textContent='Не удалось проверить правило. Измените значение, чтобы повторить.';}if(id===validationId)validity();},180);
  }
  const PICKABLE={process:'Выбрать из запущенных',geosite:'Выбрать из списка',geoip:'Выбрать из списка'};
  function pickKind(k){
    kind=k;hint.textContent=kinds[k][1];value.placeholder=kinds[k][1];
    picker.hidden=!(k in PICKABLE);picker.textContent=PICKABLE[k]||'Выбрать из списка';
    pickerHint.textContent=k==='process'
      ?'Выбирайте процесс самой игры, а не только лаунчера. Например, после запуска игры обновите список и найдите её исполняемый файл.'
      :'';
    pickerHint.hidden=k!=='process';
    picked.hidden=true;picked.textContent='';
    for(const b of typeGrid.children)b.setAttribute('aria-pressed',String(b.dataset.kind===k));
    validate();
  }
  for(const [k,[text]]of Object.entries(kinds)){const b=el('button',text);b.type='button';b.dataset.kind=k;b.onclick=()=>pickKind(k);typeGrid.append(b);}
  function open(rule=null){
    editing=rule?.id||null;title.textContent=rule?'Изменить правило':'Новое правило';error.textContent='';value.value=rule?.value||'';name.value=rule?.name||'';action.value=rule?.destination==='direct'?'direct':'proxy';
    server.replaceChildren();const automatic=el('option','Авто — сервер с главного экрана');automatic.value='proxy';server.append(automatic);
    for(const group of ST.groups){const og=el('optgroup');og.label=group.name;for(const s of group.servers||[]){if(!s.ui_id||['wg','wireguard','amneziawg','awg'].includes((s.protocol||'').toLowerCase()))continue;const ping=ST.pings?.[s.ui_id];const o=el('option',`${s.remark} · ${(s.protocol||'vless').toUpperCase()} / ${s.transport||s.type||'tcp'} · Reality: ${s.reality||s.security==='reality'?'да':'нет'} · ${ping?.label||'пинг не проверен'}`);o.value='server:'+s.ui_id;og.append(o);}server.append(og);}
    const target=rule?.destination||'proxy';if(target.startsWith('server:')&&![...server.options].some(o=>o.value===target)){const o=el('option','Сервер недоступен — выберите замену');o.value=target;server.append(o);}server.value=target==='direct'?'proxy':target;pickKind(rule?.kind||'process');initial=snapshot();modal.showModal();value.focus();
  }
  function close(){if(busy)return;if(snapshot()!==initial&&!confirm('Закрыть без сохранения изменений?'))return;modal.close();}
  cancel.onclick=close;modal.addEventListener('cancel',e=>{e.preventDefault();close();});
  value.addEventListener('input',validate);action.onchange=validate;server.onchange=validate;
  picker.onclick=async()=>{
    const requestedKind=kind;
    const choice=await window.openProcessPicker({
      mode:kind==='process'?'process':'category',
      kind,
      anchor:picker,
      current:value.value.trim(),
    });
    if(!choice||requestedKind!==kind)return;
    // В правило попадает только точное имя исполняемого файла: ни PID,
    // ни полный путь, ни командная строка здесь не участвуют.
    value.value=choice.value;
    if(kind==='process'){
      picked.textContent=`Выбрано: ${choice.name} · ${choice.value}`;
      picked.hidden=false;
      if(!name.value.trim()&&choice.name!==choice.value)name.value=choice.name;
    }
    validate();
    value.focus();
  };
  const current=()=>ST.appsConfig.rules||[];
  let conflictKey='',conflicts={};
  function showConflicts(){
    const names=new Map(current().map(r=>[r.id,r.name||r.value]));
    for(const row of list.children){
      row.querySelector('.rule-conflicts')?.remove();
      const matches=conflicts[row.dataset.ruleId];if(!matches?.length)continue;
      const note=el('p',matches.map(m=>`${m.relation==='covered'?'Перекрыто предыдущим правилом':'Частичное пересечение'} «${names.get(m.id)||'правило'}»${m.different_destination?' — другой выход':''}.`).join(' '),'route-error rule-conflicts');
      row.append(note);
    }
  }
  function refreshConflicts(){
    const key=JSON.stringify(current());if(key===conflictKey){showConflicts();return;}
    conflictKey=key;conflicts={};
    api('/api/routing/conflicts',{rules:current()}).then(result=>{if(key!==conflictKey)return;if(result.ok){conflicts=result.conflicts||{};showConflicts();}}).catch(()=>{if(key===conflictKey)conflictKey='';});
  }
  const observations=new Map();
  window.updateAdvancedRuleObservations=items=>{for(const item of items)observations.set(item.id,item);if(observations.size>1000)observations.clear();for(const row of list.children){const seen=observations.get(row.dataset.ruleId);const node=row.querySelector('.rule-observation');if(node&&seen)node.textContent=`Последнее наблюдение: ${seen.process||'процесс не сообщён'} · ${seen.exit} · ${new Date(seen.observed_at*1000).toLocaleTimeString()}`;}};
  async function persist(rules){const result=await api('/api/routing/rules',{rules});if(!result.ok)throw Error(result.error||'Не удалось сохранить правила');ST.appsConfig.rules=result.rules||rules;render();}
  form.onsubmit=async event=>{event.preventDefault();if(busy||!value.value.trim()||validated!==validationKey())return;busy=true;validity();error.textContent='';try{const rule={id:editing||crypto.randomUUID(),kind,value:value.value,name:name.value,destination:action.value==='direct'?'direct':server.value,enabled:editing?current().find(r=>r.id===editing)?.enabled!==false:true};const rules=current().slice();const index=rules.findIndex(r=>r.id===editing);if(index<0)rules.push(rule);else rules[index]=rule;await persist(rules);modal.close();}catch(e){error.textContent=e.message;}finally{busy=false;validity();}};
  // Порядок правил виден в интерфейсе: первое совпавшее и решает исход,
  // а до пользовательских правил всегда идут системные исключения.
  function renderPriority(){
    const mode=ST.appsConfig.mode||'all';
    const node=document.getElementById('rulePriority');if(!node)return;
    const fallback=mode==='whitelist'
      ?'Напрямую — через VPN идут только выбранные приложения и правила'
      :'Через VPN — напрямую идёт только то, что выбрано явно';
    node.innerHTML=[
      ['Проверяются сверху вниз','Срабатывает первое подходящее правило, остальные не проверяются'],
      ['Перед правилами','Системные исключения: localhost и локальные сети всегда идут напрямую'],
      ['Маршрут по умолчанию',fallback],
      ['Изменения','Применяются при следующем подключении: правки доступны только при отключённом VPN'],
    ].map(([k,v])=>`<div class="gf-row"><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('');
  }
  function render(){
    list.replaceChildren();const query=(search?.value||'').trim().toLowerCase();
    renderPriority();
    const order=new Map(current().map((r,i)=>[r.id,i+1]));
    for(const rule of current().filter(r=>[r.name,r.value,r.kind].join(' ').toLowerCase().includes(query))){
      const row=el('article',null,'custom-rule glass');row.draggable=!query&&ST.status==='off';
      const head=el('div',null,'custom-rule-head');
      head.append(el('span',String(order.get(rule.id)),'rule-order'));
      head.append(el('span',kindIcons[rule.kind]||'🌐','rule-ico'));
      const meta=el('div',null,'rule-meta');
      meta.append(el('div',rule.name||rule.value,'rule-name'),el('div',`${kinds[rule.kind]?.[0]||rule.kind} · ${rule.value}`,'rule-type'));
      head.append(meta);
      // Восстановление на бэкенде уже переводит потерянный сервер на основной
      // VPN. Эта ветка остаётся на случай, когда запись на диск не прошла.
      const missing=rule.destination.startsWith('server:')&&!ST.groups.some(g=>(g.servers||[]).some(s=>'server:'+s.ui_id===rule.destination));
      let target=rule.destination==='direct'?'Напрямую':rule.destination==='proxy'?'Основной маршрут':'Сервер недоступен';
      if(missing)target='Прежний сервер исчез из подписки · «Исправить» вернёт правило на основной VPN';
      if(rule.destination.startsWith('server:')){for(const g of ST.groups){const s=g.servers.find(s=>'server:'+s.ui_id===rule.destination);if(s){target=`${g.name} · ${s.remark} · ${(s.protocol||'vless').toUpperCase()} / ${s.transport||s.type||'tcp'} · Reality: ${s.reality||s.security==='reality'?'да':'нет'}`;break;}}}
      head.append(el('span',rule.enabled===false?'Выключено':rule.destination==='direct'?'Напрямую':'Через VPN','rule-badge '+(rule.enabled===false?'off':rule.destination==='direct'?'direct':'')));
      row.append(head,el('p',target,'set-desc'));
      row.dataset.ruleId=rule.id;const seen=observations.get(rule.id);row.append(el('p',seen?`Последнее наблюдение: ${seen.process||'процесс не сообщён'} · ${seen.exit} · ${new Date(seen.observed_at*1000).toLocaleTimeString()}`:'Срабатываний пока не наблюдалось','set-desc rule-observation'));
      const actions=el('div',null,'rule-actions');for(const [text,fn]of [...(missing?[['Исправить',()=>persist(current().map(r=>r.id===rule.id?{...r,destination:'proxy'}:r))]]:[]),[rule.enabled===false?'Включить':'Выключить',()=>persist(current().map(r=>r.id===rule.id?{...r,enabled:r.enabled===false}:r))],['Изменить',()=>open(rule)],['Дублировать',()=>{const rules=current().slice(),index=rules.findIndex(r=>r.id===rule.id);rules.splice(index+1,0,{...rule,id:crypto.randomUUID(),name:(rule.name||rule.value)+' (копия)'});return persist(rules);}],['Удалить',()=>{if(confirm('Удалить правило «'+(rule.name||rule.value)+'»?'))return persist(current().filter(r=>r.id!==rule.id));}]]){const b=el('button',text,'btn btn-ghost');b.disabled=ST.status!=='off';b.onclick=async()=>{try{await fn();}catch(e){toast(e.message,'err');}};actions.append(b);}
      row.append(actions);
      row.ondragstart=e=>{dragging=rule.id;e.dataTransfer.setData('text/plain',rule.id);};row.ondragover=e=>{if(row.draggable)e.preventDefault();};
      row.ondrop=async e=>{e.preventDefault();if(!row.draggable||!dragging||dragging===rule.id)return;const reordered=current().slice(),index=reordered.findIndex(r=>r.id===dragging);if(index<0)return;const moved=reordered.splice(index,1)[0];reordered.splice(reordered.findIndex(r=>r.id===rule.id),0,moved);try{await persist(reordered);}catch(err){toast(err.message,'err');}dragging=null;};
      list.append(row);
    }
    // Счётчик и пустое состояние общие для приложений и остальных правил.
    const apps=(ST.appsConfig.apps||[]).length,rules=current().length;
    const counter=document.getElementById('rulesCount');if(counter)counter.textContent=apps+rules;
    const empty=document.getElementById('ruleEmpty');if(empty)empty.classList.toggle('hidden',apps+rules>0);
    if(addButton)addButton.disabled=ST.status!=='off';
  }
  const renderWithoutConflicts=render;render=function(){renderWithoutConflicts();refreshConflicts();};
  // Кнопка «Новое правило» в шапке списка открывает этот же диалог.
  window.promptRule=()=>open();
  const original=renderRules;renderRules=function(){original();render();};
  window.openAdvancedRule=open;
  // Крупные тематические сборники. destination:'direct' — набор уводит трафик
  // мимо VPN, всё остальное идёт через выбранный на главном экране сервер.
  const presets=[
    {title:'Мессенджеры и соцсети',note:'Переписка и соцсети через VPN',destination:'proxy',items:[
      ['process','Telegram.exe'],['process','Discord.exe'],['process','WhatsApp.exe'],['process','Viber.exe'],['process','slack.exe'],
      ['suffix','telegram.org'],['suffix','t.me'],['suffix','tdesktop.com'],['suffix','discord.com'],['suffix','discordapp.com'],['suffix','discord.gg'],
      ['suffix','whatsapp.com'],['suffix','instagram.com'],['suffix','cdninstagram.com'],['suffix','facebook.com'],['suffix','fbcdn.net'],
      ['suffix','twitter.com'],['suffix','x.com'],['suffix','twimg.com'],['suffix','threads.net'],['suffix','signal.org']]},
    {title:'Видео и стриминг',note:'YouTube, Netflix, Twitch и TikTok',destination:'proxy',items:[
      ['suffix','youtube.com'],['suffix','youtu.be'],['suffix','googlevideo.com'],['suffix','ytimg.com'],['suffix','ggpht.com'],
      ['suffix','netflix.com'],['suffix','nflxvideo.net'],['suffix','nflximg.net'],['suffix','twitch.tv'],['suffix','ttvnw.net'],['suffix','jtvnw.net'],
      ['suffix','vimeo.com'],['suffix','tiktok.com'],['suffix','tiktokcdn.com'],['suffix','ibytedtos.com'],['suffix','disneyplus.com'],['suffix','hbomax.com']]},
    {title:'ИИ-сервисы',note:'Чат-боты и нейросети',destination:'proxy',items:[
      ['suffix','chatgpt.com'],['suffix','openai.com'],['suffix','oaistatic.com'],['suffix','oaiusercontent.com'],
      ['suffix','claude.ai'],['suffix','anthropic.com'],['suffix','gemini.google.com'],['suffix','bard.google.com'],
      ['suffix','perplexity.ai'],['suffix','copilot.microsoft.com'],['suffix','huggingface.co'],['suffix','midjourney.com'],
      ['suffix','stability.ai'],['suffix','mistral.ai'],['suffix','deepseek.com']]},
    {title:'Игры и лаунчеры',note:'Магазины, лаунчеры и игровые сервисы',destination:'proxy',items:[
      ['process','steam.exe'],['process','steamwebhelper.exe'],['process','EpicGamesLauncher.exe'],['process','Battle.net.exe'],
      ['process','RiotClientServices.exe'],['process','GalaxyClient.exe'],['process','Origin.exe'],['process','EADesktop.exe'],['process','UbisoftConnect.exe'],
      ['suffix','steampowered.com'],['suffix','steamcommunity.com'],['suffix','steamstatic.com'],['suffix','epicgames.com'],
      ['suffix','battle.net'],['suffix','riotgames.com'],['suffix','gog.com'],['suffix','ea.com'],['suffix','ubisoft.com']]},
    {title:'Музыка',note:'Стриминг и музыкальные сервисы',destination:'proxy',items:[
      ['process','Spotify.exe'],['suffix','spotify.com'],['suffix','scdn.co'],['suffix','spotifycdn.com'],
      ['suffix','deezer.com'],['suffix','soundcloud.com'],['suffix','sndcdn.com'],['suffix','music.apple.com'],
      ['suffix','tidal.com'],['suffix','last.fm'],['suffix','bandcamp.com'],['suffix','bcbits.com']]},
    {title:'Разработка',note:'Репозитории, пакеты и документация',destination:'proxy',items:[
      ['suffix','github.com'],['suffix','githubusercontent.com'],['suffix','githubassets.com'],['suffix','ghcr.io'],
      ['suffix','gitlab.com'],['suffix','bitbucket.org'],['suffix','npmjs.org'],['suffix','npmjs.com'],['suffix','yarnpkg.com'],
      ['suffix','pypi.org'],['suffix','pythonhosted.org'],['suffix','crates.io'],['suffix','docker.com'],['suffix','docker.io'],
      ['suffix','stackoverflow.com'],['suffix','jetbrains.com'],['suffix','visualstudio.com'],['suffix','gradle.org'],['suffix','maven.org']]},
    {title:'Российские сервисы напрямую',note:'Идут мимо VPN: банки, госуслуги, магазины',destination:'direct',items:[
      ['suffix','ru'],['suffix','xn--p1ai','рф'],['suffix','su'],
      ['suffix','yandex.ru'],['suffix','yandex.net'],['suffix','mail.ru'],['suffix','vk.com'],['suffix','vk.ru'],['suffix','userapi.com'],
      ['suffix','ok.ru'],['suffix','sberbank.ru'],['suffix','sber.ru'],['suffix','tinkoff.ru'],['suffix','alfabank.ru'],['suffix','vtb.ru'],
      ['suffix','gosuslugi.ru'],['suffix','nalog.ru'],['suffix','avito.ru'],['suffix','wildberries.ru'],['suffix','wbbasket.ru'],
      ['suffix','ozon.ru'],['suffix','rutube.ru'],['suffix','kinopoisk.ru'],['suffix','2gis.ru'],['suffix','dns-shop.ru']]},
  ];
  for(const preset of presets){
    const card=el('article',null,'preset-set glass');
    const head=el('div',null,'preset-set-head');
    const info=el('div',null,'preset-set-info');
    info.append(el('strong',preset.title),el('p',preset.note,'set-desc'));
    const count=el('span',preset.items.length+' правил','preset-set-count');
    head.append(info,count);
    const details=el('details',null,'preset-set-details');
    details.append(el('summary','Показать состав'),el('p',preset.items.map(x=>x[2]||x[1]).join(', '),'set-desc'));
    const button=el('button','Добавить набор','btn btn-primary');button.type='button';
    button.onclick=async()=>{
      if(!confirm(`Добавить набор «${preset.title}» — ${preset.items.length} правил?`))return;
      const rules=current().slice();let added=0;
      // Значения набора уже в том виде, в котором их хранит бэкенд (домены — в
      // punycode), иначе повторное добавление не распознавало дубликаты.
      for(const [kind,value,label]of preset.items){
        if(rules.some(r=>r.kind===kind&&r.value.toLowerCase()===value.toLowerCase()))continue;
        rules.push({id:crypto.randomUUID(),kind,value,name:label||value,destination:preset.destination,enabled:true});added++;
      }
      if(!added){toast('Все правила набора уже добавлены','ok');return;}
      try{await persist(rules);toast(`Добавлено правил: ${added}`,'ok');}catch(e){toast(e.message,'err');}
    };
    card.append(head,details,button);presetPanel.append(card);
  }
  render();
})();
