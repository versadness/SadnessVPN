(function () {
  'use strict';
  /**
   * Мост страницы с Electron-оболочкой.
   *
   * Выполняется в основном мире страницы после её загрузки и делает три вещи:
   *   1. переводит документ в режим стекла и держит CSS-переменные в актуальном виде;
   *   2. забирает кнопки окна у Python-бэкенда и отдаёт их Electron;
   *   3. добавляет в настройки раздел управления прозрачностью.
   */

  var shell = window.sadnessShell;
  if (!shell || window.__sadnessShellReady) return;
  window.__sadnessShellReady = true;

  var root = document.documentElement;
  root.classList.add('shell-glass', 'custom-frame');

  var state = { appearance: null, glass: null, platform: { win11: false, build: 0 } };
  var controls = {};

  /* ---------------- применение оформления ---------------- */

  function channels(hex) {
    var match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex || '');
    if (!match) return null;
    return [parseInt(match[1], 16), parseInt(match[2], 16), parseInt(match[3], 16)];
  }

  function mix(a, b, ratio) {
    return a.map(function (value, index) {
      return Math.round(value + (b[index] - value) * ratio);
    });
  }

  function applyAppearance(appearance, glass) {
    if (!appearance) return;
    state.appearance = appearance;
    if (glass) state.glass = glass;

    root.style.setProperty('--win-alpha', (appearance.windowAlpha / 100).toFixed(3));
    root.style.setProperty('--panel-alpha', (appearance.panelAlpha / 100).toFixed(3));
    root.style.setProperty('--veil', (appearance.veil / 100).toFixed(3));

    var accent = channels(appearance.accent);
    var deep = channels(appearance.background);
    if (accent) root.style.setProperty('--glass-accent', accent.join(', '));
    if (deep) {
      root.style.setProperty('--deep-rgb', deep.join(', '));
      // Панели — тот же фон, слегка подтянутый к акценту и к белому:
      // так карточки отделяются от подложки, не ломая выбранную гамму.
      var panel = mix(mix(deep, accent || [255, 255, 255], .12), [255, 255, 255], .07);
      root.style.setProperty('--panel-rgb', panel.join(', '));
    }

    root.classList.toggle('shell-opaque', appearance.glassMode === 'none');
    // Режим стекла нужен и странице: пользовательский фон размывается так же,
    // как Windows размывает рабочий стол за окном.
    root.classList.toggle('glass-blur', appearance.glassMode === 'blur');
    root.classList.toggle('glass-acrylic', appearance.glassMode === 'acrylic');
    syncControls();
  }

  shell.appearance.onChange(function (payload) {
    applyAppearance(payload.appearance, payload.glass);
  });

  /* ---------------- кнопки окна ---------------- */

  window.winMin = function () { shell.window.minimize(); };
  window.winMax = function () { shell.window.toggleMaximize(); };
  window.winClose = function () { shell.window.close(); };

  function markMaximized(value) {
    root.classList.toggle('is-maximized', value === true);
    if (typeof window.setWindowMaximized === 'function') {
      try { window.setWindowMaximized(value === true); } catch (error) { /* вёрстка сама разберётся */ }
    }
  }
  shell.window.onMaximized(markMaximized);
  shell.window.isMaximized().then(markMaximized);

  var titlebar = document.querySelector('.titlebar');
  if (titlebar) {
    titlebar.addEventListener('dblclick', function (event) {
      if (event.target.closest('.win-btns')) return;
      shell.window.toggleMaximize();
    });
  }

  /* ---------------- «сворачивать в трей» ---------------- */

  var trayToggle = document.querySelector('[data-sk="mintray"]');
  if (trayToggle) {
    var pushTrayPreference = function () {
      shell.window.setCloseToTray(trayToggle.classList.contains('on'));
    };
    pushTrayPreference();
    new MutationObserver(pushTrayPreference).observe(trayToggle, {
      attributes: true,
      attributeFilter: ['class'],
    });
  }

  var tbDot = document.getElementById('tbDot');
  if (tbDot) {
    new MutationObserver(function () {
      shell.tray.setState(tbDot.classList.contains('on'));
    }).observe(tbDot, { attributes: true, attributeFilter: ['class'] });
  }

  /* ---------------- раздел настроек ---------------- */

  function slider(key, title, description, min, max, unit) {
    var row = document.createElement('div');
    row.className = 'set-row glass glass-row';

    var meta = document.createElement('div');
    meta.className = 'set-meta';
    var name = document.createElement('strong');
    name.className = 'set-name';
    name.textContent = title;
    var desc = document.createElement('p');
    desc.className = 'set-desc';
    desc.textContent = description;
    meta.append(name, desc);

    var input = document.createElement('input');
    input.type = 'range';
    input.min = String(min);
    input.max = String(max);
    input.step = '1';
    input.setAttribute('aria-label', title);

    var value = document.createElement('span');
    value.className = 'glass-value';

    var paint = function () {
      var fill = ((Number(input.value) - min) / (max - min)) * 100;
      input.style.setProperty('--fill', fill.toFixed(1) + '%');
      value.textContent = input.value + unit;
    };

    // input — живой предпросмотр, change — запись на диск.
    input.addEventListener('input', function () {
      paint();
      var patch = {};
      patch[key] = Number(input.value);
      applyAppearance(Object.assign({}, state.appearance, patch), state.glass);
    });
    input.addEventListener('change', function () {
      var patch = {};
      patch[key] = Number(input.value);
      shell.appearance.set(patch).then(function (result) {
        applyAppearance(result.appearance, result.glass);
      });
    });

    row.append(meta, input, value);
    controls[key] = { input: input, paint: paint };
    return row;
  }

  var ACCENTS = ['#a87df8', '#5b8def', '#22b8cf', '#2fb884', '#f0a020', '#ef5da8', '#e0484d'];
  var BACKGROUNDS = ['#0a0816', '#0d1120', '#111214', '#07160f', '#170a1c', '#071722'];

  function paletteRow(key, title, description, presets) {
    var row = document.createElement('div');
    row.className = 'set-row glass glass-row';

    var meta = document.createElement('div');
    meta.className = 'set-meta';
    var name = document.createElement('strong');
    name.className = 'set-name';
    name.textContent = title;
    var desc = document.createElement('p');
    desc.className = 'set-desc';
    desc.textContent = description;
    meta.append(name, desc);

    var palette = document.createElement('div');
    palette.className = 'palette';

    var apply = function (value) {
      var patch = {};
      patch[key] = value;
      // Мгновенный отклик, затем запись на диск.
      applyAppearance(Object.assign({}, state.appearance, patch), state.glass);
      shell.appearance.set(patch).then(function (result) {
        applyAppearance(result.appearance, result.glass);
      });
    };

    presets.forEach(function (hex) {
      var swatch = document.createElement('button');
      swatch.type = 'button';
      swatch.className = 'swatch';
      swatch.dataset.value = hex;
      swatch.style.background = hex;
      swatch.setAttribute('aria-label', hex);
      swatch.addEventListener('click', function () { apply(hex); });
      palette.append(swatch);
    });

    var custom = document.createElement('input');
    custom.type = 'color';
    custom.className = 'swatch-custom';
    custom.setAttribute('aria-label', title + ': свой цвет');
    custom.addEventListener('input', function () {
      applyAppearance(Object.assign({}, state.appearance, makePatch(key, custom.value)), state.glass);
    });
    custom.addEventListener('change', function () { apply(custom.value); });
    palette.append(custom);

    row.append(meta, palette);
    controls[key] = { palette: palette, custom: custom };
    return row;
  }

  function makePatch(key, value) {
    var patch = {};
    patch[key] = value;
    return patch;
  }

  function modeRow() {
    var row = document.createElement('div');
    row.className = 'set-row glass glass-row';

    var meta = document.createElement('div');
    meta.className = 'set-meta';
    var name = document.createElement('strong');
    name.className = 'set-name';
    name.textContent = 'Режим стекла';
    var desc = document.createElement('p');
    desc.className = 'set-desc';
    desc.textContent = 'Окно прозрачное всегда. Размытие и акрил дополнительно размывают то, что за ним, силами Windows.';
    var hint = document.createElement('p');
    hint.className = 'glass-hint';
    meta.append(name, desc, hint);

    var modes = document.createElement('div');
    modes.className = 'glass-modes';

    [
      ['clear', 'Чистое стекло'],
      ['blur', 'Размытие'],
      ['acrylic', 'Акрил'],
      ['none', 'Без стекла'],
    ].forEach(function (entry) {
      var button = document.createElement('button');
      button.type = 'button';
      button.className = 'glass-mode';
      button.dataset.mode = entry[0];
      button.textContent = entry[1];
      button.addEventListener('click', function () {
        shell.appearance.set({ glassMode: entry[0] }).then(function (result) {
          applyAppearance(result.appearance, result.glass);
        });
      });
      modes.append(button);
    });

    row.append(meta, modes);
    controls.modes = modes;
    controls.hint = hint;
    return row;
  }

  function syncControls() {
    var appearance = state.appearance;
    if (!appearance) return;

    ['windowAlpha', 'panelAlpha', 'veil'].forEach(function (key) {
      var control = controls[key];
      if (!control) return;
      if (document.activeElement !== control.input) control.input.value = String(appearance[key]);
      control.paint();
    });

    if (controls.modes) {
      [].forEach.call(controls.modes.children, function (button) {
        button.classList.toggle('on', button.dataset.mode === appearance.glassMode);
      });
    }

    ['accent', 'background'].forEach(function (key) {
      var control = controls[key];
      if (!control) return;
      var value = (appearance[key] || '').toLowerCase();
      [].forEach.call(control.palette.querySelectorAll('.swatch'), function (swatch) {
        swatch.classList.toggle('on', swatch.dataset.value === value);
      });
      if (document.activeElement !== control.custom) control.custom.value = value;
    });

    if (controls.hint) {
      var glass = state.glass || {};
      if (appearance.glassMode === 'blur' || appearance.glassMode === 'acrylic') {
        controls.hint.textContent = glass.backend === 'SetWindowCompositionAttribute'
          ? 'Системное размытие включено. Если фон выглядит плоским — включите «Эффекты прозрачности» в параметрах Windows.'
          : 'Системное размытие не применилось' + (glass.reason ? ': ' + glass.reason : '') + '. Окно остаётся прозрачным.';
      } else {
        controls.hint.textContent = 'Прозрачность рисует сама оболочка — работает на Windows 10 и 11 независимо от системных настроек.';
      }
    }
  }

  function mountSettings() {
    var host = document.querySelector('.settings-group[data-category="appearance"]')
      || document.querySelector('#page-settings > .scroll');
    if (!host || document.querySelector('.glass-row')) return;

    host.append(
      modeRow(),
      slider('windowAlpha', 'Прозрачность окна',
        'Чем меньше, тем лучше виден рабочий стол. 0 — стекло полностью чистое.', 0, 100, '%'),
      slider('panelAlpha', 'Плотность панелей',
        'Насколько плотные карточки и боковая панель поверх прозрачного окна.', 0, 100, '%'),
      slider('veil', 'Затемнение',
        'Добавляет тень под текст. Поднимите, если на светлых обоях читается плохо.', 0, 90, '%'),
      paletteRow('accent', 'Акцент',
        'Цвет активного пункта меню, кнопок и подсветки. Последняя ячейка — свой цвет.', ACCENTS),
      paletteRow('background', 'Цвет фона',
        'База, из которой выводятся тон окна и панелей. Последняя ячейка — свой цвет.', BACKGROUNDS)
    );
    syncControls();
  }

  /* ---------------- запуск ---------------- */

  shell.appearance.get().then(function (payload) {
    state.platform = payload.platform || state.platform;
    applyAppearance(payload.appearance, payload.glass);
    mountSettings();
  });

  shell.app.version().then(function (version) {
    var badge = document.getElementById('tbVer');
    if (badge) badge.textContent = 'v' + version;
  });
})();
