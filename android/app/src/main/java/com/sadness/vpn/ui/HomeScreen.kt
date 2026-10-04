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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.PowerSettingsNew
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sadness.vpn.vpn.ConnState
import com.sadness.vpn.vpn.Status
import kotlinx.coroutines.delay
import java.time.LocalDate

@Composable
fun Panel(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    Box(
        modifier
            .clip(RoundedCornerShape(14.dp))
            .background(Palette.Surface)
            .border(1.dp, Palette.Border, RoundedCornerShape(14.dp))
            .padding(12.dp),
    ) { content() }
}

@Composable
fun HomeScreen(ui: UiState, vpn: ConnState, modifier: Modifier, onConnect: () -> Unit, onDisconnect: () -> Unit, onOpenServers: () -> Unit) {
    val selection = ui.data.selected()
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(vpn.status) {
        while (vpn.status == Status.ON) {
            now = System.currentTimeMillis()
            delay(1000)
        }
    }
    Column(
        modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Sadness VPN", fontSize = 20.sp, fontWeight = FontWeight.Medium, color = Palette.Text, modifier = Modifier.weight(1f))
            Text("Beta", fontSize = 12.sp, color = Palette.Accent,
                modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Palette.AccentSoft).padding(horizontal = 8.dp, vertical = 2.dp))
        }

        Panel(Modifier.fillMaxWidth().clickable(onClick = onOpenServers)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (selection == null) {
                    Text("Сервер не выбран — добавьте подписку", color = Palette.Text2, modifier = Modifier.weight(1f))
                } else {
                    val (group, server) = selection
                    val remark = server["remark"].toString()
                    Text(flagOf(remark), fontSize = 26.sp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(cleanRemark(remark), color = Palette.Text, fontWeight = FontWeight.Medium, maxLines = 1)
                        val ping = ui.pings[server["ui_id"].toString()]
                        val pingText = when { ping == null -> ""; ping < 0 -> " · не отвечает"; else -> " · $ping мс" }
                        Text(group.name + pingText, color = Palette.Text3, fontSize = 13.sp, maxLines = 1)
                    }
                }
                Icon(Icons.Outlined.ChevronRight, null, tint = Palette.Text3)
            }
        }

        Box(Modifier.fillMaxWidth().padding(vertical = 18.dp), contentAlignment = Alignment.Center) {
            PowerButton(vpn.status, onClick = {
                when (vpn.status) {
                    Status.OFF -> onConnect()
                    Status.ON, Status.CONNECTING -> onDisconnect()
                    Status.STOPPING -> Unit
                }
            })
        }

        val on = vpn.status == Status.ON
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.Bottom) {
            Text(if (on) formatSpeed(vpn.down) else "—", fontSize = 30.sp, fontWeight = FontWeight.Medium, color = Palette.Text)
            Text("  Мбит/с", fontSize = 14.sp, color = Palette.Text3, modifier = Modifier.padding(bottom = 5.dp))
        }
        if (on && vpn.onBackup) {
            Text("Выбранный сервер не отвечает — трафик идёт через «${cleanRemark(vpn.routeRemark)}»",
                color = Palette.Warn, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp))
        }

        val today = ui.data.todayBytes.takeIf { ui.data.todayDate == LocalDate.now().toString() } ?: 0
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Tile("Отдача", if (on) "${formatSpeed(vpn.up)} Мбит/с" else "—", Modifier.weight(1f))
            Tile("Сессия", if (on) formatDuration(now - vpn.startedAt) else "—", Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Tile("Сегодня", formatBytes(today + if (on) vpn.sessionUp + vpn.sessionDown else 0), Modifier.weight(1f))
            val backup = when {
                !on -> "—" to Palette.Text
                vpn.onBackup -> "Используется" to Palette.Warn
                vpn.hasBackup -> "Готов" to Palette.Accent
                else -> "Нет" to Palette.Text3
            }
            Tile("Резерв", backup.first, Modifier.weight(1f), backup.second)
        }
    }
}

@Composable
private fun PowerButton(status: Status, onClick: () -> Unit) {
    val color = when (status) {
        Status.ON -> Palette.Accent
        Status.CONNECTING, Status.STOPPING -> Palette.Warn
        Status.OFF -> Palette.Text3
    }
    val label = when (status) {
        Status.ON -> "Подключено"
        Status.CONNECTING -> "Подключение…"
        Status.STOPPING -> "Отключение…"
        Status.OFF -> "Подключить"
    }
    Box(
        Modifier.size(168.dp).clip(CircleShape)
            .background(color.copy(alpha = 0.08f))
            .border(3.dp, color, CircleShape)
            .clickable(onClick = onClick),
        contentAlignment = Alignment.Center,
    ) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            if (status == Status.CONNECTING || status == Status.STOPPING) {
                CircularProgressIndicator(color = color, strokeWidth = 3.dp, modifier = Modifier.size(44.dp))
            } else {
                Icon(Icons.Outlined.PowerSettingsNew, contentDescription = label, tint = color, modifier = Modifier.size(52.dp))
            }
            Spacer(Modifier.size(6.dp))
            Text(label, color = color, fontSize = 13.sp)
        }
    }
}

@Composable
private fun Tile(label: String, value: String, modifier: Modifier, color: Color = Palette.Text) {
    Panel(modifier) {
        Column {
            Text(label, color = Palette.Text3, fontSize = 12.sp)
            Text(value, color = color, fontSize = 15.sp, maxLines = 1)
        }
    }
}
