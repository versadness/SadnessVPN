package com.sadness.vpn.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.List
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Apps
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Map
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sadness.vpn.data.AppsMode

@Composable
fun RoutesScreen(ui: UiState, model: AppModel, modifier: Modifier) {
    var page by rememberSaveable { mutableStateOf("main") }
    if (page == "apps") {
        BackHandler { page = "main" }
        AppsScreen(ui, model, modifier, onBack = { page = "main" })
        return
    }
    val s = ui.data.settings
    var adding by remember { mutableStateOf(false) }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(L.t("Маршруты"), fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Palette.Text, modifier = Modifier.padding(top = 14.dp))
        Text(L.t("Что идёт через VPN, а что напрямую. Применяется при подключении."), color = Palette.Text3, fontSize = 12.sp)

        SectionTitle(Icons.Outlined.Map, L.t("Готовые наборы"))
        CardBox {
            ToggleRow("🇷🇺 " + L.t("Российские сайты напрямую"), L.t("Банки, Госуслуги, маркетплейсы и сайты .ru — без VPN"), s.ruDirect) { v ->
                model.updateSettings { it.copy(ruDirect = v) }
            }
            RowDivider()
            ToggleRow(L.t("Блокировка рекламы и трекеров"), L.t("Во всех приложениях, по списку доменов"), s.adblock) { v ->
                model.updateSettings { it.copy(adblock = v) }
            }
            RowDivider()
            ToggleRow("YouTube · Discord · Telegram", L.t("Всегда через VPN — даже если сработал набор выше"), s.servicesVpn) { v ->
                model.updateSettings { it.copy(servicesVpn = v) }
            }
        }

        SectionTitle(Icons.AutoMirrored.Outlined.List, L.t("Свои правила"))
        CardBox {
            if (s.rules.isEmpty()) {
                Text(L.t("Правил пока нет. Например: chatgpt.com — через VPN, sberbank.ru — напрямую."),
                    color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(vertical = 10.dp))
            }
            s.rules.forEachIndexed { index, rule ->
                if (index > 0) RowDivider()
                Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                    Chip(if (rule.type == "domain") L.t("домен") else "IP")
                    Spacer(Modifier.width(8.dp))
                    Text(rule.value, color = Palette.Text, modifier = Modifier.weight(1f), maxLines = 1)
                    Text(actionTitle(rule.action), fontSize = 12.sp, color = when (rule.action) {
                        "vpn" -> Palette.Accent; "block" -> Palette.Danger; else -> Palette.Text3
                    })
                    IconButton(onClick = { model.removeRule(index) }) { Icon(Icons.Outlined.Close, L.t("Удалить"), tint = Palette.Text3) }
                }
            }
        }
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Palette.Surface2).clickable { adding = true }.padding(vertical = 11.dp),
            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Add, null, tint = Palette.Text)
            Spacer(Modifier.width(6.dp))
            Text(L.t("Добавить правило"), color = Palette.Text)
        }

        SectionTitle(Icons.Outlined.Apps, L.t("Приложения"))
        CardBox {
            Row(Modifier.fillMaxWidth().clickable { page = "apps" }.padding(vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(L.t("Через VPN"), color = Palette.Text)
                    Text(when (s.appsMode) {
                        AppsMode.ALL -> L.t("Все приложения")
                        AppsMode.ONLY -> L.t("Только выбранные: ") + s.apps.size
                        AppsMode.EXCEPT -> L.t("Все, кроме выбранных: ") + s.apps.size
                    }, color = Palette.Text3, fontSize = 12.sp)
                }
                Icon(Icons.Outlined.ChevronRight, null, tint = Palette.Text3)
            }
        }
        Spacer(Modifier.height(24.dp))
    }
    if (adding) AddRuleDialog(onDismiss = { adding = false }, onAdd = { type, value, action -> if (model.addRule(type, value, action)) adding = false })
}

private fun actionTitle(action: String) = when (action) {
    "vpn" -> L.t("VPN"); "block" -> L.t("блок"); else -> L.t("напрямую")
}

@Composable
private fun AddRuleDialog(onDismiss: () -> Unit, onAdd: (String, String, String) -> Unit) {
    var type by remember { mutableStateOf("domain") }
    var action by remember { mutableStateOf("vpn") }
    var value by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(L.t("Новое правило")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Segmented(listOf("domain" to L.t("Домен"), "ip" to L.t("IP / подсеть")), type) { type = it }
                OutlinedTextField(value, { value = it }, singleLine = true,
                    label = { Text(if (type == "domain") L.t("Домен") else L.t("IP или подсеть")) },
                    placeholder = { Text(if (type == "domain") "example.com" else "10.0.0.0/8") })
                Segmented(listOf("vpn" to L.t("Через VPN"), "direct" to L.t("Напрямую"), "block" to L.t("Блок")), action) { action = it }
                if (type == "domain") Text(L.t("Действует и на поддомены: example.com включает www.example.com."), color = Palette.Text3, fontSize = 12.sp)
            }
        },
        confirmButton = { TextButton(onClick = { onAdd(type, value, action) }, enabled = value.isNotBlank()) { Text(L.t("Добавить")) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(L.t("Отмена")) } },
    )
}

@Composable
fun Segmented(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(Palette.Field).padding(3.dp)) {
        for ((key, title) in options) {
            val on = key == selected
            Text(title, textAlign = TextAlign.Center, fontSize = 13.sp, maxLines = 1,
                color = if (on) Palette.Bg else Palette.Text3,
                modifier = Modifier.weight(1f).clip(RoundedCornerShape(8.dp))
                    .background(if (on) Palette.Accent else Palette.Field)
                    .clickable { onSelect(key) }.padding(vertical = 8.dp))
        }
    }
}

@Composable
fun Chip(text: String, on: Boolean = false, onClick: (() -> Unit)? = null) {
    Text(text, fontSize = 11.sp, color = if (on) Palette.Accent else Palette.Text2,
        modifier = Modifier.clip(RoundedCornerShape(50)).background(if (on) Palette.AccentSoft else Palette.Surface2)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 10.dp, vertical = 5.dp))
}

@Composable
fun SectionTitle(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String) {
    Row(Modifier.padding(start = 4.dp, top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = Palette.Accent, modifier = Modifier.size(18.dp))
        Spacer(Modifier.width(8.dp))
        Text(title, color = Palette.Accent, fontWeight = FontWeight.Medium, fontSize = 14.sp)
    }
}

@Composable
fun CardBox(content: @Composable () -> Unit) {
    Panel(Modifier.fillMaxWidth()) { Column { content() } }
}

@Composable
fun RowDivider() = androidx.compose.material3.HorizontalDivider(color = Palette.Border, modifier = Modifier.padding(vertical = 2.dp))

@Composable
fun ToggleRow(title: String, subtitle: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { onChange(!checked) }.padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 10.dp)) {
            Text(title, color = Palette.Text)
            if (subtitle.isNotEmpty()) Text(subtitle, color = Palette.Text3, fontSize = 12.sp)
        }
        androidx.compose.material3.Switch(checked = checked, onCheckedChange = onChange,
            colors = androidx.compose.material3.SwitchDefaults.colors(checkedTrackColor = Palette.Accent, checkedThumbColor = androidx.compose.ui.graphics.Color.White,
                uncheckedTrackColor = Palette.Track, uncheckedThumbColor = Palette.Text2, uncheckedBorderColor = Palette.Track))
    }
}

@Composable
fun BackTitle(title: String, onBack: () -> Unit) {
    Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, L.t("Назад"), tint = Palette.Text) }
        Text(title, fontSize = 20.sp, fontWeight = FontWeight.Medium, color = Palette.Text)
    }
}
