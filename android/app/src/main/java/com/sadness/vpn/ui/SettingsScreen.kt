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
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Palette
import androidx.compose.material.icons.outlined.Wifi
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
import androidx.compose.ui.graphics.asImageBitmap
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
    when (page) {
        "socks" -> { BackHandler { page = "main" }; SocksScreen(ui, model, modifier, onBack = { page = "main" }) }
        "wifi" -> { BackHandler { page = "main" }; WifiShareScreen(ui, model, modifier, onBack = { page = "main" }) }
        "traffic" -> { BackHandler { page = "main" }; TrafficScreen(modifier, onBack = { page = "main" }) }
        "backup" -> { BackHandler { page = "main" }; BackupScreen(model, modifier, onBack = { page = "main" }) }
        "report" -> { BackHandler { page = "main" }; ReportScreen(model, modifier, onBack = { page = "main" }) }
        else -> MainSettings(ui, model, modifier, onOpenSocks = { page = "socks" }, onOpenWifi = { page = "wifi" }, onOpen = { page = it })
    }
}

@Composable
private fun MainSettings(ui: UiState, model: AppModel, modifier: Modifier, onOpenSocks: () -> Unit, onOpenWifi: () -> Unit,
                         onOpen: (String) -> Unit) {
    val s = ui.data.settings
    val context = LocalContext.current
    var dnsMenu by remember { mutableStateOf(false) }
    var hwidConfirm by remember { mutableStateOf(false) }
    var log by remember { mutableStateOf<String?>(null) }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(L.t("Настройки"), fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Palette.Text, modifier = Modifier.padding(top = 14.dp))

        Section(Icons.Outlined.PhoneAndroid, L.t("Устройство"))
        Card {
            Row(Modifier.fillMaxWidth().padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(L.t("ID устройства (HWID)"), color = Palette.Text)
                    Text(ui.data.hwid, color = Palette.Text3, fontSize = 12.sp, fontFamily = FontFamily.Monospace)
                }
                IconButton(onClick = { copy(context, "HWID", ui.data.hwid, sensitive = false); model.message(L.t("ID скопирован")) }) {
                    Icon(Icons.Outlined.ContentCopy, L.t("Скопировать ID"), tint = Palette.Text2)
                }
            }
            Divider()
            Link(L.t("Создать новый ID"), L.t("Провайдер увидит телефон как новое устройство")) { hwidConfirm = true }
        }

        Section(Icons.Outlined.Settings, L.t("Общие"))
        Card {
            Toggle(L.t("Подключаться при запуске"), L.t("К последнему серверу при открытии приложения"), s.connectOnLaunch) { v -> model.updateSettings { it.copy(connectOnLaunch = v) } }
            Divider()
            Toggle(L.t("Определять белые списки"), L.t("При смене сети проверяем, открываются ли зарубежные сайты напрямую, и предупреждаем, если оператор включил белые списки."), s.whitelistCheck) { v -> model.setWhitelistCheck(v) }
            Divider()
            Toggle(L.t("Telegram-прокси"), L.t("Встроенный TG WS Proxy: Telegram ходит через WebSocket напрямую, мимо VPN-сервера. Работает и без VPN."), s.tgProxy) { v -> model.setTgProxy(v) }
            if (s.tgProxy) {
                Divider()
                Link(L.t("Подключить в Telegram"), L.t("Откроет Telegram и предложит добавить прокси")) {
                    runCatching { context.startActivity(android.content.Intent(android.content.Intent.ACTION_VIEW, android.net.Uri.parse(com.sadness.vpn.vpn.TgWsProxy.link(s.tgProxySecret)))) }
                        .onFailure { model.message(L.t("Telegram не установлен")) }
                }
            }
            Divider()
            Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                Text(L.t("Проверка серверов"), color = Palette.Text)
                Text(L.t("TCP быстрее, HTTP точнее — настоящий запрос через сервер"), color = Palette.Text3, fontSize = 12.sp)
                Spacer(Modifier.height(8.dp))
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Palette.Field).padding(3.dp)) {
                    for ((key, title) in listOf("tcp" to L.t("TCP (быстрый)"), "http" to L.t("HTTP (точный)"))) {
                        val on = s.pingMode == key
                        Text(title, textAlign = TextAlign.Center, fontSize = 13.sp,
                            color = if (on) Palette.Bg else Palette.Text3,
                            modifier = Modifier.weight(1f).clip(RoundedCornerShape(8.dp))
                                .background(if (on) Palette.Accent else Palette.Field)
                                .clickableTv { model.updateSettings { it.copy(pingMode = key) } }.padding(vertical = 8.dp))
                    }
                }
            }
            Divider()
            Toggle(L.t("Обновлять подписки при запуске"), L.t("Как на компьютере: при каждом открытии приложения"), s.autoUpdate) { v -> model.updateSettings { it.copy(autoUpdate = v) } }
        }

        Section(Icons.Outlined.Notifications, L.t("Подписки"))
        Card {
            Toggle(L.t("Обновлять в фоне"), L.t("Даже когда приложение закрыто"), s.bgRefresh) { v -> model.updateSettingsQuiet { it.copy(bgRefresh = v) } }
            if (s.bgRefresh) {
                Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
                    Text(L.t("Как часто"), color = Palette.Text)
                    Row(Modifier.padding(top = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        for (h in listOf(3, 6, 12, 24)) Chip("$h " + L.t("ч"), s.bgHours == h) { model.updateSettingsQuiet { it.copy(bgHours = h) } }
                    }
                }
            }
            Divider()
            Toggle(L.t("Предупреждать о конце"), L.t("За 3 дня и за 1 день до окончания"), s.warnExpire) { v -> model.updateSettingsQuiet { it.copy(warnExpire = v) } }
            Divider()
            Toggle(L.t("Предупреждать о трафике"), L.t("Когда осталось 10% и 0%"), s.warnTraffic) { v -> model.updateSettingsQuiet { it.copy(warnTraffic = v) } }
        }

        Section(Icons.Outlined.Public, L.t("VPN и доступ"))
        Card {
            Toggle(L.t("Поддержка Gemini / AI Studio"), L.t("DNS сервисов Google AI через Xbox DNS, их трафик — напрямую"), s.geminiDns) { v -> model.updateSettings { it.copy(geminiDns = v) } }
            Divider()
            Row(Modifier.fillMaxWidth().clickableTv(onOpenSocks).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(L.t("SOCKS5 / прокси"), color = Palette.Text)
                    Text("127.0.0.1:${Store.SOCKS_PORT} · " + L.t("с паролем"), color = Palette.Text3, fontSize = 12.sp)
                }
                Text(if (s.socksEnabled) L.t("Вкл") else L.t("Выкл"), color = if (s.socksEnabled) Palette.Accent else Palette.Text3, fontSize = 13.sp)
                Icon(Icons.Outlined.ChevronRight, null, tint = Palette.Text3)
            }
            Divider()
            Row(Modifier.fillMaxWidth().clickableTv(onOpenWifi).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(L.t("Раздача по Wi-Fi"), color = Palette.Text)
                    Text(L.t("VPN для устройств в точке доступа телефона"), color = Palette.Text3, fontSize = 12.sp)
                }
                Text(if (s.shareWifi) L.t("Вкл") else L.t("Выкл"), color = if (s.shareWifi) Palette.Accent else Palette.Text3, fontSize = 13.sp)
                Icon(Icons.Outlined.ChevronRight, null, tint = Palette.Text3)
            }
            Divider()
            Toggle(L.t("Автоматическая замена сервера"), L.t("Если сервер перестал отвечать — запасной из той же подписки"), s.failover) { v -> model.updateSettings { it.copy(failover = v) } }
            Divider()
            Link(L.t("Постоянный VPN"), L.t("Запуск после перезагрузки и блокировка сети без VPN — системная настройка")) {
                context.startActivity(Intent(AndroidSettings.ACTION_VPN_SETTINGS))
            }
        }

        Section(Icons.Outlined.Lan, L.t("Сеть"))
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
            Toggle(L.t("IPv6 через VPN"), L.t("Сайты с IPv6 открываются через сервер, а не напрямую"), s.ipv6) { v -> model.updateSettings { it.copy(ipv6 = v) } }
            Divider()
            Toggle(L.t("Мультиплексирование (mux)"), L.t("Несколько соединений в одном; не для HY2 и XHTTP"), s.mux) { v -> model.updateSettings { it.copy(mux = v) } }
            Divider()
            Toggle(L.t("Блокировать UDP"), L.t("Для серверов, где UDP не работает"), s.blockUdp) { v -> model.updateSettings { it.copy(blockUdp = v) } }
        }

        Section(Icons.Outlined.Palette, L.t("Внешний вид"))
        Card {
            Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                Text(L.t("Тема"), color = Palette.Text)
                Spacer(Modifier.height(8.dp))
                Segmented(listOf("dark" to L.t("Тёмная"), "light" to L.t("Светлая"), "system" to L.t("Как в системе")), s.theme) { model.setTheme(it) }
            }
            Divider()
            Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                Text(L.t("Фон главного экрана"), color = Palette.Text)
                Spacer(Modifier.height(8.dp))
                Segmented(listOf("auto" to L.t("Авто"), "ocean" to L.t("Океан"), "sunset" to L.t("Закат"), "neon" to L.t("Неон"), "off" to L.t("Выкл")), s.aurora) { model.setAurora(it) }
                Spacer(Modifier.height(6.dp))
                Text(L.t("Авто меняет цвет по состоянию VPN. В режиме энергосбережения фон замирает."), color = Palette.Text3, fontSize = 12.sp)
            }
            Divider()
            Column(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                Text(L.t("Язык"), color = Palette.Text)
                Spacer(Modifier.height(8.dp))
                Segmented(listOf("ru" to L.t("Русский"), "en" to "English"), s.language) { model.setLanguage(it) }
            }
        }

        Section(Icons.Outlined.Storage, L.t("Данные"))
        Card {
            Link(L.t("Трафик по приложениям"), L.t("Сколько каждое приложение прогнало через VPN")) { onOpen("traffic") }
            Divider()
            Link(L.t("Резервная копия"), L.t("Сохранить или восстановить")) { onOpen("backup") }
            Divider()
            Link(L.t("Сообщить об ошибке"), L.t("Отчёт без адресов и ключей")) { onOpen("report") }
        }

        Section(Icons.Outlined.Info, L.t("Дополнительно"))
        Card {
            Link(L.t("Проверить обновления"), L.t("Версия ") + BuildConfig.VERSION_NAME + L.t(" · обновления приходят с GitHub")) { model.checkUpdates(manual = true) }
            Divider()
            Link(L.t("Журнал ядра"), L.t("Последние строки — для диагностики")) {
                log = File(context.cacheDir, "core-vpn.log").takeIf { it.isFile }?.readLines()?.takeLast(80)?.joinToString("\n")
                    ?.replace(Regex("""\b\d{1,3}(\.\d{1,3}){3}\b"""), "x.x.x.x") ?: L.t("Журнал пуст: VPN ещё не включался.")
            }
        }
        Text("Sadness VPN " + L.t("для Android") + " ${BuildConfig.VERSION_NAME} · Beta", color = Palette.Text3, fontSize = 12.sp,
            modifier = Modifier.padding(top = 6.dp, bottom = 100.dp))
    }

    if (hwidConfirm) {
        AlertDialog(onDismissRequest = { hwidConfirm = false },
            title = { Text(L.t("Создать новый ID?")) },
            text = { Text(L.t("Провайдер увидит телефон как новое устройство, и оно займёт ещё одно место в лимите устройств подписки.")) },
            confirmButton = { TextButton(onClick = { hwidConfirm = false; model.regenerateHwid() }) { Text(L.t("Создать")) } },
            dismissButton = { TextButton(onClick = { hwidConfirm = false }) { Text(L.t("Отмена")) } })
    }
    log?.let { text ->
        AlertDialog(onDismissRequest = { log = null },
            title = { Text(L.t("Журнал ядра")) },
            text = {
                Box(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState())) {
                    Text(text, fontFamily = FontFamily.Monospace, fontSize = 11.sp, color = Palette.Text2)
                }
            },
            confirmButton = { TextButton(onClick = { log = null }) { Text(L.t("Закрыть")) } })
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
            IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, L.t("Назад"), tint = Palette.Text) }
            Text(L.t("SOCKS5 / прокси"), fontSize = 20.sp, fontWeight = FontWeight.Medium, color = Palette.Text)
        }
        Card {
            Toggle(L.t("Локальный прокси"), L.t("Работает, пока VPN подключён: трафик идёт через выбранный сервер"), s.socksEnabled) { v ->
                model.updateSettings { it.copy(socksEnabled = v) }
            }
        }
        Card {
            Field(L.t("Адрес"), host)
            Divider()
            Field(L.t("Порт"), Store.SOCKS_PORT.toString())
            Divider()
            Field(L.t("Логин"), s.socksUser)
            Divider()
            Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(L.t("Пароль"), color = Palette.Text3, modifier = Modifier.weight(1f))
                Text(if (showPassword) s.socksPassword else "•".repeat(10), color = Palette.Text, fontFamily = FontFamily.Monospace)
                IconButton(onClick = { showPassword = !showPassword }) {
                    Icon(if (showPassword) Icons.Outlined.Visibility else Icons.Outlined.VisibilityOff,
                        if (showPassword) L.t("Скрыть пароль") else L.t("Показать пароль"), tint = Palette.Text3)
                }
            }
        }
        ActionButton(Icons.Outlined.Send, L.t("Открыть в Telegram"), primary = true) {
            val link = Uri.parse("tg://socks?server=127.0.0.1&port=${Store.SOCKS_PORT}" +
                "&user=${Uri.encode(s.socksUser)}&pass=${Uri.encode(s.socksPassword)}")
            try {
                context.startActivity(Intent(Intent.ACTION_VIEW, link))
                if (!s.socksEnabled) model.message(L.t("Не забудьте включить прокси и подключить VPN."))
            } catch (_: ActivityNotFoundException) {
                model.message(L.t("Telegram не установлен."))
            }
        }
        ActionButton(Icons.Outlined.ContentCopy, L.t("Скопировать данные"), primary = false) {
            copy(context, "SOCKS5", "socks5://${s.socksUser}:${s.socksPassword}@$host:${Store.SOCKS_PORT}", sensitive = true)
            model.message(L.t("Данные прокси скопированы"))
        }
        Card {
            Toggle(L.t("Разрешить LAN"), L.t("Доступ с других устройств в этой Wi-Fi сети — тоже по паролю"), s.socksLan) { v ->
                model.updateSettings { it.copy(socksLan = v) }
            }
            Divider()
            Row(Modifier.fillMaxWidth().clickableTv { newPassword = true }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(L.t("Новый пароль"), color = Palette.Text)
                    Text(L.t("Старые настройки в приложениях перестанут работать"), color = Palette.Text3, fontSize = 12.sp)
                }
                Icon(Icons.Outlined.Refresh, null, tint = Palette.Text3)
            }
        }
        Text(L.t("Без пароля прокси не включается: на телефоне к 127.0.0.1 может обратиться любое приложение."),
            color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp))
        Spacer(Modifier.height(96.dp))
    }
    if (newPassword) {
        AlertDialog(onDismissRequest = { newPassword = false },
            title = { Text(L.t("Создать новый пароль?")) },
            text = { Text(L.t("Приложения, настроенные на старый пароль (например, Telegram), перестанут подключаться к прокси.")) },
            confirmButton = { TextButton(onClick = { newPassword = false; model.regenerateSocksPassword() }) { Text(L.t("Создать")) } },
            dismissButton = { TextButton(onClick = { newPassword = false }) { Text(L.t("Отмена")) } })
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
    Row(Modifier.fillMaxWidth().clickableTv(onClick).padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
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
        .clickableTv(onClick).padding(vertical = 12.dp),
        horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = if (primary) Palette.Bg else Palette.Text)
        Spacer(Modifier.width(8.dp))
        Text(title, color = if (primary) Palette.Bg else Palette.Text, fontWeight = FontWeight.Medium)
    }
}

@Composable
private fun Toggle(title: String, subtitle: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickableTv { onChange(!checked) }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 10.dp)) {
            Text(title, color = Palette.Text)
            Text(subtitle, color = Palette.Text3, fontSize = 12.sp)
        }
        Switch(checked = checked, onCheckedChange = onChange,
            colors = SwitchDefaults.colors(checkedTrackColor = Palette.Accent, checkedThumbColor = Palette.Text,
                uncheckedTrackColor = Palette.Track, uncheckedThumbColor = Palette.Text2, uncheckedBorderColor = Palette.Track))
    }
}

@Composable
private fun WifiShareScreen(ui: UiState, model: AppModel, modifier: Modifier, onBack: () -> Unit) {
    val s = ui.data.settings
    val context = LocalContext.current
    var addresses by remember { mutableStateOf(com.sadness.vpn.vpn.Hotspot.addresses()) }
    androidx.compose.runtime.LaunchedEffect(Unit) {
        while (true) { addresses = com.sadness.vpn.vpn.Hotspot.addresses(); kotlinx.coroutines.delay(3000) }
    }
    val address = addresses.firstOrNull()
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BackTitle(L.t("Раздача по Wi-Fi"), onBack)
        Card {
            Toggle(L.t("Раздавать VPN"), L.t("Прокси HTTP и SOCKS5 для устройств, подключённых к точке доступа телефона"), s.shareWifi) { v ->
                model.updateSettings { it.copy(shareWifi = v) }
            }
        }
        if (address == null) {
            Card {
                Row(Modifier.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Icon(Icons.Outlined.Wifi, null, tint = Palette.Warn)
                    Spacer(Modifier.width(10.dp))
                    Text(L.t("Точка доступа выключена. Включите её в настройках телефона, затем переподключите VPN."), color = Palette.Text2, fontSize = 13.sp)
                }
                ActionButton(Icons.Outlined.Wifi, L.t("Открыть настройки точки доступа"), primary = false) {
                    runCatching { context.startActivity(Intent(AndroidSettings.ACTION_WIRELESS_SETTINGS)) }
                }
            }
        } else {
            val text = "${address.ip}:${Store.SOCKS_PORT}"
            Panel(Modifier.fillMaxWidth()) {
                Column(Modifier.fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally) {
                    QrImage(text, 180)
                    Text(L.t("Адрес прокси для других устройств"), color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
                }
            }
            Card {
                Field(L.t("Прокси (HTTP и SOCKS5)"), address.ip)
                Divider()
                Field(L.t("Порт"), Store.SOCKS_PORT.toString())
                Divider()
                Field(L.t("Пароль"), L.t("не нужен в точке доступа"))
            }
            ActionButton(Icons.Outlined.ContentCopy, L.t("Скопировать адрес"), primary = false) {
                copy(context, "proxy", text, sensitive = false)
                model.message(L.t("Адрес скопирован"))
            }
        }
        Text(L.t("На другом устройстве: настройки этой Wi-Fi сети → Прокси → Вручную → адрес и порт выше. Через прокси идут браузеры и большинство приложений; игры и звонки (UDP) — напрямую. Раздача работает, пока VPN подключён; после включения точки доступа переподключите VPN."),
            color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 4.dp))
        Spacer(Modifier.height(24.dp))
    }
}

/** QR-код из текста (ZXing). */
@Composable
fun QrImage(text: String, sizeDp: Int) {
    val bitmap = remember(text) {
        val matrix = com.google.zxing.qrcode.QRCodeWriter().encode(text, com.google.zxing.BarcodeFormat.QR_CODE, 512, 512,
            mapOf(com.google.zxing.EncodeHintType.MARGIN to 1))
        val bmp = android.graphics.Bitmap.createBitmap(matrix.width, matrix.height, android.graphics.Bitmap.Config.RGB_565)
        for (x in 0 until matrix.width) for (y in 0 until matrix.height) {
            bmp.setPixel(x, y, if (matrix[x, y]) android.graphics.Color.BLACK else android.graphics.Color.WHITE)
        }
        bmp.asImageBitmap()
    }
    androidx.compose.foundation.Image(bitmap, null, Modifier.size(sizeDp.dp).clip(RoundedCornerShape(10.dp)))
}
