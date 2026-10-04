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
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.setValue
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
    var favoritesOnly by androidx.compose.runtime.saveable.rememberSaveable { androidx.compose.runtime.mutableStateOf(false) }
    val s = ui.data.settings
    Column(modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth().padding(top = 12.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(L.t("Серверы"), fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Palette.Text)
                Text(if (s.pingMode == "tcp") L.t("Проверка: TCP (быстрая)") else L.t("Проверка: HTTP через сервер"),
                    color = Palette.Text3, fontSize = 12.sp)
            }
            if (ui.pinging) {
                CircularProgressIndicator(Modifier.size(20.dp), color = Palette.Accent, strokeWidth = 2.dp)
                Spacer(Modifier.width(14.dp))
            } else {
                IconButton(onClick = model::pingAll) { Icon(Icons.Outlined.Bolt, L.t("Проверить все серверы"), tint = Palette.Text2) }
            }
        }
        if (ui.data.groups.isNotEmpty()) {
            CardBox {
                ToggleRow(L.t("Подключаться к лучшему"), L.t("Самый быстрый сервер выбранной подписки; при сбое — следующий"), s.autoBest) { v ->
                    model.updateSettings { it.copy(autoBest = v) }
                }
            }
            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Chip(L.t("По пингу"), s.sortMode == "ping") { model.updateSettingsQuiet { it.copy(sortMode = "ping") } }
                Chip(L.t("По порядку"), s.sortMode == "order") { model.updateSettingsQuiet { it.copy(sortMode = "order") } }
                Chip("★ " + L.t("Избранные"), favoritesOnly) { favoritesOnly = !favoritesOnly }
                Chip(L.t("Скрыть нерабочие"), s.hideDead) { model.updateSettingsQuiet { it.copy(hideDead = !it.hideDead) } }
            }
        }
        if (ui.data.groups.isEmpty()) {
            Panel(Modifier.fillMaxWidth()) {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(L.t("Серверов пока нет"), color = Palette.Text, fontWeight = FontWeight.Medium)
                    Text(L.t("Серверы появятся, когда вы добавите подписку."), color = Palette.Text2, fontSize = 13.sp)
                    TextButton(onClick = onOpenSubscriptions) { Text(L.t("Перейти к подпискам"), color = Palette.Accent) }
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
                    var list = group.servers
                    if (favoritesOnly) list = list.filter { it["ui_id"].toString() in s.favorites }
                    if (s.hideDead) list = list.filter { (ui.pings[it["ui_id"].toString()] ?: 0) >= 0 }
                    if (s.sortMode == "ping") list = list.sortedBy { ui.pings[it["ui_id"].toString()]?.takeIf { p -> p >= 0 } ?: Int.MAX_VALUE }
                    items(list, key = { "s-" + group.id + it["ui_id"] }) { server ->
                        val id = server["ui_id"].toString()
                        val selected = group.id == ui.data.selectedGroup && id == ui.data.selectedServer
                        val active = (vpn.onBackup || s.autoBest) && vpn.status == com.sadness.vpn.vpn.Status.ON && server["remark"] == vpn.routeRemark
                        ServerRow(server, selected, active, ui.pings[id], favorite = id in s.favorites,
                            onFavorite = { model.toggleFavorite(id) }) { model.select(group.id, id) }
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
                Text(group.name.ifEmpty { L.t("Подписка") }, color = Palette.Text, fontWeight = FontWeight.Medium, maxLines = 1)
                Text("${group.servers.size} " + L.t("серв."), color = Palette.Text3, fontSize = 12.sp)
            }
            if (busy) CircularProgressIndicator(Modifier.size(18.dp), color = Palette.Accent, strokeWidth = 2.dp)
            else if (group.url.isNotEmpty()) IconButton(onClick = onRefresh) { Icon(Icons.Outlined.Refresh, L.t("Обновить"), tint = Palette.Text3) }
            Icon(if (open) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, null, tint = Palette.Text3)
        }
    }
}

@Composable
private fun ServerRow(server: Server, selected: Boolean, active: Boolean, ping: Int?, favorite: Boolean, onFavorite: () -> Unit, onClick: () -> Unit) {
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
            val label = when {
                protocol == "hysteria2" -> "HY2"
                protocol == "wireguard" -> if (server["awg"] != null) "AmneziaWG" else "WireGuard"
                else -> protocol.uppercase() + " · " + Failover.transport(server).uppercase()
            }
            Text(label + if (active) " · " + L.t("сейчас через него") else "", color = if (active) Palette.Warn else Palette.Text3, fontSize = 11.sp)
        }
        Text(if (favorite) "★" else "☆", color = if (favorite) Palette.Warn else Palette.Text3, fontSize = 18.sp,
            modifier = Modifier.clip(RoundedCornerShape(50)).clickable(onClick = onFavorite).padding(horizontal = 8.dp, vertical = 2.dp))
        Text(when { ping == null -> ""; ping < 0 -> "—"; else -> "$ping" }, color = pingColor(ping), fontSize = 14.sp)
    }
}
