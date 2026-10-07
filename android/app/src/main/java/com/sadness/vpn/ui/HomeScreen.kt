package com.sadness.vpn.ui

import androidx.compose.foundation.background
import androidx.compose.runtime.collectAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.foundation.layout.height
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
    // Раскладка как в макете «Жидкий градиент»: живой фон на весь экран,
    // поверх — полупрозрачные «стеклянные» элементы с белым текстом.
    val white = Color.White
    val glass = Modifier.clip(RoundedCornerShape(16.dp)).background(Color.Black.copy(alpha = 0.18f))
        .border(1.dp, white.copy(alpha = 0.08f), RoundedCornerShape(16.dp))
    // Живой фон рисует MainActivity под всеми вкладками; без него — тёмная заливка.
    Box(modifier.fillMaxSize().background(if (s.aurora != "off") Color.Transparent else Color(0xFF05060A))) {
    Column(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(bottom = 76.dp)
        .padding(start = 16.dp, end = 16.dp, top = 14.dp, bottom = 10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Sadness VPN", fontSize = 17.sp, fontWeight = FontWeight.SemiBold, color = white, modifier = Modifier.weight(1f))
            Text("Beta", fontSize = 12.sp, color = white,
                modifier = Modifier.clip(RoundedCornerShape(50)).background(white.copy(alpha = 0.12f)).padding(horizontal = 10.dp, vertical = 3.dp))
        }
        Spacer(Modifier.height(12.dp))
        Row(glass.fillMaxWidth().clickableTv(onOpenServers).padding(horizontal = 14.dp, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically) {
            val label = when {
                selection == null -> L.t("Сервер не выбран — добавьте подписку")
                s.autoBest -> "⚡ " + L.t("Лучший сервер") + if (on && vpn.routeRemark.isNotEmpty()) " · " + cleanRemark(vpn.routeRemark) else ""
                else -> {
                    val (group, server) = selection
                    val remark = server["remark"].toString()
                    val ping = ui.pings[server["ui_id"].toString()]
                    val tail = when { ping == null -> group.name; ping < 0 -> L.t("не отвечает"); else -> "$ping " + L.t("мс") }
                    flagOf(remark) + "  " + cleanRemark(remark) + " · " + tail
                }
            }
            Text(label, color = white, fontSize = 14.sp, maxLines = 1, modifier = Modifier.weight(1f))
            Icon(Icons.Outlined.ChevronRight, null, tint = white.copy(alpha = 0.6f))
        }

        val whitelist by com.sadness.vpn.vpn.Whitelist.state.collectAsState()
        if (s.whitelistCheck && whitelist == com.sadness.vpn.vpn.Whitelist.State.ON) {
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Color.Black.copy(alpha = 0.35f))
                .border(1.dp, Palette.Warn.copy(alpha = 0.55f), RoundedCornerShape(14.dp))
                .clickableTv { com.sadness.vpn.vpn.Whitelist.recheck() }.padding(12.dp),
                verticalAlignment = Alignment.CenterVertically) {
                Text("⚠", fontSize = 20.sp, color = Palette.Warn)
                Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(L.t("Оператор включил белые списки"), color = white, fontWeight = FontWeight.Medium)
                    Text(L.t("Зарубежные сайты напрямую не открываются. Если VPN перестал работать — выберите сервер для белых списков."),
                        color = white.copy(alpha = 0.75f), fontSize = 12.sp)
                }
            }
        }

        if (batteryRestricted && !s.batteryDismissed) {
            Spacer(Modifier.height(10.dp))
            Column(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Color.Black.copy(alpha = 0.35f))
                .border(1.dp, Palette.Warn.copy(alpha = 0.5f), RoundedCornerShape(14.dp)).padding(12.dp)) {
                Text(L.t("Телефон может отключать VPN в фоне"), color = white, fontWeight = FontWeight.Medium)
                Text(L.t("Разрешите работу без ограничений батареи, иначе система может закрыть VPN при выключенном экране."),
                    color = white.copy(alpha = 0.75f), fontSize = 12.sp, modifier = Modifier.padding(top = 3.dp, bottom = 8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SmallButton(L.t("Исправить"), Palette.Warn, Color(0xFF080A0F), Modifier.weight(1f), onFixBattery)
                    SmallButton(L.t("Позже"), white.copy(alpha = 0.12f), white, Modifier.weight(1f)) {
                        model.updateSettingsQuiet { it.copy(batteryDismissed = true) }
                    }
                }
            }
        }

        Column(Modifier.weight(1f).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            GlassPowerButton(vpn.status) {
                when (vpn.status) {
                    Status.OFF -> onConnect()
                    Status.ON, Status.CONNECTING -> model.disconnect()
                    Status.STOPPING -> Unit
                }
            }
            Spacer(Modifier.height(14.dp))
            val state = when (vpn.status) {
                Status.ON -> L.t("Защищено")
                Status.CONNECTING -> L.t("Подключение…")
                Status.STOPPING -> L.t("Отключение…")
                Status.OFF -> L.t("Нажми, чтобы подключить")
            }
            Text(state.uppercase(), color = white.copy(alpha = 0.88f), fontSize = 13.sp, letterSpacing = 1.sp)
            Row(verticalAlignment = Alignment.Bottom, modifier = Modifier.padding(top = 4.dp)) {
                val rate = formatRate(vpn.down)
                Text(if (on) rate.first else "—", fontSize = 34.sp, fontWeight = FontWeight.SemiBold, color = white)
                if (on) Text("  " + rate.second, fontSize = 13.sp, color = white.copy(alpha = 0.7f), modifier = Modifier.padding(bottom = 6.dp))
            }
            if (vpn.status == Status.OFF && vpn.error.isNotEmpty()) {
                Text(vpn.error, color = Color(0xFFFF8A95), fontSize = 13.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    modifier = Modifier.padding(top = 10.dp).clip(RoundedCornerShape(12.dp)).background(Color.Black.copy(alpha = 0.35f)).padding(10.dp))
            }
            if (on && vpn.onBackup && !s.autoBest) {
                Text(L.t("Выбранный сервер не отвечает — трафик идёт через ") + "«${cleanRemark(vpn.routeRemark)}»",
                    color = Palette.Warn, fontSize = 13.sp, textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                    modifier = Modifier.padding(top = 10.dp))
            }
        }

        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            GlassTile(L.t("Отдача"), if (on) formatRateText(vpn.up) else "—", glass, Modifier.weight(1f))
            GlassTile(L.t("Сессия"), if (on) formatDuration(now - vpn.startedAt) else "—", glass, Modifier.weight(1f))
        }
    }
    }
}

@Composable
private fun GlassTile(label: String, value: String, glass: Modifier, modifier: Modifier) {
    Column(modifier.then(glass).padding(horizontal = 14.dp, vertical = 11.dp)) {
        Text(label, color = Color.White.copy(alpha = 0.78f), fontSize = 12.sp)
        Text(value, color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
    }
}

/** Кнопка из матового стекла; при подключении мягко пульсирует. */
@Composable
private fun GlassPowerButton(status: Status, onClick: () -> Unit) {
    val pulse = androidx.compose.animation.core.rememberInfiniteTransition(label = "pulse")
    val k by pulse.animateFloat(1f, if (status == Status.CONNECTING) 1.06f else 1f,
        androidx.compose.animation.core.infiniteRepeatable(androidx.compose.animation.core.tween(700),
            androidx.compose.animation.core.RepeatMode.Reverse), label = "k")
    val on = status == Status.ON
    Box(Modifier.size(128.dp).graphicsLayer { scaleX = k; scaleY = k }.clip(CircleShape)
        .background(Color.White.copy(alpha = if (on) 0.16f else 0.09f))
        .border(1.dp, Color.White.copy(alpha = if (on) 0.4f else 0.2f), CircleShape)
        .clickableTv(onClick), contentAlignment = Alignment.Center) {
        Icon(Icons.Outlined.PowerSettingsNew, L.t("Подключить"), tint = Color.White, modifier = Modifier.size(46.dp))
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
