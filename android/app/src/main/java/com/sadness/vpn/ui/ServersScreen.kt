package com.sadness.vpn.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.outlined.Bolt
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.remember
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
fun ServersScreen(ui: UiState, vpn: ConnState, model: AppModel, modifier: Modifier, onOpenSubscriptions: () -> Unit) {
    val expanded = remember { mutableStateMapOf<String, Boolean>() }
    Column(modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Серверы", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Palette.Text)
                Text(if (ui.data.settings.pingMode == "tcp") "Проверка: TCP (быстрая)" else "Проверка: HTTP через сервер",
                    color = Palette.Text3, fontSize = 12.sp)
            }
            if (ui.pinging) {
                CircularProgressIndicator(Modifier.size(20.dp), color = Palette.Accent, strokeWidth = 2.dp)
                Spacer(Modifier.width(14.dp))
            } else {
                IconButton(onClick = model::pingAll) { Icon(Icons.Outlined.Bolt, "Проверить все серверы", tint = Palette.Text2) }
            }
        }
        if (ui.data.groups.isEmpty()) {
            Panel(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("Серверов пока нет", color = Palette.Text, fontWeight = FontWeight.Medium)
                    Text("Серверы появятся, когда вы добавите подписку.", color = Palette.Text2, fontSize = 13.sp)
                    TextButton(onClick = onOpenSubscriptions) { Text("Перейти к подпискам", color = Palette.Accent) }
                }
            }
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            for (group in ui.data.groups) {
                val open = expanded[group.id] ?: (group.id == ui.data.selectedGroup || ui.data.groups.size == 1)
                item(key = "g-" + group.id) {
                    GroupHeader(group, busy = group.id in ui.busyGroups, open = open,
                        onToggle = { expanded[group.id] = !open }, onRefresh = { model.refresh(group.id) })
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
            item { Spacer(Modifier.height(96.dp)) }
        }
    }
}

@Composable
private fun GroupHeader(group: Group, busy: Boolean, open: Boolean, onToggle: () -> Unit, onRefresh: () -> Unit) {
    Panel(Modifier.fillMaxWidth().clickable(onClick = onToggle)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(group.name.ifEmpty { "Подписка" }, color = Palette.Text, fontWeight = FontWeight.Medium, maxLines = 1)
                Text("${group.servers.size} серв.", color = Palette.Text3, fontSize = 12.sp)
            }
            if (busy) CircularProgressIndicator(Modifier.size(18.dp), color = Palette.Accent, strokeWidth = 2.dp)
            else IconButton(onClick = onRefresh) { Icon(Icons.Outlined.Refresh, "Обновить", tint = Palette.Text3) }
            Icon(if (open) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, null, tint = Palette.Text3)
        }
    }
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
            Text(label + if (active) " · сейчас через него" else "", color = if (active) Palette.Warn else Palette.Text3, fontSize = 11.sp)
        }
        Text(when { ping == null -> ""; ping < 0 -> "—"; else -> "$ping" }, color = pingColor(ping), fontSize = 14.sp)
    }
}
