package com.sadness.vpn.ui

import android.content.Intent
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sadness.vpn.BuildConfig
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
    val s = ui.data.settings
    val context = LocalContext.current
    var dnsMenu by remember { mutableStateOf(false) }
    var hwidConfirm by remember { mutableStateOf(false) }
    var log by remember { mutableStateOf<String?>(null) }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Text("Настройки", fontSize = 20.sp, fontWeight = FontWeight.Medium, color = Palette.Text, modifier = Modifier.padding(top = 12.dp))

        Panel(Modifier.fillMaxWidth()) {
            Column {
                Box {
                    SettingRow("DNS", DNS_NAMES[s.dnsPreset] ?: s.dnsPreset) { dnsMenu = true }
                    DropdownMenu(expanded = dnsMenu, onDismissRequest = { dnsMenu = false }) {
                        DNS_NAMES.forEach { (key, title) ->
                            DropdownMenuItem(text = { Text(title) }, onClick = {
                                dnsMenu = false
                                model.updateSettings { it.copy(dnsPreset = key) }
                            })
                        }
                    }
                }
                Divider()
                Toggle("Обновлять подписки при запуске", "Как на компьютере: при каждом открытии приложения", s.autoUpdate) { v -> model.updateSettings { it.copy(autoUpdate = v) } }
                Divider()
                Toggle("Автоматическая замена сервера", "Если сервер перестал отвечать — запасной из той же подписки", s.failover) { v -> model.updateSettings { it.copy(failover = v) } }
                Divider()
                Toggle("IPv6 через VPN", "Сайты с IPv6 открываются через сервер, а не напрямую", s.ipv6) { v -> model.updateSettings { it.copy(ipv6 = v) } }
                Divider()
                Toggle("Мультиплексирование (mux)", "Несколько соединений в одном; не для HY2 и XHTTP", s.mux) { v -> model.updateSettings { it.copy(mux = v) } }
                Divider()
                Toggle("Блокировать UDP", "Для серверов, где UDP не работает", s.blockUdp) { v -> model.updateSettings { it.copy(blockUdp = v) } }
            }
        }

        Panel(Modifier.fillMaxWidth()) {
            Column {
                SettingRow("Постоянный VPN", "Системные настройки: включаться при старте телефона и блокировать сеть без VPN") {
                    context.startActivity(Intent(AndroidSettings.ACTION_VPN_SETTINGS))
                }
                Divider()
                SettingRow("ID устройства (HWID)", ui.data.hwid) { hwidConfirm = true }
                Divider()
                SettingRow("Журнал ядра", "Последние строки — для диагностики") {
                    log = File(context.cacheDir, "core-vpn.log").takeIf { it.isFile }?.readLines()?.takeLast(80)?.joinToString("\n")
                        ?.replace(Regex("""\b\d{1,3}(\.\d{1,3}){3}\b"""), "x.x.x.x") ?: "Журнал пуст: VPN ещё не включался."
                }
            }
        }

        Text("Sadness VPN для Android ${BuildConfig.VERSION_NAME} · Beta", color = Palette.Text3, fontSize = 12.sp,
            modifier = Modifier.padding(vertical = 8.dp))
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
private fun Divider() = HorizontalDivider(color = Palette.Border, modifier = Modifier.padding(vertical = 4.dp))

@Composable
private fun SettingRow(title: String, value: String, onClick: () -> Unit) {
    Column(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 8.dp)) {
        Text(title, color = Palette.Text)
        Text(value, color = Palette.Text3, fontSize = 12.sp, maxLines = 2)
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
