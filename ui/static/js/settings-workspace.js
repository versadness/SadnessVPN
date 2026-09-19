// Move existing controls intact: switching tabs never saves or resets settings.
(function () {
  const page = document.getElementById('page-settings');
  const pane = page.querySelector(':scope > .scroll');
  const nav = document.getElementById('settingNav');
  const categories = {all:'Все настройки',network:'Сеть',behavior:'Поведение',appearance:'Оформление',diagnostics:'Диагностика'};
  const mapping = {'Порты':'network','SOCKS5 аутентификация':'network','Туннель':'network','DNS':'network','Пинг':'network','Общие':'behavior','Персонализация':'appearance'};
  const groups = [];
  let current;
  for (const child of [...pane.children]) {
    if (child.classList.contains('sec')) {
      const title = child.querySelector('.sec-lbl').textContent;
      current = document.createElement('section');
      current.className = 'settings-group';
      current.dataset.category = mapping[title] || 'diagnostics';
      pane.insertBefore(current, child); current.append(child); groups.push(current);
    } else if (current) current.append(child);
  }
  const lan = page.querySelector('[data-sk="lan"]')?.closest('.set-row');
  if (lan) groups.find(g=>g.dataset.category==='network').append(lan);
  const startup = document.getElementById('autostartState');
  if (startup) groups.find(g=>g.dataset.category==='behavior').prepend(startup);
  for(const [category,key,title,description] of [['behavior','reconnect','Восстановление соединения','До трёх попыток после неожиданной остановки ядра. Ручное отключение отменяет восстановление.'],['behavior','mintray','Сворачивать при закрытии','Крестик скрывает окно в трей. Выход через меню трея завершает приложение.'],['appearance','animations','Декоративные анимации','Отключите для спокойного фона и меньшей нагрузки.']]){
    const row=document.createElement('div');row.className='set-row glass';const meta=document.createElement('div');meta.className='set-meta';const name=document.createElement('strong');name.className='set-name';name.textContent=title;const desc=document.createElement('p');desc.className='set-desc';desc.textContent=description;meta.append(name,desc);
    const toggle=document.createElement('button');toggle.type='button';toggle.className='toggle';toggle.dataset.sk=key;toggle.setAttribute('aria-label',title);toggle.onclick=()=>tglSetting(toggle,key);row.append(meta,toggle);groups.find(g=>g.dataset.category===category).append(row);
  }
  const toolbar = document.createElement('div'); toolbar.className = 'settings-search search glass';
  const search = document.createElement('input'); search.type='search'; search.id='settingsSearch';
  search.placeholder='Поиск по настройкам'; search.setAttribute('aria-label',search.placeholder);
  toolbar.append(search); nav.before(toolbar);
  const empty = document.createElement('p'); empty.className='settings-empty'; empty.textContent='Ничего не найдено. Попробуйте другое название.'; empty.hidden=true; pane.append(empty);
  let selected='all';
  let remembered='all';
  try { remembered=sessionStorage.getItem('settings-tab')||'all';if(categories[remembered])selected=remembered; } catch (_) {}
  nav.replaceChildren(); nav.setAttribute('aria-label','Категории настроек');
  function clearMarks() { page.querySelectorAll('mark.settings-match').forEach(mark=>mark.replaceWith(document.createTextNode(mark.textContent))); }
  function highlight(node, query) {
    const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT); const texts=[];
    while(walker.nextNode()) texts.push(walker.currentNode);
    for(const text of texts) {
      const value=text.nodeValue, lower=value.toLocaleLowerCase(); let start=0,index=lower.indexOf(query); if(index<0)continue;
      const fragment=document.createDocumentFragment();
      while(index>=0){fragment.append(document.createTextNode(value.slice(start,index)));const mark=document.createElement('mark');mark.className='settings-match';mark.textContent=value.slice(index,index+query.length);fragment.append(mark);start=index+query.length;index=lower.indexOf(query,start);}
      fragment.append(document.createTextNode(value.slice(start)));text.replaceWith(fragment);
    }
  }
  function filter() {
    clearMarks(); const query=search.value.trim().toLocaleLowerCase(); let visible=0;
    for(const group of groups) {
      let count=0;
      for(const row of [...group.children].filter(c=>!c.classList.contains('sec'))) {
        const matches=(!query ? selected==='all'||selected===group.dataset.category : row.textContent.toLocaleLowerCase().includes(query));
        row.hidden=!matches;
        if(matches){count++;if(query)row.querySelectorAll('.set-name,.set-desc,.about-k').forEach(el=>highlight(el,query));}
      }
      group.hidden=count===0;visible+=count;
    }
    empty.hidden=visible>0;
    for(const button of nav.children) button.setAttribute('aria-pressed',String(button.dataset.category===selected));
  }
  for(const [key,label] of Object.entries(categories)) {
    const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.category=key;
    button.addEventListener('click',()=>{selected=key;try{sessionStorage.setItem('settings-tab',key);}catch(_){}filter();pane.scrollTop=0;});nav.append(button);
  }
  nav.addEventListener('keydown',event=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(event.key))return;
    const buttons=[...nav.children],index=buttons.indexOf(document.activeElement);if(index<0)return;
    event.preventDefault();const next=event.key==='Home'?0:event.key==='End'?buttons.length-1:(index+(event.key==='ArrowRight'?1:-1)+buttons.length)%buttons.length;buttons[next].focus();buttons[next].click();
  });
  search.addEventListener('input',filter);
  // Modules can add a real settings panel without placeholder tabs.
  window.addSettingsPanel=function(key,label,section){categories[key]=label;section.dataset.category=key;section.classList.add('settings-group');pane.insertBefore(section,empty);groups.push(section);const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.category=key;button.onclick=()=>{selected=key;try{sessionStorage.setItem('settings-tab',key);}catch(_){}filter();pane.scrollTop=0;};nav.append(button);if(remembered===key)selected=key;filter();};
  filter();
})();
