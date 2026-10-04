package com.sadness.vpn.ui

import android.content.ActivityNotFoundException
import android.content.ClipData
import android.content.ClipDescription
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PersistableBundle
import android.provider.Settings as AndroidSettings
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Lan
import androidx.compose.material.icons.outlined.PhoneAndroid
import androidx.compose.material.icons.outlined.Public
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Send
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sadness.vpn.BuildConfig
import com.sadness.vpn.data.Store
import java.io.File

private val DNS_NAMES = linkedMapOf(
    "cf_google" to "Cloudflare + Google (DoT)",
    "cloudflare" to "Cloudflare (DoT)",
    "google" to "Google (DoT)",
    "adguard" to "AdGuard (DoT)",
    "quad9" to "Quad9 (DoT)",
    "comss" to "Comss Smart DNS",
    "comss_dot" to "Comss Smart DNS (DoT)",
    "xbox" to "Xbox Smart DNS",
    "xbox_dot" to "Xbox Smart DNS (DoT)",
)

@Composable
fun SettingsScreen(ui: UiState, model: AppModel, modifier: Modifier) {
    var page by rememberSaveable { mutableStateOf("main") }
    if (page == "socks") {
        BackHandler { page = "main" }
        SocksScreen(ui, model, modifier, onBack = { page = "main" })
    } else {
        MainSettings(ui, model, modifier, onOpenSocks = { page = "socks" })
    }
}

@Composable
private fun MainSettings(ui: UiState, model: AppModel, modifier: Modifier, onOpenSocks: () -> Unit) {
    val s = ui.data.settings
    val context = LocalContext.current
    var dnsMenu by remember { mutableStateOf(false) }
    var hwidConfirm by remember { mutableStateOf(false) }
    var log by remember { mutableStateOf<String?>(null) }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Настройки", fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Palette.Text, modifier = Modifier.padding(top = 14.dp))

        Section(Icons.Outlined.PhoneAndroid, "Устройство")
        Card {
            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("ID устройства (HWID)", color = Palette.Text)
                    Text(ui.data.hwid, color = Palette.Text3, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                }
                IconButton(onClick = { copy(context, "HWID", ui.data.hwid, sensitive = false); model.message("ID скопирован") }) {
                    Icon(Icons.Outlined.ContentCopy, "Скопировать ID", tint = Palette.Text2)
                }
            }
            Divider()
            Link("Создать новый ID", "Провайдер увидит телефон как новое устройство") { hwidConfirm = true }
        }

        Section(Icons.Outlined.Settings, "Общие")
        Card {
            Toggle("Подключаться при запуске", "К последнему серверу при открытии приложения", s.connectOnLaunch) { v -> model.updateSettings { it.copy(connectOnLaunch = v) } }
            Divider()
            Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                Text("Проверка серверов", color = Palette.Text)
                Text("TCP быстрее, HTTP точнее — настоящий запрос через сервер", color = Palette.Text3, fontSize = 12.sp)
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Palette.Field).padding(3.dp)) {
                    for ((key, title) in listOf("tcp" to "TCP (быстрый)", "http" to "HTTP (точный)")) {
                        val on = s.pingMode == key
                        Text(title, textAlign = TextAlign.Center, fontSize = 13.sp,
                            color = if (on) Palette.Bg else Palette.Text3,
                            modifier = Modifier.weight(1f).clip(RoundedCornerShape(8.dp))
                                .background(if (on) Palette.Accent else Palette.Field)
                                .clickable { model.updateSettings { it.copy(pingMode = key) } }.padding(vertical = 8.dp))
                    }
                }
            }
            Divider()
            Toggle("Обновлять подписки при запуске", "Как на компьютере: при каждом открытии приложения", s.autoUpdate) { v -> model.updateSettings { it.copy(autoUpdate = v) } }
        }

        Section(Icons.Outlined.Public, "VPN и доступ")
        Card {
            Toggle("Поддержка Gemini / AI Studio", "DNS сервисов Google AI через Xbox DNS, их трафик — напрямую", s.geminiDns) { v -> model.updateSettings { it.copy(geminiDns = v) } }
            Divider()
            Row(Modifier.fillMaxWidth().clickable(onClick = onOpenSocks).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("SOCKS5 / прокси", color = Palette.Text)
                    Text("127.0.0.1:${Store.SOCKS_PORT} · с паролем", color = Palette.Text3, fontSize = 12.sp)
                }
                Text(if (s.socksEnabled) "Вкл" else "Выкл", color = if (s.socksEnabled) Palette.Accent else Palette.Text3, fontSize = 13.sp)
                Icon(Icons.Outlined.ChevronRight, null, tint = Palette.Text3)
            }
            Divider()
            Toggle("Автоматическая замена сервера", "Если сервер перестал отвечать — запасной из той же подписки", s.failover) { v -> model.updateSettings { it.copy(failover = v) } }
            Divider()
            Link("Постоянный VPN", "Запуск после перезагрузки и блокировка сети без VPN — системная настройка") {
                context.startActivity(Intent(AndroidSettings.ACTION_VPN_SETTINGS))
            }
        }

        Section(Icons.Outlined.Lan, "Сеть")
        Card {
            Box {
                Link("DNS", DNS_NAMES[s.dnsPreset] ?: s.dnsPreset) { dnsMenu = true }
                DropdownMenu(expanded = dnsMenu, onDismissRequest = { dnsMenu = false }) {
                    DNS_NAMES.forEach { (key, title) ->
                        DropdownMenuItem(text = { Text(title) }, onClick = { dnsMenu = false; model.updateSettings { it.copy(dnsPreset = key) } })
                    }
                }
            }
            Divider()
            Toggle("IPv6 через VPN", "Сайты с IPv6 открываются через сервер, а не напрямую", s.ipv6) { v -> model.updateSettings { it.copy(ipv6 = v) } }
            Divider()
            Toggle("Мультиплексирование (mux)", "Несколько соединений в одном; не для HY2 и XHTTP", s.mux) { v -> model.updateSettings { it.copy(mux = v) } }
            Divider()
            Toggle("Блокировать UDP", "Для серверов, где UDP не работает", s.blockUdp) { v -> model.updateSettings { it.copy(blockUdp = v) } }
        }

        Section(Icons.Outlined.Info, "Дополнительно")
        Card {
            Link("Журнал ядра", "Последние строки — для диагностики") {
                log = File(context.cacheDir, "core-vpn.log").takeIf { it.isFile }?.readLines()?.takeLast(80)?.joinToString("\n")
                    ?.replace(Regex("""\b\d{1,3}(\.\d{1,3}){3}\b"""), "x.x.x.x") ?: "Журнал пуст: VPN ещё не включался."
            }
        }
        Text("Sadness VPN для Android ${BuildConfig.VERSION_NAME} · Beta", color = Palette.Text3, fontSize = 12.sp,
            modifier = Modifier.padding(top = 6.dp, bottom = 100.dp))
    }

    if (hwidConfirm) {
        AlertDialog(onDismissRequest = { hwidConfirm = false },
            title = { Text("Создать новый ID?") },
            text = { Text("Провайдер увидит телефон как новое устройство, и оно займёт ещё одно место в лимите устройств подписки.") },
            confirmButton = { TextButton(onClick = { hwidConfirm = false; model.regenerateHwid() }) { Text("Создать") } },
            dismissButton = { TextButton(onClick = { hwidConfirm = false }) { Text("Отмена") } })
    }
    log?.let { text ->
        AlertDialog(onDismissRequest = { log = null },
            title = { Text("Журнал ядра") },
            text = {
                Box(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState())) {
                    Text(text, fontFamily = FontFamily.Monospace, fontSize = 11.sp, color = Palette.Text2)
                }
            },
            confirmButton = { TextButton(onClick = { log = null }) { Text("Закрыть") } })
    }
}

@Composable
private fun SocksScreen(ui: UiState, model: AppModel, modifier: Modifier, onBack: () -> Unit) {
    val s = ui.data.settings
    val context = LocalContext.current
    var showPassword by remember { mutableStateOf(false) }
    var newPassword by remember { mutableStateOf(false) }
    val host = if (s.socksLan) model.lanAddress() else "127.0.0.1"
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Назад", tint = Palette.Text) }
            Text("SOCKS5 / прокси", fontSize = 20.sp, fontWeight = FontWeight.Medium, color = Palette.Text)
        }
        Card {
            Toggle("Локальный прокси", "Работает, пока VPN подключён: трафик идёт через выбранный сервер", s.socksEnabled) { v ->
                model.updateSettings { it.copy(socksEnabled = v) }
            }
        }
        Card {
            Field("Адрес", host)
            Divider()
            Field("Порт", Store.SOCKS_PORT.toString())
            Divider()
            Field("Логин", s.socksUser)
            Divider()
            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Пароль", color = Palette.Text3, modifier = Modifier.weight(1f))
                Text(if (showPassword) s.socksPassword else "•".repeat(10), color = Palette.Text, fontFamily = FontFamily.Monospace)
                IconButton(onClick = { showPassword = !showPassword }) {
                    Icon(if (showPassword) Icons.Outlined.Visibility else Icons.Outlined.VisibilityOff,
                        if (showPassword) "Скрыть пароль" else "Показать пароль", tint = Palette.Text3)
                }
            }
        }
        ActionButton(Icons.Outlined.Send, "Открыть в Telegram", primary = true) {
            val link = Uri.parse("tg://socks?server=127.0.0.1&port=${Store.SOCKS_PORT}" +
                "&user=${Uri.encode(s.socksUser)}&pass=${Uri.encode(s.socksPassword)}")
            try {
                context.startActivity(Intent(Intent.ACTION_VIEW, link))
                if (!s.socksEnabled) model.message("Не забудьте включить прокси и подключить VPN.")
            } catch (_: ActivityNotFoundException) {
                model.message("Telegram не установлен.")
            }
        }
        ActionButton(Icons.Outlined.ContentCopy, "Скопировать данные", primary = false) {
            copy(context, "SOCKS5", "socks5://${s.socksUser}:${s.socksPassword}@$host:${Store.SOCKS_PORT}", sensitive = true)
            model.message("Данные прокси скопированы")
        }
        Card {
            Toggle("Разрешить LAN", "Доступ с других устройств в этой Wi-Fi сети — тоже по паролю", s.socksLan) { v ->
                model.updateSettings { it.copy(socksLan = v) }
            }
            Divider()
            Row(Modifier.fillMaxWidth().clickable { newPassword = true }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Новый пароль", color = Palette.Text)
                    Text("Старые настройки в приложениях перестанут работать", color = Palette.Text3, fontSize = 12.sp)
                }
                Icon(Icons.Outlined.Refresh, null, tint = Palette.Text3)
            }
        }
        Text("Без пароля прокси не включается: на телефоне к 127.0.0.1 может обратиться любое приложение.",
            color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp))
        Spacer(Modifier.height(96.dp))
    }
    if (newPassword) {
        AlertDialog(onDismissRequest = { newPassword = false },
            title = { Text("Создать новый пароль?") },
            text = { Text("Приложения, настроенные на старый пароль (например, Telegram), перестанут подключаться к прокси.") },
            confirmButton = { TextButton(onClick = { newPassword = false; model.regenerateSocksPassword() }) { Text("Создать") } },
            dismissButton = { TextButton(onClick = { newPassword = false }) { Text("Отмена") } })
    }
}

private fun copy(context: Context, label: String, text: String, sensitive: Boolean) {
    val clip = ClipData.newPlainText(label, text)
    if (sensitive && Build.VERSION.SDK_INT >= 33) {
        clip.description.extras = PersistableBundle().apply { putBoolean(ClipDescription.EXTRA_IS_SENSITIVE, true) }
    }
    context.getSystemService(ClipboardManager::class.java).setPrimaryClip(clip)
}

@Composable
private fun Section(icon: ImageVector, title: String) {
    Row(Modifier.padding(start = 4.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = Palette.Accent, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(title, color = Palette.Accent, fontWeight = FontWeight.Medium, fontSize = 14.sp)
    }
}

@Composable
private fun Card(content: @Composable () -> Unit) {
    Panel(Modifier.fillMaxWidth()) { Column { content() } }
}

@Composable
private fun Divider() = HorizontalDivider(color = Palette.Border, modifier = Modifier.padding(vertical = 2.dp))

@Composable
private fun Link(title: String, value: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, color = Palette.Text)
            Text(value, color = Palette.Text3, fontSize = 12.sp, maxLines = 2)
        }
        Icon(Icons.Outlined.ChevronRight, null, tint = Palette.Text3)
    }
}

@Composable
private fun Field(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = Palette.Text3, modifier = Modifier.weight(1f))
        Text(value, color = Palette.Text, fontFamily = FontFamily.Monospace)
    }
}

@Composable
private fun ActionButton(icon: ImageVector, title: String, primary: Boolean, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(if (primary) Palette.Accent else Palette.Surface2)
        .clickable(onClick = onClick).padding(vertical = 12.dp),
        horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = if (primary) Palette.Bg else Palette.Text)
        Spacer(Modifier.width(8.dp))
        Text(title, color = if (primary) Palette.Bg else Palette.Text, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun Toggle(title: String, subtitle: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { onChange(!checked) }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 10.dp)) {
            Text(title, color = Palette.Text)
            Text(subtitle, color = Palette.Text3, fontSize = 12.sp)
        }
        Switch(checked = checked, onCheckedChange = onChange,
            colors = SwitchDefaults.colors(checkedTrackColor = Palette.Accent, checkedThumbColor = Palette.Text,
                uncheckedTrackColor = Palette.Track, uncheckedThumbColor = Palette.Text2, uncheckedBorderColor = Palette.Track))
    }
}
