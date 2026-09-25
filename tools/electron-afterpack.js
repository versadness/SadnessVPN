'use strict';
/**
 * Чистка пакета Electron после сборки.
 *
 * Интерфейс только русский, а electron-builder кладёт рядом полсотни .pak
 * с локализациями Chromium — это 40 МБ в установщике, которые никогда не
 * читаются. LICENSES.chromium.html при этом НЕ трогаем: он обязателен для
 * распространения Chromium. SwiftShader (vk_swiftshader.dll) тоже остаётся —
 * это программный рендер для машин без рабочих драйверов GPU.
 */
const fs = require('fs');
const path = require('path');

const KEEP_LOCALES = new Set(['ru.pak', 'en-US.pak']);

exports.default = async function afterPack(context) {
  const locales = path.join(context.appOutDir, 'locales');
  let removed = 0;
  let freed = 0;
  let entries;
  try {
    entries = fs.readdirSync(locales);
  } catch (error) {
    console.log('afterPack: каталог locales не найден, пропускаю');
    return;
  }
  for (const entry of entries) {
    if (!entry.endsWith('.pak') || KEEP_LOCALES.has(entry)) continue;
    const file = path.join(locales, entry);
    freed += fs.statSync(file).size;
    fs.rmSync(file);
    removed += 1;
  }
  const kept = entries.filter((entry) => KEEP_LOCALES.has(entry));
  if (!kept.length) throw new Error('afterPack: не осталось ни одной локали Chromium');
  console.log(`afterPack: удалено ${removed} локалей (${(freed / 1048576).toFixed(1)} МБ), оставлены ${kept.join(', ')}`);
};
