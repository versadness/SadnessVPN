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
fun HomeScreen(ui: UiState, vpn: ConnState, model: AppModel, modifier: Modifier, batteryRestricted: Boolean,
               onFixBattery: () -> Unit, onConnect: () -> Unit, onOpenServers: () -> Unit) {
    val selection = ui.data.selected()
    val s = ui.data.settings
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(vpn.status) {
        while (vpn.status == Status.ON) {
            now = System.currentTimeMillis()
            delay(1000)
        }
    }
    val on = vpn.status == Status.ON
    Box(modifier.fillMaxSize()) {
    if (s.aurora != "off") Aurora(s.aurora, vpn.status, vpn.up + vpn.down, Modifier.matchParentSize())
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Sadness VPN", fontSize = 20.sp, fontWeight = FontWeight.Medium, color = Palette.Text, modifier = Modifier.weight(1f))
            Text("Beta", fontSize = 12.sp, color = Palette.Accent,
                modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(Palette.AccentSoft).padding(horizontal = 8.dp, vertical = 2.dp))
        }

        if (batteryRestricted && !s.batteryDismissed) {
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Palette.Warn.copy(alpha = 0.12f))
                .border(1.dp, Palette.Warn.copy(alpha = 0.4f), RoundedCornerShape(14.dp)).padding(12.dp)) {
                Text(L.t("Телефон может отключать VPN в фоне"), color = Palette.Text, fontWeight = FontWeight.Medium)
                Text(L.t("Разрешите работу без ограничений батареи, иначе система может закрыть VPN при выключенном экране."),
                    color = Palette.Text2, fontSize = 12.sp, modifier = Modifier.padding(top = 3.dp, bottom = 8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SmallButton(L.t("Исправить"), Palette.Warn, Palette.Bg, Modifier.weight(1f), onFixBattery)
                    SmallButton(L.t("Позже"), Palette.Surface2, Palette.Text, Modifier.weight(1f)) {
                        model.updateSettingsQuiet { it.copy(batteryDismissed = true) }
                    }
                }
            }
        }

        Panel(Modifier.fillMaxWidth().clickableTv(onOpenServers)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                if (selection == null) {
                    Text(L.t("Сервер не выбран — добавьте подписку"), color = Palette.Text2, modifier = Modifier.weight(1f))
                } else if (s.autoBest) {
                    Text("⚡", fontSize = 24.sp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(L.t("Лучший сервер"), color = Palette.Text, fontWeight = FontWeight.Medium)
                        Text(if (on && vpn.routeRemark.isNotEmpty()) L.t("Сейчас: ") + vpn.routeRemark else selection.first.name,
                            color = Palette.Text3, fontSize = 13.sp, maxLines = 1)
                    }
                } else {
                    val (group, server) = selection
                    val remark = server["remark"].toString()
                    Text(flagOf(remark), fontSize = 26.sp)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(cleanRemark(remark), color = Palette.Text, fontWeight = FontWeight.Medium, maxLines = 1)
                        val ping = ui.pings[server["ui_id"].toString()]
                        val pingText = when { ping == null -> ""; ping < 0 -> " · " + L.t("не отвечает"); else -> " · $ping " + L.t("мс") }
                        Text(group.name + pingText, color = Palette.Text3, fontSize = 13.sp, maxLines = 1)
                    }
                }
                Icon(Icons.Outlined.ChevronRight, null, tint = Palette.Text3)
            }
        }

        Box(Modifier.fillMaxWidth().padding(vertical = 10.dp), contentAlignment = Alignment.Center) {
            PowerButton(vpn.status, onClick = {
                when (vpn.status) {
                    Status.OFF -> onConnect()
                    Status.ON, Status.CONNECTING -> model.disconnect()
                    Status.STOPPING -> Unit
                }
            })
        }

        if (vpn.status == Status.OFF && vpn.error.isNotEmpty()) {
            Panel(Modifier.fillMaxWidth()) { Text(vpn.error, color = Palette.Danger, fontSize = 13.sp) }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.Bottom) {
            Text(if (on) formatSpeed(vpn.down) else "—", fontSize = 30.sp, fontWeight = FontWeight.Medium, color = Palette.Text)
            Text("  " + L.t("Мбит/с"), fontSize = 14.sp, color = Palette.Text3, modifier = Modifier.padding(bottom = 5.dp))
        }
        if (on && vpn.onBackup && !s.autoBest) {
            Text(L.t("Выбранный сервер не отвечает — трафик идёт через ") + "«${cleanRemark(vpn.routeRemark)}»",
                color = Palette.Warn, fontSize = 13.sp, modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp))
        }

        val today = ui.data.todayBytes.takeIf { ui.data.todayDate == LocalDate.now().toString() } ?: 0
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Tile(L.t("Отдача"), if (on) "${formatSpeed(vpn.up)} " + L.t("Мбит/с") else "—", Modifier.weight(1f))
            Tile(L.t("Сессия"), if (on) formatDuration(now - vpn.startedAt) else "—", Modifier.weight(1f))
        }
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Tile(L.t("Сегодня"), formatBytes(today + if (on) vpn.sessionUp + vpn.sessionDown else 0), Modifier.weight(1f))
            val backup = when {
                !on -> "—" to Palette.Text
                vpn.onBackup && !s.autoBest -> L.t("Используется") to Palette.Warn
                vpn.hasBackup -> L.t("Готов") to Palette.Accent
                else -> L.t("Нет") to Palette.Text3
            }
            Tile(L.t("Резерв"), backup.first, Modifier.weight(1f), backup.second)
        }

        CheckCard(ui, on, model)
    }
    }
}

@Composable
private fun CheckCard(ui: UiState, on: Boolean, model: AppModel) {
    Panel(Modifier.fillMaxWidth()) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(L.t("Проверка соединения"), color = Palette.Text, fontWeight = FontWeight.Medium, modifier = Modifier.weight(1f))
                if (ui.checking) CircularProgressIndicator(Modifier.size(18.dp), color = Palette.Accent, strokeWidth = 2.dp)
                else Text(L.t("Проверить"), color = if (on) Palette.Accent else Palette.Text3, fontSize = 14.sp,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).clickableTv(model::checkConnection).padding(horizontal = 8.dp, vertical = 4.dp))
            }
            val c = ui.check
            if (c == null) {
                Text(if (on) L.t("Страна выхода, YouTube, Telegram и утечка DNS — одной кнопкой.") else L.t("Доступно при подключённом VPN."),
                    color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
            } else {
                CheckRow(L.t("Внешний IP"), when {
                    c.country == null -> null
                    c.country.isEmpty() -> L.t("не удалось") to Palette.Danger
                    else -> (flagFromCode(c.countryCode) + " " + c.country) to Palette.Text
                })
                CheckRow("YouTube", c.youtube?.let { if (it > 0) "✓ $it " + L.t("мс") to Palette.Accent else "✗ " + L.t("недоступен") to Palette.Danger })
                CheckRow("Telegram", c.telegram?.let { if (it > 0) "✓ $it " + L.t("мс") to Palette.Accent else "✗ " + L.t("недоступен") to Palette.Danger })
                CheckRow(L.t("Утечка DNS"), when {
                    c.dnsCountries == null -> null
                    c.dnsLeak == true -> L.t("возможна: ") + c.dnsCountries.joinToString() to Palette.Danger
                    c.dnsCountries.isEmpty() -> L.t("не удалось проверить") to Palette.Text3
                    else -> L.t("нет") + " · " + c.dnsCountries.joinToString() to Palette.Accent
                })
            }
        }
    }
}

@Composable
private fun CheckRow(label: String, value: Pair<String, Color>?) {
    Row(Modifier.fillMaxWidth().padding(top = 6.dp)) {
        Text(label, color = Palette.Text3, fontSize = 13.sp, modifier = Modifier.weight(0.4f), maxLines = 1)
        Text(value?.first ?: "…", color = value?.second ?: Palette.Text3, fontSize = 13.sp, maxLines = 3,
            textAlign = androidx.compose.ui.text.style.TextAlign.End, modifier = Modifier.weight(0.6f))
    }
}

fun flagFromCode(code: String?): String {
    if (code == null || code.length != 2) return "🌐"
    return code.uppercase().map { String(Character.toChars(0x1F1E6 + (it - 'A'))) }.joinToString("")
}

@Composable
fun SmallButton(text: String, background: Color, color: Color, modifier: Modifier, onClick: () -> Unit) {
    Text(text, color = color, fontSize = 13.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center,
        modifier = modifier.clip(RoundedCornerShape(10.dp)).background(background).clickableTv(onClick).padding(vertical = 9.dp))
}

@Composable
private fun PowerButton(status: Status, onClick: () -> Unit) {
    val color = when (status) {
        Status.ON -> Palette.Accent
        Status.CONNECTING, Status.STOPPING -> Palette.Warn
        Status.OFF -> Palette.Text3
    }
    val label = when (status) {
        Status.ON -> L.t("Подключено")
        Status.CONNECTING -> L.t("Подключение…")
        Status.STOPPING -> L.t("Отключение…")
        Status.OFF -> L.t("Подключить")
    }
    Box(
        Modifier.size(160.dp).clip(CircleShape)
            .background(color.copy(alpha = 0.08f))
            .border(3.dp, color, CircleShape)
            .clickableTv(onClick),
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
