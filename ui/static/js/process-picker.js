/* Единственная реализация выбора запущенного приложения.
 *
 * Раньше списков было два: модалка processModal в app.js (только имена EXE,
 * без иконок) и раскрывающийся блок внутри формы редактора правил. Второй
 * растягивал форму и давал вложенные полосы прокрутки. Теперь оба вызова
 * идут сюда, в отдельный дочерний <dialog>, а источник данных один —
 * /api/apps/catalog, где engine/process_catalog уже отсеял системные и
 * запрещённые процессы и подставил понятные названия.
 *
 * Наружу уходит только {value,name}: ни PID, ни полный путь, ни командная
 * строка здесь не запрашиваются и не сохраняются.
 */
(function () {
  const NOTE = 'Выбирайте процесс самой игры, а не только лаунчера. ' +
    'Например, после запуска игры обновите список и найдите её исполняемый файл.';

  let dialog = null, ui = null, resolve = null, anchor = null;
  let mode = 'process', kind = 'process', items = [], loaded = '';

  const escape = s => String(s == null ? '' : s)
    .replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function build() {
    dialog = document.createElement('dialog');
    dialog.id = 'processPicker';
    dialog.className = 'process-picker';
    dialog.setAttribute('aria-labelledby', 'processPickerTitle');
    dialog.innerHTML = `
      <div class="picker-head">
        <div class="picker-head-text">
          <h2 id="processPickerTitle">Выбрать из запущенных</h2>
          <p class="picker-sub" id="processPickerCount">Получение списка…</p>
        </div>
        <button type="button" class="picker-close" id="processPickerClose" aria-label="Закрыть">×</button>
      </div>
      <p class="picker-note" id="processPickerNote"></p>
      <div class="picker-search">
        <input type="search" id="processPickerSearch" class="inp" autocomplete="off" spellcheck="false"
               aria-label="Поиск запущенного приложения" placeholder="Поиск по названию или имени EXE">
        <button type="button" class="btn btn-ghost picker-refresh" id="processPickerRefresh">Обновить</button>
      </div>
      <div class="picker-list" id="processPickerList" role="listbox" aria-labelledby="processPickerTitle"></div>
      <div class="picker-manual">
        <label class="form-label" for="processPickerManual">Или введите имя вручную</label>
        <div class="picker-manual-row">
          <input class="inp" id="processPickerManual" maxlength="253" autocomplete="off" spellcheck="false"
                 placeholder="Например, Telegram.exe">
          <button type="button" class="btn btn-primary" id="processPickerManualApply">Использовать</button>
        </div>
        <p class="picker-manual-error" id="processPickerManualError" role="alert"></p>
      </div>
      <div class="picker-actions">
        <button type="button" class="btn btn-ghost" id="processPickerCancel">Отмена</button>
      </div>`;
    document.body.append(dialog);
    ui = {
      title: dialog.querySelector('#processPickerTitle'),
      count: dialog.querySelector('#processPickerCount'),
      note: dialog.querySelector('#processPickerNote'),
      search: dialog.querySelector('#processPickerSearch'),
      refresh: dialog.querySelector('#processPickerRefresh'),
      list: dialog.querySelector('#processPickerList'),
      manual: dialog.querySelector('#processPickerManual'),
      manualApply: dialog.querySelector('#processPickerManualApply'),
      manualError: dialog.querySelector('#processPickerManualError'),
      manualBlock: dialog.querySelector('.picker-manual'),
    };
    // Обработчики вешаются ровно один раз: повторное открытие их не дублирует.
    ui.search.addEventListener('input', renderList);
    ui.refresh.addEventListener('click', () => load(true));
    ui.manual.addEventListener('input', () => { ui.manualError.textContent = ''; });
    ui.manual.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); applyManual(); }
    });
    ui.manualApply.addEventListener('click', applyManual);
    ui.list.addEventListener('click', event => {
      const row = event.target.closest('.picker-row');
      if (row) finish({ value: row.dataset.value, name: row.dataset.name });
    });
    for (const id of ['processPickerClose', 'processPickerCancel']) {
      dialog.querySelector('#' + id).addEventListener('click', () => finish(null));
    }
    // Escape закрывает только этот, верхний диалог — родительский остаётся.
    dialog.addEventListener('cancel', event => { event.preventDefault(); finish(null); });
    dialog.addEventListener('close', () => finish(null));
  }

  function finish(result) {
    const pending = resolve;
    resolve = null;
    if (dialog.open) dialog.close();
    if (anchor && document.contains(anchor)) anchor.focus();
    anchor = null;
    if (pending) pending(result);
  }

  function applyManual() {
    let value = ui.manual.value.trim();
    if (!value) { ui.manualError.textContent = 'Введите значение'; ui.manual.focus(); return; }
    if (mode === 'process') {
      if (/[\\/:*?"<>|,()]/.test(value)) {
        ui.manualError.textContent = 'Укажите только имя процесса, без пути';
        ui.manual.focus();
        return;
      }
      if (!value.toLowerCase().endsWith('.exe')) value += '.exe';
    }
    finish({ value, name: mode === 'process' ? value.replace(/\.exe$/i, '') : value });
  }

  function renderList() {
    const query = (ui.search.value || '').trim().toLowerCase();
    const matches = query
      ? items.filter(item => (item.name + ' ' + item.value).toLowerCase().includes(query))
      : items;
    const shown = matches.slice(0, 300);
    ui.count.textContent = query
      ? `Найдено: ${matches.length} из ${items.length}`
      : `Доступно: ${items.length}`;
    if (!shown.length) {
      ui.list.innerHTML = `<p class="picker-state">${query ? 'Ничего не найдено. Измените запрос или обновите список.' : 'Список пуст. Запустите приложение и обновите список.'}</p>`;
      return;
    }
    ui.list.innerHTML = shown.map(item => `
      <button type="button" class="picker-row" role="option" aria-selected="false"
              data-value="${escape(item.value)}" data-name="${escape(item.name)}">
        ${mode === 'process'
          ? `<img class="picker-ico" width="24" height="24" alt="" loading="lazy" src="/api/apps/icon?exe=${encodeURIComponent(item.value)}" onerror="this.classList.add('missing')">`
          : '<span class="picker-ico picker-ico-glyph" aria-hidden="true">◇</span>'}
        <span class="picker-text">
          <span class="picker-name" title="${escape(item.name)}">${escape(item.name)}</span>
          <span class="picker-exe" title="${escape(item.value)}">${escape(item.value)}</span>
        </span>
      </button>`).join('')
      + (matches.length > shown.length
        ? '<p class="picker-state">Показаны первые 300. Уточните поиск.</p>' : '');
  }

  async function load(force) {
    const key = mode === 'process' ? 'process' : kind;
    if (!force && loaded === key && items.length) { renderList(); return; }
    ui.list.innerHTML = '<p class="picker-state">Получение списка…</p>';
    ui.count.textContent = 'Получение списка…';
    try {
      const endpoint = mode === 'process'
        ? '/api/apps/catalog'
        : '/api/routing/categories?kind=' + encodeURIComponent(kind);
      const response = await fetch(endpoint, { headers: { 'Accept': 'application/json' } });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || data.ok === false) throw Error(data.error || 'Список недоступен');
      const raw = mode === 'process'
        ? (data.apps || []).map(app => ({ value: app.exe, name: app.name || app.exe }))
        : (data.items || data.categories || []).map(value => ({ value, name: value }));
      // Одно приложение — одна строка, даже если процессов у него несколько.
      const unique = new Map();
      for (const item of raw) {
        if (!item || typeof item.value !== 'string' || !item.value.trim()) continue;
        const id = item.value.trim().toLowerCase();
        if (!unique.has(id)) unique.set(id, { value: item.value.trim(), name: String(item.name || item.value).trim() });
      }
      items = [...unique.values()].sort((a, b) => a.name.localeCompare(b.name, 'ru', { sensitivity: 'base' }));
      loaded = key;
      renderList();
    } catch (error) {
      items = [];
      loaded = '';
      ui.count.textContent = 'Список недоступен';
      // Наружу отдаём только текст ошибки — без путей и командных строк.
      ui.list.innerHTML = `<p class="picker-state picker-error">${escape(error.message || 'Не удалось получить список')}</p>`;
    }
  }

  /** Открыть выбор. Возвращает {value,name} либо null, если отменили. */
  window.openProcessPicker = function (options = {}) {
    if (!dialog) build();
    if (resolve) finish(null);
    mode = options.mode === 'category' ? 'category' : 'process';
    kind = options.kind || 'process';
    anchor = options.anchor || document.activeElement;
    ui.title.textContent = options.title ||
      (mode === 'process' ? 'Выбрать из запущенных' : 'Выбрать из списка');
    ui.note.textContent = mode === 'process' ? (options.note || NOTE) : '';
    ui.note.hidden = mode !== 'process';
    ui.manualBlock.hidden = mode !== 'process';
    ui.search.value = '';
    ui.manual.value = options.current || '';
    ui.manualError.textContent = '';
    dialog.showModal();
    ui.search.focus();
    const promise = new Promise(done => { resolve = done; });
    load(false);
    return promise;
  };
})();
