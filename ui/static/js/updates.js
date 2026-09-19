(function(){
  const section=document.createElement('section');
  const card=document.createElement('div');card.className='set-row glass update-card';
  const meta=document.createElement('div');meta.className='set-meta';
  const title=document.createElement('strong');title.className='set-name';title.textContent='Обновления Sadness VPN';
  const status=document.createElement('p');status.className='set-desc';status.setAttribute('aria-live','polite');
  const details=document.createElement('p');details.className='set-desc';
  const channel=document.createElement('select');channel.className='inp compact';channel.setAttribute('aria-label','Канал обновлений');for(const key of ['beta','stable']){const o=document.createElement('option');o.value=key;o.textContent=key==='beta'?'Beta':'Stable';channel.append(o);}
  const progress=document.createElement('progress');progress.max=100;progress.hidden=true;
  const notes=document.createElement('ul');notes.className='set-desc';
  const actions=document.createElement('div');actions.className='rule-actions';
  const buttons={};for(const [key,label]of [['check','Проверить обновления'],['download','Скачать'],['cancel','Отменить загрузку'],['install','Установить и перезапустить']]){const b=document.createElement('button');b.type='button';b.className='btn btn-ghost';b.textContent=label;buttons[key]=b;actions.append(b);}
  meta.append(title,status,details,channel,progress,notes,actions);card.append(meta);section.append(card);
  const historyHead=document.createElement('div');historyHead.className='history-head';
  const historyList=document.createElement('div');historyList.className='history-list';
  section.append(historyHead,historyList);
  window.addSettingsPanel('updates','Обновления',section);
  let timer=null,noticeVersion=null,lastStatus=null;
  function render(state){
    lastStatus=state.status;title.textContent='Sadness VPN '+state.version;status.textContent=state.message||'';
    renderHistory(state.version);
    details.textContent=[state.available_version?'Доступная версия: '+state.available_version:'',state.size?(state.size/1048576).toFixed(1)+' МБ':'',state.published_at?'Опубликовано: '+state.published_at:'',state.checked_at?'Проверено: '+new Date(state.checked_at*1000).toLocaleString():''].filter(Boolean).join(' · ');
    if(state.last_update?.message)details.textContent+=' · '+state.last_update.message;
    if(state.recovery_size)details.textContent+=' · Резервный MSI: '+(state.recovery_size/1048576).toFixed(1)+' МБ дополнительно';
    if(state.channel)channel.value=state.channel;
    notes.replaceChildren();for(const note of state.notes||[]){const li=document.createElement('li');li.textContent=note;notes.append(li);}
    const busy=['checking','downloading','installing'].includes(state.status);buttons.check.disabled=busy;channel.disabled=busy;
    buttons.download.hidden=!(state.can_download??['available','cancelled'].includes(state.status));buttons.download.textContent=state.status==='error'?'Повторить загрузку':'Скачать';buttons.cancel.hidden=state.status!=='downloading';buttons.install.hidden=state.status!=='ready';
    progress.hidden=state.status!=='downloading';progress.value=state.progress||0;
    if(state.suppress_notice){status.textContent+=' · После трёх ошибок уведомления для этой версии отключены. Ручная загрузка доступна.';document.querySelectorAll('.update-notice').forEach(n=>n.remove());}
    if(state.status==='available'&&!state.suppress_notice&&noticeVersion!==state.available_version){noticeVersion=state.available_version;showNotice(state);}
    if(timer){clearTimeout(timer);timer=null;}if(['checking','downloading'].includes(state.status))timer=setTimeout(refresh,500);
  }

  function versionKey(value){return String(value||'0').split('.').map(n=>parseInt(n,10)||0);}
  function newer(a,b){const x=versionKey(a),y=versionKey(b);for(let i=0;i<Math.max(x.length,y.length);i++){const d=(x[i]||0)-(y[i]||0);if(d)return d>0;}return false;}
  let history=null;
  async function renderHistory(installed){
    if(history===null){try{const r=await fetch('/static/version-history.json');history=r.ok?await r.json():[];}catch(_){history=[];}}
    if(!history.length){historyHead.textContent='';historyList.replaceChildren();return;}
    const ahead=history.filter(entry=>newer(entry.version,installed)).length;
    historyHead.textContent='История версий'+(ahead?' · новее вашей: '+ahead:'');
    historyList.replaceChildren();
    for(const entry of history){
      const item=document.createElement('article');item.className='history-item glass';
      if(newer(entry.version,installed))item.classList.add('ahead');
      const head=document.createElement('header');
      const tag=document.createElement('strong');tag.textContent='v'+entry.version;head.append(tag);
      if(newer(entry.version,installed)){const badge=document.createElement('span');badge.className='history-badge';badge.textContent='НОВОЕ';head.append(badge);}
      else if(entry.version===installed){const badge=document.createElement('span');badge.className='history-badge current';badge.textContent='УСТАНОВЛЕНА';head.append(badge);}
      const date=document.createElement('time');date.textContent=entry.released||'';head.append(date);
      item.append(head);
      const list=document.createElement('ul');
      for(const note of entry.notes||[]){const li=document.createElement('li');li.textContent=note;list.append(li);}
      item.append(list);historyList.append(item);
    }
  }
  async function refresh(){try{const r=await fetch('/api/updates/state');if(r.ok)render(await r.json());}catch(_){status.textContent='Нет связи с приложением';}}
  async function command(key,body={}){try{const result=await api('/api/updates/'+key,body);if(!result.ok){toast(result.error||'Операция не выполнена','err');return;}
    // Окном владеет оболочка Electron: закрыть его может только она, а установщик
    // ждёт освобождения файлов в каталоге установки не дольше 45 секунд.
    if(result.shell_quit&&window.sadnessShell&&window.sadnessShell.app&&window.sadnessShell.app.quit){status.textContent='Приложение закрывается для установки обновления…';try{await window.sadnessShell.app.quit();}catch(_){}return;}
    if(result.status)render(result);else await refresh();}catch(_){status.textContent='Нет связи с приложением';}}
  buttons.check.onclick=()=>command('check',{channel:channel.value});channel.onchange=()=>{status.textContent='Канал выбран. Нажмите «Проверить обновления».';buttons.download.hidden=true;buttons.install.hidden=true;};
  buttons.download.onclick=()=>command('download');buttons.cancel.onclick=()=>command('cancel');buttons.install.onclick=()=>command('install');
  function showNotice(state){document.querySelectorAll('.update-notice').forEach(n=>n.remove());const notice=document.createElement('div');notice.className='update-notice glass';const text=document.createElement('strong');text.textContent='Доступна '+state.available_version+' '+state.channel;notice.append(text);const summary=document.createElement('p');summary.className='set-desc';summary.textContent=[state.size?(state.size/1048576).toFixed(1)+' МБ':'',...(state.notes||[]).slice(0,2)].filter(Boolean).join(' · ');notice.append(summary);for(const [label,action]of [['Подробнее',()=>{go('settings');document.querySelector('#settingNav [data-category="updates"]').click();notice.remove();}],['Скачать',()=>{command('download');notice.remove();}],['Позже',()=>notice.remove()]]){const button=document.createElement('button');button.className='btn btn-ghost';button.textContent=label;button.onclick=action;notice.append(button);}document.body.append(notice);}
  // The backend also deduplicates this request across WebView reloads.
  command('check',{automatic:true});
})();
