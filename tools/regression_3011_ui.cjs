/* UI-регрессии 3.0.11: редактор правил, дочерний диалог выбора процесса,
 * вёрстка на разных размерах окна и игровой фильтр Zapret.
 *
 * Скриншоты и замеры сохраняются ДО assert, чтобы при падении остались
 * доказательства, а не только текст ошибки.
 */
const fs = require('fs'), path = require('path'), assert = require('assert/strict');
const { chromium } = require('C:/Users/Sadness/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const out = path.join(root, 'build', 'regression-3011');
fs.mkdirSync(out, { recursive: true });

const evidence = { viewports: {}, notes: [] };
const save = () => fs.writeFileSync(path.join(out, 'evidence.json'), JSON.stringify(evidence, null, 2));

const CATALOG = [
  { exe: 'Telegram.exe', name: 'Telegram' },
  { exe: 'Discord.exe', name: 'Discord' },
  { exe: 'DeadByDaylight-Win64-Shipping.exe', name: 'Dead by Daylight Win64 Shipping Very Long Product Name' },
  { exe: 'Steam.exe', name: 'Steam' },
  ...Array.from({ length: 60 }, (_, i) => ({ exe: `filler${i}.exe`, name: `Filler ${i}` })),
];

const VIEWPORTS = [
  { name: '1366x768', width: 1366, height: 768 },
  { name: '964x661', width: 964, height: 661 },
  { name: '620x440', width: 620, height: 440 },
  { name: '480x720', width: 480, height: 720 },
  // Масштабирование Windows/браузера 125% и 150% — это тот же CSS-пиксельный
  // viewport меньшего размера при том же физическом окне.
  { name: '1366x768@125', width: 1093, height: 614 },
  { name: '1366x768@150', width: 911, height: 512 },
];

// Ответ бэкенда об эффективном охвате: интерфейс обязан показывать его, а не
// придумывать формулировки самостоятельно.
const COVERAGE = scope => ({
  strategy: 'General', scope, scope_label: scope === 'custom' ? 'Пользовательские фильтры'
    : scope === 'extended' ? 'Расширенный системный охват' : 'Стандартный охват стратегии',
  protocols: ['QUIC (HTTP/3)', 'Discord'],
  tcp_ports: ['80', '443'], udp_ports: scope === 'custom' ? ['443', '27000-27100'] : ['443'],
  ports_label: scope === 'custom' ? 'TCP 80, 443 · UDP 443, 27000-27100' : 'TCP 80, 443 · UDP 443',
  hostlists: ['list-general.txt'], domains: [], ipsets: ['ipset-all.txt'],
  excludes: ['ipset-exclude.txt'], restart_required: true, vpn_mode: null,
  notes: ['Охват выбран.', 'Часть секций ограничена списками сайтов.'],
});

const STATE = {
  type: 'state', appVersion: '3.0.11', status: 'off', connected: false,
  groups: [{ id: 'g', name: 'Подписка', servers: [{ ui_id: 's1', remark: 'Amsterdam', protocol: 'vless', type: 'tcp', security: 'reality' }] }],
  selGroup: 'g', selIndex: 0,
  appsConfig: { mode: 'all', apps: [], rules: [] },
  appSettings: { socks: 1080, http: 8080 }, tunnelSettings: {},
  zapretStrategies: [{ id: 'flowseal_general', name: 'General', category: 'Основная', desc: 'Основная', icon: '✦', tags: ['Discord'] }],
  zapretSelected: 'flowseal_general',
  zapretGameFilter: { scope: 'standard', mode: 'off', ipset: 'list', tcp_start: 1024, tcp_end: 65535, udp_start: 1024, udp_end: 65535 },
  zapretCoverage: COVERAGE('standard'),
};

(async () => {
  const browser = await chromium.launch({
    headless: true,
    executablePath: 'C:/Users/Sadness/AppData/Local/ms-playwright/chromium-1228/chrome-win64/chrome.exe',
  });
  let failed = null;
  try {
    const page = await browser.newPage({ viewport: { width: 1366, height: 768 } });
    const errors = [];
    let catalogCalls = 0, catalogFails = false;
    const savedRules = [];
    page.on('pageerror', e => errors.push(e.message));

    await page.route('**/*', async route => {
      const u = new URL(route.request().url());
      if (u.pathname === '/api/apps/icon') return route.fulfill({ status: 404, body: '' });
      if (u.pathname.startsWith('/api/')) {
        const body = route.request().postDataJSON();
        let result = { ok: true };
        if (u.pathname === '/api/apps/catalog') {
          catalogCalls++;
          if (catalogFails) return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ ok: false, error: 'Список процессов недоступен' }) });
          result.apps = CATALOG;
        }
        if (u.pathname === '/api/routing/rules') { result.rules = body?.rules || []; savedRules.push(...result.rules); }
        if (u.pathname === '/api/routing/conflicts') result.conflicts = {};
        if (u.pathname === '/api/zapret/game-filter') { result.game_filter = body?.game_filter; result.summary = {}; result.coverage = COVERAGE(body?.game_filter?.scope || 'standard'); }
        if (u.pathname === '/api/zapret/coverage') result.coverage = COVERAGE('standard');
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify(result) });
      }
      const file = u.pathname === '/' ? path.join(root, 'ui/templates/index.html') : path.join(root, 'ui', u.pathname);
      if (!file.startsWith(path.join(root, 'ui')) || !fs.existsSync(file)) return route.fulfill({ status: 404, body: '' });
      return route.fulfill({
        body: fs.readFileSync(file),
        contentType: file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html',
      });
    });
    await page.addInitScript(() => { window.WebSocket = class { static OPEN = 1; constructor() { this.readyState = 1; } close() { } }; });
    await page.goto('http://127.0.0.1:45690/?desktop=1');
    await page.evaluate(state => { handle(state); go('routing'); }, STATE);

    const openEditor = async () => {
      await page.evaluate(() => window.openAdvancedRule());
      await page.locator('dialog.routing-editor[open]').waitFor();
    };
    const openPicker = async () => {
      await page.locator('.route-pick-btn').click();
      await page.locator('dialog.process-picker[open]').waitFor();
      await page.locator('.picker-row').first().waitFor();
    };

    // ── 1. Выбор процесса заполняет точное имя EXE ───────────────────────────
    await openEditor();
    await openPicker();
    assert.equal(await page.locator('.route-pick-btn').textContent(), 'Выбрать из запущенных',
      'Кнопка должна называться «Выбрать из запущенных»');

    await page.locator('#processPickerSearch').fill('Daylight');
    await page.locator('.picker-row').first().waitFor();
    const found = await page.locator('.picker-row').count();
    evidence.search = { query: 'Daylight', rows: found };
    save();
    assert.equal(found, 1, 'Поиск должен сузить список до одного совпадения');

    await page.screenshot({ path: path.join(out, 'picker-search.png') });
    await page.locator('.picker-row').first().click();
    await page.locator('dialog.process-picker[open]').waitFor({ state: 'detached' }).catch(() => { });
    const picked = await page.evaluate(() => ({
      value: document.getElementById('routeValue').value,
      name: document.getElementById('routeName').value,
      note: document.querySelector('.route-picked')?.textContent || '',
      open: document.getElementById('processPicker').open,
      focus: document.activeElement?.className || '',
    }));
    evidence.picked = picked;
    save();
    assert.equal(picked.value, 'DeadByDaylight-Win64-Shipping.exe', 'В поле попадает точное имя EXE');
    assert(picked.note.includes('DeadByDaylight-Win64-Shipping.exe') && picked.note.includes('Dead by Daylight'),
      'Пользователь видит и понятное название, и фактический EXE');
    assert.equal(picked.open, false, 'Дочерний диалог закрывается после выбора');
    assert(!picked.value.includes('\\') && !picked.value.includes('/'), 'Полный путь не сохраняется');

    // Сохраняем правило и смотрим, что реально уходит на бэкенд.
    await page.locator('dialog.routing-editor .btn-primary').click();
    await page.waitForTimeout(400);
    const saved = savedRules.at(-1) || {};
    evidence.savedRule = saved;
    save();
    assert.equal(saved.value, 'DeadByDaylight-Win64-Shipping.exe', 'В правило сохраняется точное имя EXE');
    assert.deepEqual(Object.keys(saved).sort(), ['destination', 'enabled', 'id', 'kind', 'name', 'value'],
      'В правиле нет лишних полей: ни PID, ни пути, ни командной строки');
    await openEditor();

    // ── 2. Повторное открытие не дублирует обработчики ───────────────────────
    await openPicker();
    await page.locator('#processPickerSearch').fill('Telegram');
    await page.locator('.picker-row').first().click();
    await openPicker();
    await page.locator('#processPickerSearch').fill('Steam');
    const clicks = await page.evaluate(async () => {
      let count = 0;
      const original = document.getElementById('routeValue');
      const observer = new MutationObserver(() => { });
      observer.observe(original, { attributes: true });
      const row = document.querySelector('.picker-row');
      const before = original.value;
      row.click();
      await new Promise(r => setTimeout(r, 50));
      count = original.value === before ? 0 : 1;
      return { count, value: original.value };
    });
    evidence.reopen = clicks;
    save();
    assert.equal(clicks.value, 'Steam.exe', 'Повторное открытие выбирает корректно, без дублирования обработчиков');

    // ── 3. Обновление списка и выбор после него ──────────────────────────────
    await openPicker();
    const before = catalogCalls;
    await page.locator('#processPickerRefresh').click();
    await page.waitForTimeout(150);
    await page.locator('.picker-row').first().waitFor();
    await page.locator('#processPickerSearch').fill('Discord');
    await page.locator('.picker-row').first().click();
    const afterRefresh = await page.evaluate(() => document.getElementById('routeValue').value);
    evidence.refresh = { calls: catalogCalls - before, value: afterRefresh };
    save();
    assert(catalogCalls > before, 'Кнопка «Обновить» перезапрашивает список');
    assert.equal(afterRefresh, 'Discord.exe', 'Выбор работает после обновления списка');

    // ── 4. Ручной ввод ───────────────────────────────────────────────────────
    await openPicker();
    await page.locator('#processPickerManual').fill('MyGame');
    await page.locator('#processPickerManualApply').click();
    const manual = await page.evaluate(() => document.getElementById('routeValue').value);
    evidence.manual = manual;
    save();
    assert.equal(manual, 'MyGame.exe', 'Ручной ввод дополняется расширением .exe');

    await openPicker();
    await page.locator('#processPickerManual').fill('C:\\games\\bad.exe');
    await page.locator('#processPickerManualApply').click();
    const manualError = await page.locator('#processPickerManualError').textContent();
    evidence.manualError = manualError;
    save();
    assert(manualError.includes('без пути'), 'Путь в ручном вводе отклоняется с понятным сообщением');
    await page.keyboard.press('Escape');

    // ── 5. Ошибка загрузки показывается безопасно ────────────────────────────
    catalogFails = true;
    await openEditor();
    await page.locator('.route-pick-btn').click();
    // Список кэшируется между открытиями, поэтому отказ ловим на «Обновить».
    await page.locator('#processPickerRefresh').click();
    await page.locator('.picker-error').waitFor();
    const errorText = await page.locator('.picker-error').textContent();
    await page.screenshot({ path: path.join(out, 'picker-error.png') });
    evidence.apiError = errorText;
    save();
    assert(errorText.includes('недоступен'), 'Ошибка API показывается пользователю');
    assert(!/[A-Z]:\\|Traceback|\/home\//.test(errorText), 'В ошибке нет путей и трассировок');
    catalogFails = false;

    // ── 6. Escape закрывает только верхний диалог, фокус возвращается ────────
    await page.keyboard.press('Escape');
    const afterEscape = await page.evaluate(() => ({
      picker: document.getElementById('processPicker').open,
      editor: document.querySelector('dialog.routing-editor').open,
      focused: document.activeElement?.classList.contains('route-pick-btn'),
    }));
    evidence.escape = afterEscape;
    save();
    assert.equal(afterEscape.picker, false, 'Escape закрывает дочерний диалог');
    assert.equal(afterEscape.editor, true, 'Escape не закрывает сразу оба диалога');
    assert.equal(afterEscape.focused, true, 'Фокус возвращается на кнопку «Выбрать из запущенных»');

    // ── 7. Вёрстка на каждом размере окна ────────────────────────────────────
    for (const viewport of VIEWPORTS) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.waitForTimeout(80);

      const editor = await page.evaluate(() => {
        const dialog = document.querySelector('dialog.routing-editor');
        const body = dialog.querySelector('.route-form-body');
        const row = dialog.querySelector('.route-value-row');
        const input = row.querySelector('.inp');
        const button = row.querySelector('.route-pick-btn');
        const groups = [...body.querySelectorAll('.form-group')];
        const rect = n => { const r = n.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height }; };
        const actions = dialog.querySelector('.modal-actions');
        return {
          dialog: rect(dialog), body: rect(body), row: rect(row),
          input: rect(input), button: rect(button), actions: rect(actions),
          gaps: groups.slice(1).map((n, i) => n.getBoundingClientRect().top - groups[i].getBoundingClientRect().bottom),
          stacked: button.getBoundingClientRect().top >= input.getBoundingClientRect().bottom - 1,
          bodyScrollX: body.scrollWidth - body.clientWidth,
          docScrollX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          nestedScrollers: [...body.querySelectorAll('*')].filter(n => {
            const style = getComputedStyle(n);
            return /auto|scroll/.test(style.overflowY) && n.scrollHeight > n.clientHeight + 1;
          }).length,
          viewport: { width: window.innerWidth, height: window.innerHeight },
        };
      });
      evidence.viewports[viewport.name] = { editor };
      save();
      await page.screenshot({ path: path.join(out, `editor-${viewport.name}.png`) });

      assert(editor.dialog.width <= editor.viewport.width + 1 && editor.dialog.height <= editor.viewport.height + 1,
        `${viewport.name}: диалог выходит за viewport`);
      assert(editor.dialog.top >= -1 && editor.dialog.left >= -1,
        `${viewport.name}: диалог обрезан сверху или слева`);
      assert.equal(editor.docScrollX, 0, `${viewport.name}: появился горизонтальный скролл страницы`);
      assert.equal(editor.bodyScrollX, 0, `${viewport.name}: появился горизонтальный скролл формы`);
      assert.equal(editor.nestedScrollers, 0, `${viewport.name}: внутри формы появился вложенный скролл`);
      assert(editor.gaps.every(gap => gap >= 13 && gap <= 20),
        `${viewport.name}: неверный вертикальный gap между группами: ${JSON.stringify(editor.gaps)}`);
      assert(editor.input.right <= editor.row.right + 1 && editor.button.right <= editor.row.right + 1,
        `${viewport.name}: поле или кнопка выходят за контейнер`);
      assert(editor.actions.bottom <= editor.dialog.bottom + 1 && editor.actions.top >= editor.dialog.top,
        `${viewport.name}: кнопки сохранения/отмены недостижимы`);
      if (!editor.stacked) {
        assert(editor.input.width >= 140, `${viewport.name}: кнопка сжала поле до ${editor.input.width}px`);
        assert(editor.button.left >= editor.input.right - 1, `${viewport.name}: поле и кнопка перекрываются`);
      } else {
        assert(editor.button.top >= editor.input.bottom - 1, `${viewport.name}: столбец собран неправильно`);
      }

      // Диалог процессов на том же размере окна.
      await page.locator('.route-pick-btn').click();
      await page.locator('.picker-row').first().waitFor();
      const picker = await page.evaluate(() => {
        const dialog = document.getElementById('processPicker');
        const list = dialog.querySelector('.picker-list');
        const rows = [...list.querySelectorAll('.picker-row')];
        const rect = n => { const r = n.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height }; };
        const last = rows[rows.length - 1];
        list.scrollTop = list.scrollHeight;
        const lastAfterScroll = last.getBoundingClientRect();
        list.scrollTop = 0;
        return {
          dialog: rect(dialog), list: rect(list),
          rowHeight: rows[0].getBoundingClientRect().height,
          rowGap: rows[1].getBoundingClientRect().top - rows[0].getBoundingClientRect().bottom,
          listScrollX: list.scrollWidth - list.clientWidth,
          docScrollX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
          nestedRowScrollers: rows.filter(r => r.scrollHeight > r.clientHeight + 1 || r.scrollWidth > r.clientWidth + 1).length,
          lastRowReachable: lastAfterScroll.bottom <= list.getBoundingClientRect().bottom + 1
            && lastAfterScroll.top >= list.getBoundingClientRect().top - 1,
          ellipsis: getComputedStyle(rows[0].querySelector('.picker-name')).textOverflow,
          iconWidth: rows[0].querySelector('.picker-ico').getBoundingClientRect().width,
          viewport: { width: window.innerWidth, height: window.innerHeight },
        };
      });
      evidence.viewports[viewport.name].picker = picker;
      save();
      await page.screenshot({ path: path.join(out, `picker-${viewport.name}.png`) });

      assert(picker.dialog.width <= picker.viewport.width + 1 && picker.dialog.height <= picker.viewport.height + 1,
        `${viewport.name}: диалог процессов выходит за viewport`);
      assert.equal(picker.listScrollX, 0, `${viewport.name}: горизонтальный скролл в списке процессов`);
      assert.equal(picker.docScrollX, 0, `${viewport.name}: горизонтальный скролл страницы при открытом списке`);
      assert.equal(picker.nestedRowScrollers, 0, `${viewport.name}: строка списка сама прокручивается`);
      assert(picker.rowHeight >= 46 && picker.rowHeight <= 60, `${viewport.name}: высота строки ${picker.rowHeight}px`);
      assert(picker.rowGap >= 4, `${viewport.name}: строки списка слиплись (gap ${picker.rowGap}px)`);
      assert.equal(picker.ellipsis, 'ellipsis', `${viewport.name}: длинные имена не обрезаются`);
      assert.equal(Math.round(picker.iconWidth), 24, `${viewport.name}: иконка сжалась`);
      assert(picker.lastRowReachable, `${viewport.name}: последняя строка недостижима прокруткой`);

      await page.keyboard.press('Escape');
      await page.waitForTimeout(60);
    }

    // ── 8. Enter/Space выбирают процесс с клавиатуры ─────────────────────────
    await page.setViewportSize({ width: 1366, height: 768 });
    await page.locator('.route-pick-btn').click();
    await page.locator('.picker-row').first().waitFor();
    await page.locator('#processPickerSearch').fill('Telegram');
    await page.locator('.picker-row').first().focus();
    const focusRing = await page.evaluate(() => getComputedStyle(document.activeElement, ':focus-visible').outlineWidth);
    await page.keyboard.press('Enter');
    const keyboardPick = await page.evaluate(() => document.getElementById('routeValue').value);
    evidence.keyboard = { value: keyboardPick, focusRing };
    save();
    assert.equal(keyboardPick, 'Telegram.exe', 'Enter выбирает процесс');

    // ── 9. Игровой фильтр Zapret в интерфейсе ────────────────────────────────
    await page.evaluate(() => { document.querySelector('dialog.routing-editor').close(); go('zapret'); });
    const gameFilter = await page.evaluate(async () => {
      document.getElementById('gfScope').value = 'custom';
      document.getElementById('gfMode').value = 'both';
      document.getElementById('gfUdpStart').value = '27000';
      document.getElementById('gfUdpEnd').value = '27100';
      await saveGameFilter();
      const rows = [...document.querySelectorAll('#gfEffective .gf-row')].map(r => r.textContent);
      return {
        rows,
        error: document.getElementById('gfError').textContent,
        summary: document.getElementById('gfSummary').textContent,
        notes: [...document.querySelectorAll('#gfCoverageNotes li')].map(n => n.textContent),
        rangesHidden: document.getElementById('gfRanges').hidden,
      };
    });
    evidence.gameFilter = gameFilter;
    save();
    await page.screenshot({ path: path.join(out, 'zapret-coverage.png') });
    assert.equal(gameFilter.error, '', 'Корректная настройка не даёт ошибки');
    assert.equal(gameFilter.rangesHidden, false, 'Свои диапазоны доступны в пользовательском охвате');
    assert(gameFilter.rows.some(r => r.includes('27000–27100')), 'Показан эффективный UDP-диапазон');
    assert(gameFilter.rows.some(r => r.includes('Профиль Zapret')), 'Показан выбранный профиль');
    assert(gameFilter.rows.some(r => r.includes('Охваченные порты')), 'Показаны охваченные порты');
    assert(gameFilter.rows.some(r => r.includes('Обрабатываемые протоколы')), 'Показаны протоколы');
    assert(gameFilter.rows.some(r => r.includes('Ограничение по адресам')), 'Показано ограничение по адресам');
    assert(gameFilter.rows.some(r => r.includes('после перезапуска обхода')), 'Сказано, когда применяются изменения');
    assert(gameFilter.notes.length > 0, 'Показаны пояснения об охвате');

    // Стандартный охват прячет поля, которые к нему не относятся.
    const standard = await page.evaluate(async () => {
      document.getElementById('gfScope').value = 'standard';
      await saveGameFilter();
      return {
        mode: document.getElementById('gfModeField').hidden,
        ipset: document.getElementById('gfIpsetField').hidden,
        ranges: document.getElementById('gfRanges').hidden,
        summary: document.getElementById('gfSummary').textContent,
      };
    });
    evidence.standardScope = standard;
    save();
    assert(standard.mode && standard.ipset && standard.ranges, 'Стандартный охват не показывает лишние поля');
    assert(standard.summary.includes('Стандартный'), 'Подпись охвата обновилась');

    const badRange = await page.evaluate(async () => {
      document.getElementById('gfScope').value = 'custom';
      document.getElementById('gfTcpStart').value = '5000';
      document.getElementById('gfTcpEnd').value = '100';
      await saveGameFilter();
      return document.getElementById('gfError').textContent;
    });
    evidence.gameFilterError = badRange;
    save();
    assert(badRange.includes('начало диапазона'), 'Некорректный диапазон отклоняется в интерфейсе');

    // ── 10. Закрытый <dialog> обязан быть скрыт ─────────────────────────────
    // display:flex на самом .routing-editor перебивал UA-правило
    // dialog:not([open]){display:none} и оставлял закрытый диалог на экране.
    const hidden = await page.evaluate(() => {
      const editor = document.querySelector('dialog.routing-editor');
      const picker = document.getElementById('processPicker');
      editor.close(); picker.close();
      return {
        editor: getComputedStyle(editor).display,
        picker: getComputedStyle(picker).display,
      };
    });
    evidence.closedDialogs = hidden;
    save();
    assert.equal(hidden.editor, 'none', 'Закрытый редактор правила остаётся на экране');
    assert.equal(hidden.picker, 'none', 'Закрытый диалог процессов остаётся на экране');

    evidence.pageErrors = errors;
    save();
    assert.deepEqual(errors, [], 'Исключения на странице: ' + errors.join(' | '));
    console.log('regression_3010_ui: OK');
  } catch (error) {
    failed = error;
    evidence.failure = String(error && error.message || error);
    save();
  } finally {
    await browser.close();
  }
  if (failed) { console.error(failed); process.exit(1); }
})();
