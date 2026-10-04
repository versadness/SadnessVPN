package com.sadness.vpn.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sadness.vpn.core.Failover
import com.sadness.vpn.core.Server
import com.sadness.vpn.data.Group
import com.sadness.vpn.vpn.ConnState

@Composable
fun ServersScreen(ui: UiState, vpn: ConnState, model: AppModel, modifier: Modifier) {
    var adding by remember { mutableStateOf(false) }
    val expanded = remember { mutableStateMapOf<String, Boolean>() }
    Column(modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth().padding(vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Серверы", fontSize = 20.sp, fontWeight = FontWeight.Medium, color = Palette.Text, modifier = Modifier.weight(1f))
            if (ui.pinging) {
                CircularProgressIndicator(Modifier.size(20.dp), color = Palette.Accent, strokeWidth = 2.dp)
                Spacer(Modifier.width(14.dp))
            } else {
                IconButton(onClick = model::pingAll) { Icon(Icons.Outlined.Bolt, "Проверить все серверы", tint = Palette.Text2) }
            }
            IconButton(onClick = { adding = true }) { Icon(Icons.Outlined.Add, "Добавить подписку", tint = Palette.Text2) }
        }
        if (ui.data.groups.isEmpty()) {
            Panel(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Добавьте первую подписку", color = Palette.Text, fontWeight = FontWeight.Medium)
                    Text("Нужна ссылка подписки от провайдера VPN — та же, что для десктопного клиента.", color = Palette.Text2, fontSize = 13.sp)
                    TextButton(onClick = { adding = true }) { Text("Добавить подписку", color = Palette.Accent) }
                }
            }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            for (group in ui.data.groups) {
                val open = expanded[group.id] ?: (group.id == ui.data.selectedGroup || ui.data.groups.size == 1)
                item(key = "g-" + group.id) {
                    GroupHeader(group, busy = group.id in ui.busyGroups, open = open,
                        onToggle = { expanded[group.id] = !open },
                        onRefresh = { model.refresh(group.id) },
                        onRename = { model.renameGroup(group.id, it) },
                        onDelete = { model.deleteGroup(group.id) })
                }
                if (open) {
                    items(group.servers, key = { "s-" + group.id + it["ui_id"] }) { server ->
                        val id = server["ui_id"].toString()
                        val selected = group.id == ui.data.selectedGroup && id == ui.data.selectedServer
                        val active = vpn.onBackup && server["remark"] == vpn.routeRemark
                        ServerRow(server, selected, active, ui.pings[id]) { model.select(group.id, id) }
                    }
                }
            }
            item { Spacer(Modifier.height(12.dp)) }
        }
    }
    if (adding) AddDialog(onDismiss = { adding = false }, onAdd = { url, name -> adding = false; model.addSubscription(url, name) })
}

@Composable
private fun GroupHeader(group: Group, busy: Boolean, open: Boolean, onToggle: () -> Unit, onRefresh: () -> Unit,
                        onRename: (String) -> Unit, onDelete: () -> Unit) {
    var menu by remember { mutableStateOf(false) }
    var renaming by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    Panel(Modifier.fillMaxWidth().clickable(onClick = onToggle)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(group.name.ifEmpty { "Подписка" }, color = Palette.Text, fontWeight = FontWeight.Medium, maxLines = 1)
                    Text(groupSubtitle(group), color = Palette.Text3, fontSize = 12.sp, maxLines = 1)
                }
                if (busy) CircularProgressIndicator(Modifier.size(18.dp), color = Palette.Accent, strokeWidth = 2.dp)
                else IconButton(onClick = onRefresh) { Icon(Icons.Outlined.Refresh, "Обновить", tint = Palette.Text3) }
                Box {
                    IconButton(onClick = { menu = true }) { Icon(Icons.Outlined.MoreVert, "Меню подписки", tint = Palette.Text3) }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Переименовать") }, onClick = { menu = false; renaming = true })
                        DropdownMenuItem(text = { Text("Удалить", color = Palette.Danger) }, onClick = { menu = false; deleting = true })
                    }
                }
                Icon(if (open) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, null, tint = Palette.Text3)
            }
            val total = (group.meta["total"] as? Number)?.toLong() ?: 0
            if (total > 0) {
                val used = ((group.meta["upload"] as? Number)?.toLong() ?: 0) + ((group.meta["download"] as? Number)?.toLong() ?: 0)
                Spacer(Modifier.height(8.dp))
                LinearProgressIndicator(progress = { (used.toFloat() / total).coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)),
                    color = Palette.Accent, trackColor = Palette.Track, drawStopIndicator = {})
            }
            if (group.error.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text(group.error, color = Palette.Danger, fontSize = 12.sp)
            }
        }
    }
    if (renaming) {
        var name by remember { mutableStateOf(group.name) }
        AlertDialog(onDismissRequest = { renaming = false },
            title = { Text("Название подписки") },
            text = { OutlinedTextField(name, { name = it }, singleLine = true) },
            confirmButton = { TextButton(onClick = { renaming = false; onRename(name) }) { Text("Сохранить") } },
            dismissButton = { TextButton(onClick = { renaming = false }) { Text("Отмена") } })
    }
    if (deleting) {
        AlertDialog(onDismissRequest = { deleting = false },
            title = { Text("Удалить подписку?") },
            text = { Text("«${group.name}» и её серверы будут удалены с телефона. У провайдера подписка останется.") },
            confirmButton = { TextButton(onClick = { deleting = false; onDelete() }) { Text("Удалить", color = Palette.Danger) } },
            dismissButton = { TextButton(onClick = { deleting = false }) { Text("Отмена") } })
    }
}

private fun groupSubtitle(group: Group): String {
    val parts = mutableListOf("${group.servers.size} серв.")
    (group.meta["updated_at"] as? Number)?.toLong()?.let { at ->
        val minutes = (System.currentTimeMillis() / 1000 - at) / 60
        parts += when {
            minutes < 1 -> "обновлено только что"
            minutes < 60 -> "обновлено $minutes мин назад"
            minutes < 60 * 24 -> "обновлено ${minutes / 60} ч назад"
            else -> "обновлено ${minutes / 60 / 24} дн назад"
        }
    }
    val total = (group.meta["total"] as? Number)?.toLong() ?: 0
    if (total > 0) {
        val used = ((group.meta["upload"] as? Number)?.toLong() ?: 0) + ((group.meta["download"] as? Number)?.toLong() ?: 0)
        parts += "${formatBytes(used)} из ${formatBytes(total)}"
    }
    return parts.joinToString(" · ")
}

@Composable
private fun ServerRow(server: Server, selected: Boolean, active: Boolean, ping: Int?, onClick: () -> Unit) {
    val remark = server["remark"].toString()
    val shape = RoundedCornerShape(12.dp)
    Row(
        Modifier.fillMaxWidth().clip(shape)
            .then(if (selected) Modifier.background(Palette.AccentSoft).border(1.dp, Palette.Accent.copy(alpha = 0.35f), shape) else Modifier)
            .clickable(onClick = onClick).padding(horizontal = 12.dp, vertical = 11.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(flagOf(remark), fontSize = 18.sp)
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Text(cleanRemark(remark), color = Palette.Text, maxLines = 1)
            val protocol = server["protocol"]?.toString().orEmpty().ifEmpty { "vless" }
            val label = if (protocol == "hysteria2") "HY2" else protocol.uppercase() + " · " + Failover.transport(server).uppercase()
            Text(label +
                if (active) " · сейчас через него" else "", color = if (active) Palette.Warn else Palette.Text3, fontSize = 11.sp)
        }
        Text(when { ping == null -> ""; ping < 0 -> "—"; else -> "$ping" }, color = pingColor(ping), fontSize = 14.sp)
    }
}

@Composable
private fun AddDialog(onDismiss: () -> Unit, onAdd: (String, String) -> Unit) {
    var url by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Новая подписка") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(url, { url = it }, label = { Text("Ссылка подписки") }, singleLine = true,
                    placeholder = { Text("https://…") })
                OutlinedTextField(name, { name = it }, label = { Text("Название (необязательно)") }, singleLine = true)
            }
        },
        confirmButton = { TextButton(onClick = { onAdd(url, name) }, enabled = url.isNotBlank()) { Text("Добавить") } },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Отмена") } },
    )
}
