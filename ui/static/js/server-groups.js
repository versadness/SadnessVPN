// Display-only grouping. Server IDs and original group indexes are preserved.
const serverGroupView = new Map();
function renderServerGroups(groups, rows, kind, filterKey, renderRow, searching) {
  const byGroup = new Map();
  for (const row of rows) {
    if (!byGroup.has(row.g)) byGroup.set(row.g, []);
    byGroup.get(row.g).push(row);
  }
  const selected = kind === 'wg' ? ST.selWgGroup : ST.selGroup;
  return groups.map((group, index) => {
    const items = byGroup.get(group.id) || [];
    if (!items.length) return '';
    const key = JSON.stringify([kind, group.id]);
    let state = serverGroupView.get(key);
    if (!state) { state = {collapsed:false, limit:100, filterKey}; serverGroupView.set(key, state); }
    if (state.filterKey !== filterKey) { state.filterKey = filterKey; state.limit = 100; if (searching) state.collapsed = false; }
    const collapsed = state.collapsed;
    const title = ['Подписка','WG Подписка'].includes(group.name) && group.subscription?.provider_name ? group.subscription.provider_name : group.name || (group.url ? 'Подписка' : 'Добавлены вручную');
    const count = searching ? `${items.length} из ${(group.servers || []).length}` : String(items.length);
    const target = `server-group-${kind}-${index}`;
    return `<section class="server-subgroup" data-server-group="${esc(group.id)}">
      <button type="button" class="server-subgroup-head" data-group-action="toggle" data-group-id="${esc(group.id)}" data-group-kind="${kind}" aria-expanded="${!collapsed}" aria-controls="${target}">
        <span class="server-subgroup-mark tone-${index % 3}" aria-hidden="true">${group.url ? esc(Array.from(title)[0] || 'S') : '+'}</span>
        <span class="server-subgroup-title"><strong>${esc(title)}</strong><span>${group.url ? 'Подписка' : 'Добавлены вручную'} · серверов: ${count}</span></span>
        ${group.id === selected ? '<span class="server-subgroup-selected">Выбран сервер</span>' : ''}
        <svg class="server-subgroup-chevron ${collapsed ? 'collapsed' : ''}" viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>
      </button>
      <div class="server-subgroup-rows" id="${target}" ${collapsed ? 'hidden' : ''}>
        ${collapsed ? '' : items.slice(0,state.limit).map(renderRow).join('')}
        ${!collapsed && items.length > state.limit ? `<button type="button" class="btn secondary load-more" data-group-action="more" data-group-id="${esc(group.id)}" data-group-kind="${kind}">Показать ещё · ${state.limit} из ${items.length}</button>` : ''}
      </div>
    </section>`;
  }).join('');
}
document.addEventListener('click', event => {
  const button = event.target.closest('[data-group-action]');
  if (!button) return;
  const {groupKind:kind, groupId:id, groupAction:action} = button.dataset;
  const state = serverGroupView.get(JSON.stringify([kind,id]));
  if (!state) return;
  if (action === 'more') state.limit += 100;
  else state.collapsed = !state.collapsed;
  kind === 'wg' ? renderWg() : renderServers();
  const next = [...document.querySelectorAll('[data-group-action]')].find(el => el.dataset.groupKind === kind && el.dataset.groupId === id && el.dataset.groupAction === action)
    || [...document.querySelectorAll('[data-group-action="toggle"]')].find(el => el.dataset.groupKind === kind && el.dataset.groupId === id);
  next?.focus({preventScroll:true});
});
