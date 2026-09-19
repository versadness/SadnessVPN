/* Subscription UI only receives display metadata, never renders subscription URLs. */
let subscriptionRequestPending = false;
let subscriptionEditTarget = null;

function subscriptionGroups() {
  return [...ST.groups.map(g => ({...g, kind:'vless'})), ...ST.wgGroups.map(g => ({...g, kind:'wg'}))].filter(g => g.url);
}
function subscriptionDate(epoch) {
  const date = new Date(Number(epoch) * 1000);
  return epoch > 0 && Number.isFinite(date.getTime()) ? date.toLocaleDateString('ru-RU') : 'Не указан';
}
function renderSubscriptions() {
  const list = document.getElementById('subscriptionList');
  if (!list) return;
  const groups = subscriptionGroups(), busy = !!ST.subscriptionBusy || subscriptionRequestPending;
  const disabled = busy || !ST.backendOnline || ST.status !== 'off';
  document.getElementById('subscriptionCount').textContent = `Подписок: ${groups.length}`;
  document.getElementById('subscriptionNotice').textContent = busy ? 'Загружаем подписку… Уже сохранённые серверы остаются на месте.' : !ST.backendOnline ? 'Нет связи с приложением.' : ST.status !== 'off' ? 'Чтобы изменить подписки, сначала отключите VPN.' : 'Срок и трафик сообщает провайдер. Если этих данных нет, мы не подставляем выдуманные значения.';
  document.querySelectorAll('#subscriptionImport input, #subscriptionImport select, #subscriptionImport button').forEach(el => el.disabled = disabled);
  list.innerHTML = groups.map(g => {
    const m = g.subscription || {}, expired = m.expire > 0 && m.expire * 1000 <= Date.now();
    const knownUsage = Number.isFinite(m.download) && Number.isFinite(m.upload);
    const used = knownUsage ? m.download + m.upload : 0;
    const percent = knownUsage && m.total > 0 ? Math.min(100, Math.max(0, used / m.total * 100)) : null;
    const state = m.error ? 'Ошибка обновления' : expired ? 'Срок истёк' : m.updated_at ? 'Обновлена' : 'Нужно обновить';
    return `<article class="subscription-card glass">
      <div class="subscription-card-head"><span class="subscription-mark" aria-hidden="true">${esc(Array.from(g.name || 'S')[0])}</span><div class="subscription-heading"><h2>${esc(g.name)}</h2><p>${esc(m.provider_name && m.provider_name !== g.name ? m.provider_name : g.kind === 'wg' ? 'WireGuard / AmneziaWG' : 'VPN-подписка')}</p></div><span class="subscription-status ${m.error || expired ? 'warn' : ''}">${state}</span></div>
      <div class="subscription-facts"><div><span>Срок действия</span><strong>${m.expire > 0 ? 'До ' + subscriptionDate(m.expire) : 'Не указан провайдером'}</strong></div><div><span>Серверов</span><strong>${Number(g.count ?? g.servers?.length ?? 0)}</strong></div><div><span>Последнее обновление</span><strong>${m.updated_at ? subscriptionDate(m.updated_at) : 'Ещё не обновлялась'}</strong></div></div>
      <div class="subscription-usage"><span>Трафик подписки</span><strong>${knownUsage ? fmtBytes(used) + (m.total > 0 ? ' / ' + fmtBytes(m.total) : ' · лимит не указан') : 'Не указан провайдером'}</strong>${percent !== null ? `<progress max="100" value="${percent}" aria-label="Использованный трафик подписки"></progress>` : ''}</div>
      ${m.error ? `<p class="subscription-error" role="status">${esc(m.error)}</p>` : ''}
      <div class="subscription-actions"><button class="btn btn-primary" data-sub-action="refresh" data-id="${esc(g.id)}" data-kind="${g.kind}" ${disabled ? 'disabled' : ''}>Обновить</button><button class="btn" data-sub-action="rename" data-id="${esc(g.id)}" data-kind="${g.kind}" ${disabled ? 'disabled' : ''}>Переименовать</button><button class="btn subscription-delete" data-sub-action="delete" data-id="${esc(g.id)}" data-kind="${g.kind}" ${disabled ? 'disabled' : ''}>Удалить</button></div>
    </article>`;
  }).join('') || '<div class="empty"><b>Подписки появятся здесь</b><p>Вставьте ссылку из бота или личного кабинета VPN-сервиса выше.</p></div>';
}
async function subscriptionCall(kind, action, body) {
  subscriptionRequestPending = true;
  renderSubscriptions();
  const base = kind === 'wg' ? '/api/wg' : '/api';
  const response = await api(base + (action === 'import' ? '/servers/import' : '/groups/' + action), body);
  subscriptionRequestPending = false;
  renderSubscriptions();
  if (!response.ok) toast(response.error || 'Не удалось выполнить действие', 'err');
  return response;
}
document.getElementById('subscriptionImport').addEventListener('submit', async event => {
  event.preventDefault();
  if (ST.subscriptionBusy || subscriptionRequestPending) return;
  const form = event.currentTarget, data = new FormData(form);
  const response = await subscriptionCall(data.get('protocol'), 'import', {url:String(data.get('url')).trim(), name:String(data.get('name')).trim()});
  if (response.ok) { form.reset(); toast('Подписка загружается…'); }
});
document.getElementById('subscriptionList').addEventListener('click', async event => {
  const button = event.target.closest('[data-sub-action]');
  if (!button || button.disabled) return;
  const group = subscriptionGroups().find(g => g.id === button.dataset.id && g.kind === button.dataset.kind);
  if (!group) return;
  if (button.dataset.subAction === 'refresh') {
    await subscriptionCall(group.kind, 'refresh', {id:group.id});
    return;
  }
  subscriptionEditTarget = {group, action:button.dataset.subAction};
  const deleting = subscriptionEditTarget.action === 'delete';
  document.getElementById('subscriptionDialogTitle').textContent = deleting ? 'Удалить подписку?' : 'Название подписки';
  document.getElementById('subscriptionDialogDescription').textContent = deleting ? `«${group.name}» и её серверы будут удалены только из приложения. Покупка у провайдера не отменяется.` : 'Это имя будет отображаться только в вашем приложении.';
  document.getElementById('subscriptionNameLabel').hidden = deleting;
  const input = document.getElementById('subscriptionName');
  input.value = group.name;
  input.required = !deleting;
  document.getElementById('subscriptionConfirm').textContent = deleting ? 'Удалить' : 'Сохранить';
  document.getElementById('subscriptionDialog').showModal();
  if (!deleting) { input.focus(); input.select(); }
});
document.getElementById('subscriptionCancel').addEventListener('click', () => document.getElementById('subscriptionDialog').close());
document.getElementById('subscriptionEdit').addEventListener('submit', async event => {
  event.preventDefault();
  if (!subscriptionEditTarget || subscriptionRequestPending) return;
  const {group, action} = subscriptionEditTarget, name = document.getElementById('subscriptionName').value.trim();
  if (action === 'rename' && !name) { toast('Введите название', 'err'); return; }
  const response = await subscriptionCall(group.kind, action, {id:group.id, ...(action === 'rename' ? {name} : {})});
  if (response.ok) { document.getElementById('subscriptionDialog').close(); toast(action === 'delete' ? 'Подписка удалена из приложения' : 'Название сохранено', 'ok'); }
});
renderSubscriptions();
