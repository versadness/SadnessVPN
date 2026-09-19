(function(){
  const page=document.getElementById('page-routing'),nav=page.querySelector('.route-tabs');
  const kinds={process:['Программа','Имя приложения .exe, например Telegram.exe'],geosite:['GeoSite','Категория из локальной базы GeoSite'],suffix:['По суффиксу','Домен и поддомены, например example.com'],keyword:['Слово в домене','Часть имени домена, например example'],geoip:['GeoIP','Код страны или категория IP'],cidr:['IP-CIDR','IP или сеть, например 192.0.2.0/24']};
  function el(tag,text,cls){const e=document.createElement(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;}
  const rulesPanel=el('section',null,'route-panel'),presetPanel=el('section',null,'route-panel');rulesPanel.id='routeCustom';presetPanel.id='routePresets';
  const search=el('input');search.className='inp';search.placeholder='Поиск по правилам';search.setAttribute('aria-label',search.placeholder);
  const add=el('button','Новое правило','btn btn-primary');add.type='button';
  const list=el('div',null,'custom-rule-list');rulesPanel.append(search,add,list);page.append(rulesPanel,presetPanel);
  for(const [id,label] of [['routeCustom','Мои правила'],['routePresets','Готовые наборы']]){const button=el('button',label);button.type='button';button.dataset.panel=id;nav.append(button);}
  nav.addEventListener('click',event=>{const button=event.target.closest('button');if(!button)return;const id=button.dataset.panel||([...nav.children].indexOf(button)===0?'routeApps':'routeOverview');for(const panel of page.querySelectorAll(':scope > .route-panel'))panel.hidden=panel.id!==id;for(const b of nav.children)b.setAttribute('aria-pressed',String(b===button));});
  rulesPanel.hidden=true;presetPanel.hidden=true;
  const oldPreset=page.querySelector('.preset-card');if(oldPreset)presetPanel.append(oldPreset);
  const modal=el('dialog',null,'routing-editor');modal.setAttribute('aria-labelledby','routingEditorTitle');
  const title=el('h2','Новое правило');title.id='routingEditorTitle';const form=el('form');form.method='dialog';
  const typeGrid=el('div',null,'rule-type-grid'),hint=el('p',null,'set-desc');
  const value=el('input');value.className='inp';value.required=true;value.maxLength=253;value.id='routeValue';
  const picker=el('button','Список','btn btn-ghost');picker.type='button';const choices=el('div',null,'route-choice-list');choices.hidden=true;
  const name=el('input');name.className='inp';name.maxLength=256;name.id='routeName';name.placeholder='Заполнится автоматически';
  const action=el('select');action.className='inp';action.id='routeAction';for(const [v,t]of [['proxy','Через VPN'],['direct','Без VPN']]){const o=el('option',t);o.value=v;action.append(o);}
  const server=el('select');server.className='inp';server.id='routeServer';
  const error=el('p',null,'route-error');error.setAttribute('role','alert');
  const valueError=el('p',null,'route-error');valueError.id='routeValueError';valueError.setAttribute('aria-live','polite');value.setAttribute('aria-describedby',valueError.id);
  const serverError=el('p',null,'route-error');serverError.id='routeServerError';serverError.setAttribute('aria-live','polite');server.setAttribute('aria-describedby',serverError.id);
  const cancel=el('button','Отмена','btn btn-ghost');cancel.type='button';const save=el('button','Сохранить','btn btn-primary');save.type='submit';
  const footer=el('div',null,'modal-actions');footer.append(cancel,save);
  const label=(text,id)=>{const l=el('label',text,'form-label');l.htmlFor=id;return l;};
  form.append(typeGrid,hint,label('Значение','routeValue'),value,picker,choices,label('Название · необязательно','routeName'),name,label('Действие','routeAction'),action,label('Через сервер','routeServer'),server,error,footer);modal.append(title,form);document.body.append(modal);
  value.after(valueError);server.after(serverError);
  let kind='process',editing=null,initial='',busy=false,dragging=null,validationTimer=null,validationId=0,validated='',requiresSeparateServer=false;
  const snapshot=()=>JSON.stringify([kind,value.value,name.value,action.value,server.value]);
  const validationKey=()=>JSON.stringify([kind,value.value,action.value,server.value]);
  function validity(){save.disabled=busy||!value.value.trim()||validated!==validationKey();server.disabled=busy||action.value==='direct';}
  function validate(){
    const id=++validationId,key=validationKey();validated='';clearTimeout(validationTimer);valueError.textContent='';serverError.textContent='';value.removeAttribute('aria-invalid');server.removeAttribute('aria-invalid');validity();
    if(requiresSeparateServer&&(action.value!=='proxy'||!server.value.startsWith('server:'))){serverError.textContent='Для этого набора выберите отдельный сервер, разрешающий торрент-трафик.';server.setAttribute('aria-invalid','true');return;}
    if(!value.value.trim())return;
    validationTimer=setTimeout(async()=>{try{const response=await api('/api/routing/validate',{kind,value:value.value,destination:action.value==='direct'?'direct':server.value});if(id!==validationId)return;if(response.ok){validated=key;}else{const target=response.field==='server'?serverError:valueError;target.textContent=response.error||'Некорректное значение';(response.field==='server'?server:value).setAttribute('aria-invalid','true');}}catch(_){if(id===validationId)valueError.textContent='Не удалось проверить правило. Измените значение, чтобы повторить.';}if(id===validationId)validity();},180);
  }
  function pickKind(k){kind=k;hint.textContent=kinds[k][1];value.placeholder=kinds[k][1];picker.hidden=!['process','geosite','geoip'].includes(k);choices.hidden=true;for(const b of typeGrid.children)b.setAttribute('aria-pressed',String(b.dataset.kind===k));validate();}
  for(const [k,[text]]of Object.entries(kinds)){const b=el('button',text);b.type='button';b.dataset.kind=k;b.onclick=()=>pickKind(k);typeGrid.append(b);}
  function open(rule=null){
    requiresSeparateServer=false;
    editing=rule?.id||null;title.textContent=rule?'Изменить правило':'Новое правило';error.textContent='';value.value=rule?.value||'';name.value=rule?.name||'';action.value=rule?.destination==='direct'?'direct':'proxy';
    server.replaceChildren();const automatic=el('option','Авто — сервер с главного экрана');automatic.value='proxy';server.append(automatic);
    for(const group of ST.groups){const og=el('optgroup');og.label=group.name;for(const s of group.servers||[]){if(!s.ui_id||['wg','wireguard','amneziawg','awg'].includes((s.protocol||'').toLowerCase()))continue;const ping=ST.pings?.[s.ui_id];const o=el('option',`${s.remark} · ${s.country||'страна не указана'} · ${(s.protocol||'vless').toUpperCase()} / ${s.transport||s.type||'tcp'} · Reality: ${s.reality||s.security==='reality'?'да':'нет'} · ${ping?.label||'пинг не проверен'}`);o.value='server:'+s.ui_id;og.append(o);}server.append(og);}
    const target=rule?.destination||'proxy';if(target.startsWith('server:')&&![...server.options].some(o=>o.value===target)){const o=el('option','Сервер недоступен — выберите замену');o.value=target;server.append(o);}server.value=target==='direct'?'proxy':target;pickKind(rule?.kind||'process');initial=snapshot();modal.showModal();value.focus();
  }
  function close(){if(busy)return;if(snapshot()!==initial&&!confirm('Закрыть без сохранения изменений?'))return;modal.close();}
  cancel.onclick=close;modal.addEventListener('cancel',e=>{e.preventDefault();close();});
  value.addEventListener('input',validate);action.onchange=validate;server.onchange=validate;
  picker.onclick=async()=>{
    const requestedKind=kind;choices.replaceChildren();choices.hidden=false;const filter=el('input');filter.className='inp';filter.placeholder='Поиск в списке';const results=el('div');choices.append(filter,results);
    try{
      const endpoint=kind==='process'?'/api/apps/catalog':'/api/routing/categories?kind='+kind;
      const response=await fetch(endpoint);const data=await response.json();if(requestedKind!==kind)return;if(!response.ok)throw Error(data.error||'Список недоступен');
      const values=kind==='process'?(data.apps||[]).map(a=>({value:a.exe,name:a.name,icon:true})):(data.items||(data.categories||[]).map(v=>({value:v,name:v})));
      const render=()=>{results.replaceChildren();const matches=values.filter(v=>(v.name+' '+v.value).toLowerCase().includes(filter.value.toLowerCase()));for(const item of matches.slice(0,150)){
        const b=el('button',null,'btn btn-ghost');b.type='button';
        if(item.icon){const icon=el('img');icon.width=24;icon.height=24;icon.alt='';icon.loading='lazy';icon.src='/api/apps/icon?exe='+encodeURIComponent(item.value);icon.onerror=()=>icon.remove();b.append(icon);}
        b.append(el('span',item.name===item.value?item.value:item.name+' · '+item.value));b.onclick=()=>{value.value=item.value;choices.hidden=true;validate();};results.append(b);
      }if(!matches.length)results.append(el('p','Ничего не найдено','set-desc'));else if(matches.length>150)results.append(el('p','Показаны первые 150. Уточните поиск.','set-desc'));};
      filter.oninput=render;render();
    }catch(e){choices.append(el('p',e.message));}
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
  function render(){list.replaceChildren();const query=search.value.trim().toLowerCase();for(const rule of current().filter(r=>[r.name,r.value,r.kind].join(' ').toLowerCase().includes(query))){const row=el('article',null,'custom-rule glass');row.draggable=!query&&ST.status==='off';const header=el('strong',rule.name);const meta=el('p',`${kinds[rule.kind]?.[0]||rule.kind} · ${rule.value}`,'set-desc');let target=rule.destination==='direct'?'Напрямую':rule.destination==='proxy'?'Основной сервер':'Сервер недоступен';if(rule.destination.startsWith('server:')){for(const g of ST.groups){const s=g.servers.find(s=>'server:'+s.ui_id===rule.destination);if(s){target=`${g.name} · ${s.remark} · ${(s.protocol||'vless').toUpperCase()} / ${s.transport||s.type||'tcp'} · Reality: ${s.reality||s.security==='reality'?'да':'нет'}`;break;}}}row.append(header,meta,el('p',target,'set-desc'));
    row.dataset.ruleId=rule.id;const seen=observations.get(rule.id);row.append(el('p',seen?`Последнее наблюдение: ${seen.process||'процесс не сообщён'} · ${seen.exit} · ${new Date(seen.observed_at*1000).toLocaleTimeString()}`:'Срабатываний пока не наблюдалось','set-desc rule-observation'));
    const actions=el('div',null,'rule-actions');for(const [text,fn]of [[rule.enabled===false?'Включить':'Выключить',()=>persist(current().map(r=>r.id===rule.id?{...r,enabled:r.enabled===false}:r))],['Изменить',()=>open(rule)],['Удалить',()=>{if(confirm('Удалить правило «'+rule.name+'»?'))return persist(current().filter(r=>r.id!==rule.id));}]]){const b=el('button',text,'btn btn-ghost');b.disabled=ST.status!=='off';b.onclick=async()=>{try{await fn();}catch(e){toast(e.message,'err');}};actions.append(b);}row.append(actions);row.ondragstart=e=>{dragging=rule.id;e.dataTransfer.setData('text/plain',rule.id);};row.ondragover=e=>{if(row.draggable)e.preventDefault();};row.ondrop=async e=>{e.preventDefault();if(!row.draggable||!dragging||dragging===rule.id)return;const reordered=current().slice(),index=reordered.findIndex(r=>r.id===dragging);if(index<0)return;const moved=reordered.splice(index,1)[0];reordered.splice(reordered.findIndex(r=>r.id===rule.id),0,moved);try{await persist(reordered);}catch(err){toast(err.message,'err');}dragging=null;};list.append(row);}if(!list.children.length)list.append(el('p','Правила не найдены','settings-empty'));add.disabled=ST.status!=='off';}
  const renderWithoutConflicts=render;render=function(){renderWithoutConflicts();refreshConflicts();};
  add.onclick=()=>open();search.oninput=render;
  const original=renderRules;renderRules=function(){original();render();};
  window.openAdvancedRule=open;
  const presets={messengers:['Мессенджеры',[['process','Telegram.exe'],['process','Discord.exe']]],video:['Видео',[['suffix','youtube.com'],['suffix','googlevideo.com'],['suffix','netflix.com']]],social:['Социальные сети',[['suffix','instagram.com'],['suffix','facebook.com']]],ai:['AI-сервисы',[['suffix','chatgpt.com'],['suffix','openai.com'],['suffix','claude.ai']]],games:['Игровые лаунчеры',[['process','steam.exe'],['process','EpicGamesLauncher.exe']]],ru:['Российские сайты напрямую',[['suffix','ru'],['suffix','рф']]]};
  for(const [key,[title,items]]of Object.entries(presets)){const card=el('article',null,'custom-rule glass');card.append(el('strong',title),el('p',items.map(x=>x[1]).join(', '),'set-desc'));const button=el('button','Добавить набор','btn btn-primary');button.onclick=async()=>{if(!confirm('Добавить правила: '+items.map(x=>x[1]).join(', ')+'?'))return;const rules=current().slice();for(const [kind,value]of items){if(!rules.some(r=>r.kind===kind&&r.value.toLowerCase()===value.toLowerCase()))rules.push({id:crypto.randomUUID(),kind,value,name:value,destination:key==='ru'?'direct':'proxy',enabled:true});}try{await persist(rules);toast('Набор добавлен','ok');}catch(e){toast(e.message,'err');}};card.append(button);presetPanel.append(card);}
  const torrent=el('button','Торрент-клиент → выбрать отдельный сервер','btn btn-ghost');torrent.onclick=()=>{open();requiresSeparateServer=true;value.value='qbittorrent.exe';name.value='Торрент-клиент';validate();server.focus();};presetPanel.append(torrent);
  render();
})();
