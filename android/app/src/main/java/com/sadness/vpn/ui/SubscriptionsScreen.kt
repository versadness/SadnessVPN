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
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.ContentPaste
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.QrCodeScanner
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.RadioButtonUnchecked
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.RssFeed
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material.icons.outlined.VisibilityOff
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.sadness.vpn.data.Group
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter

@Composable
fun SubscriptionsScreen(ui: UiState, model: AppModel, modifier: Modifier, onScanQr: () -> Unit, onPickFile: () -> Unit,
                        readClipboard: () -> String?) {
    var adding by remember { mutableStateOf(false) }
    var menu by remember { mutableStateOf(false) }
    Column(modifier.fillMaxSize().padding(horizontal = 16.dp)) {
        Text(L.t("Подписки"), fontSize = 22.sp, fontWeight = FontWeight.Medium, color = Palette.Text,
            modifier = Modifier.padding(top = 14.dp, bottom = 12.dp))
        if (ui.clipboardOffer.isNotEmpty()) {
            Column(Modifier.fillMaxWidth().padding(bottom = 10.dp).clip(RoundedCornerShape(14.dp)).background(Palette.AccentSoft)
                .border(1.dp, Palette.Accent.copy(alpha = 0.35f), RoundedCornerShape(14.dp)).padding(12.dp)) {
                Text(L.t("В буфере обмена ссылка — добавить?"), color = Palette.Text, fontWeight = FontWeight.Medium)
                Text(ui.clipboardOffer.lines().first().let { if (it.length > 42) it.take(18) + "…" + it.takeLast(6) else it },
                    color = Palette.Text3, fontSize = 12.sp, fontFamily = FontFamily.Monospace, maxLines = 1)
                Row(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    SmallButton(L.t("Добавить"), Palette.Accent, Palette.Bg, Modifier.weight(1f)) { model.acceptClipboard() }
                    SmallButton(L.t("Нет"), Palette.Surface2, Palette.Text, Modifier.weight(1f)) { model.dismissClipboard() }
                }
            }
        }
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp)).background(Palette.Accent)
            .clickable { menu = true }.padding(vertical = 12.dp),
            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Add, null, tint = Palette.Bg)
            Spacer(Modifier.width(6.dp))
            Text(L.t("Добавить"), color = Palette.Bg, fontWeight = FontWeight.Medium)
        }
        Spacer(Modifier.height(12.dp))
        if (ui.data.groups.isEmpty()) {
            Text(L.t("Подписок пока нет. Нужна ссылка от провайдера VPN — та же, что для компьютера. Ссылки vless:// и hy2:// из Telegram открываются сразу здесь."),
                color = Palette.Text3, fontSize = 13.sp)
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp), modifier = Modifier.weight(1f)) {
            items(ui.data.groups, key = { it.id }) { group ->
                SubscriptionCard(group, selected = group.id == ui.data.selectedGroup, busy = group.id in ui.busyGroups,
                    onSelect = { model.selectGroup(group.id) }, onRefresh = { model.refresh(group.id) },
                    onRename = { model.renameGroup(group.id, it) }, onDelete = { model.deleteGroup(group.id) })
            }
            item { Spacer(Modifier.height(90.dp)) }
        }
    }
    if (adding) AddSubscriptionDialog(onDismiss = { adding = false }, onAdd = { url, name ->
        adding = false
        if (url.trim().startsWith("http")) model.addSubscription(url, name) else model.importText(url)
    })
    if (menu) {
        AlertDialog(onDismissRequest = { menu = false },
            title = { Text(L.t("Добавить")) },
            text = {
                Column {
                    MenuRow(Icons.Outlined.Link, L.t("Ссылка подписки или сервера")) { menu = false; adding = true }
                    MenuRow(Icons.Outlined.QrCodeScanner, L.t("Сканировать QR-код")) { menu = false; onScanQr() }
                    MenuRow(Icons.Outlined.ContentPaste, L.t("Из буфера обмена")) {
                        menu = false
                        val text = readClipboard()
                        if (text.isNullOrBlank()) model.message(L.t("Буфер обмена пуст.")) else model.importText(text)
                    }
                    MenuRow(Icons.Outlined.Description, L.t("Файл WireGuard / AmneziaWG (.conf)")) { menu = false; onPickFile() }
                }
            },
            confirmButton = { TextButton(onClick = { menu = false }) { Text(L.t("Отмена")) } })
    }
}

@Composable
private fun MenuRow(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickable(onClick = onClick).padding(vertical = 12.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = Palette.Accent)
        Spacer(Modifier.width(12.dp))
        Text(title, color = Palette.Text)
    }
}

@Composable
private fun SubscriptionCard(group: Group, selected: Boolean, busy: Boolean, onSelect: () -> Unit, onRefresh: () -> Unit,
                             onRename: (String) -> Unit, onDelete: () -> Unit) {
    var showUrl by remember { mutableStateOf(false) }
    var renaming by remember { mutableStateOf(false) }
    var deleting by remember { mutableStateOf(false) }
    val shape = RoundedCornerShape(18.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(Palette.Surface)
        .border(1.dp, if (selected) Palette.Accent.copy(alpha = 0.55f) else Palette.Border, shape)
        .clickable(onClick = onSelect).padding(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.RssFeed, null, tint = if (selected) Palette.Accent else Palette.Text3, modifier = Modifier.size(22.dp))
            Spacer(Modifier.width(10.dp))
            Text(group.name.ifEmpty { L.t("Подписка") }, color = Palette.Text, fontSize = 16.sp, fontWeight = FontWeight.Medium,
                maxLines = 1, modifier = Modifier.weight(1f))
            Icon(if (selected) Icons.Outlined.CheckCircle else Icons.Outlined.RadioButtonUnchecked,
                contentDescription = if (selected) L.t("Выбрана") else L.t("Выбрать"), tint = if (selected) Palette.Accent else Palette.Text3)
        }
        if (group.url.isEmpty()) {
            Text(L.t("Добавлены вручную — по ссылкам или из файлов"), color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
        } else Row(Modifier.padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text(if (showUrl) group.url else maskUrl(group.url), color = Palette.Text3, fontSize = 12.sp,
                fontFamily = FontFamily.Monospace, maxLines = if (showUrl) 3 else 1, modifier = Modifier.weight(1f, fill = false))
            Icon(if (showUrl) Icons.Outlined.Visibility else Icons.Outlined.VisibilityOff,
                contentDescription = if (showUrl) L.t("Скрыть ссылку") else L.t("Показать ссылку"), tint = Palette.Text3,
                modifier = Modifier.padding(start = 6.dp).size(18.dp).clickable { showUrl = !showUrl })
        }
        Text(updatedLine(group), color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
        expireLine(group)?.let { (text, days) ->
            Row(Modifier.padding(top = 3.dp)) {
                Text(text, color = Palette.Text2, fontSize = 13.sp)
                Text(" ($days)", color = if (days.startsWith(L.t("истекла"))) Palette.Danger else Palette.Accent, fontSize = 13.sp)
            }
        }
        val total = (group.meta["total"] as? Number)?.toLong() ?: 0
        if (total > 0) {
            val used = ((group.meta["upload"] as? Number)?.toLong() ?: 0) + ((group.meta["download"] as? Number)?.toLong() ?: 0)
            LinearProgressIndicator(progress = { (used.toFloat() / total).coerceIn(0f, 1f) },
                modifier = Modifier.padding(top = 8.dp).fillMaxWidth().height(4.dp).clip(RoundedCornerShape(2.dp)),
                color = Palette.Accent, trackColor = Palette.Track, drawStopIndicator = {})
            Text("${formatBytes(used)} " + L.t("из") + " ${formatBytes(total)}", color = Palette.Text3, fontSize = 11.sp, modifier = Modifier.padding(top = 3.dp))
        }
        if (group.error.isNotEmpty()) Text(group.error, color = Palette.Danger, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
            if (busy) CircularProgressIndicator(Modifier.padding(12.dp).size(20.dp), color = Palette.Accent, strokeWidth = 2.dp)
            else if (group.url.isNotEmpty()) IconButton(onClick = onRefresh) { Icon(Icons.Outlined.Refresh, L.t("Обновить"), tint = Palette.Text2) }
            IconButton(onClick = { renaming = true }) { Icon(Icons.Outlined.Edit, L.t("Переименовать"), tint = Palette.Text2) }
            IconButton(onClick = { deleting = true }) { Icon(Icons.Outlined.Delete, L.t("Удалить"), tint = Palette.Danger) }
        }
    }
    if (renaming) {
        var name by remember { mutableStateOf(group.name) }
        AlertDialog(onDismissRequest = { renaming = false },
            title = { Text(L.t("Название подписки")) },
            text = { OutlinedTextField(name, { name = it }, singleLine = true) },
            confirmButton = { TextButton(onClick = { renaming = false; onRename(name) }) { Text(L.t("Сохранить")) } },
            dismissButton = { TextButton(onClick = { renaming = false }) { Text(L.t("Отмена")) } })
    }
    if (deleting) {
        AlertDialog(onDismissRequest = { deleting = false },
            title = { Text(L.t("Удалить подписку?")) },
            text = { Text("«${group.name}» " + L.t("и её серверы будут удалены с телефона. У провайдера подписка останется.")) },
            confirmButton = { TextButton(onClick = { deleting = false; onDelete() }) { Text(L.t("Удалить"), color = Palette.Danger) } },
            dismissButton = { TextButton(onClick = { deleting = false }) { Text(L.t("Отмена")) } })
    }
}

/** Схема и начало адреса видны, остальное скрыто: в ссылке подписки — личный токен. */
private fun maskUrl(url: String): String {
    val scheme = url.substringBefore("://", "")
    return if (scheme.isNotEmpty()) "$scheme://" + "•".repeat(14) else "•".repeat(18)
}

private fun updatedLine(group: Group): String {
    val parts = mutableListOf("${group.servers.size} " + L.t("серв."))
    (group.meta["updated_at"] as? Number)?.toLong()?.let { at ->
        val time = Instant.ofEpochSecond(at).atZone(ZoneId.systemDefault())
        val today = java.time.LocalDate.now()
        parts += L.t("обновлено ") + when (time.toLocalDate()) {
            today -> time.format(DateTimeFormatter.ofPattern("HH:mm"))
            today.minusDays(1) -> L.t("вчера")
            else -> time.format(DateTimeFormatter.ofPattern("dd.MM.yyyy"))
        }
    }
    return parts.joinToString(" · ")
}

/** «Действует до 16.10.2026» и «12 дней» — если провайдер сообщил срок. */
private fun expireLine(group: Group): Pair<String, String>? {
    val expire = (group.meta["expire"] as? Number)?.toLong()?.takeIf { it > 0 } ?: return null
    val date = Instant.ofEpochSecond(expire).atZone(ZoneId.systemDefault())
    val days = java.time.Duration.between(Instant.now(), Instant.ofEpochSecond(expire)).toDays()
    val left = when {
        expire * 1000 < System.currentTimeMillis() -> L.t("истекла")
        days == 0L -> L.t("меньше дня")
        else -> "$days " + L.plural(days, "день", "дня", "дней")
    }
    return L.t("Действует до ") + date.format(DateTimeFormatter.ofPattern("dd.MM.yyyy")) to left
}

fun plural(n: Long, one: String, few: String, many: String): String {
    val m10 = n % 10; val m100 = n % 100
    return when {
        m10 == 1L && m100 != 11L -> one
        m10 in 2..4 && m100 !in 12..14 -> few
        else -> many
    }
}

@Composable
fun AddSubscriptionDialog(onDismiss: () -> Unit, onAdd: (String, String) -> Unit) {
    var url by remember { mutableStateOf("") }
    var name by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(L.t("Новая подписка")) },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                OutlinedTextField(url, { url = it }, label = { Text(L.t("Ссылка подписки")) }, singleLine = true,
                    placeholder = { Text("https://…") })
                OutlinedTextField(name, { name = it }, label = { Text(L.t("Название (необязательно)")) }, singleLine = true)
            }
        },
        confirmButton = { TextButton(onClick = { onAdd(url, name) }, enabled = url.isNotBlank()) { Text(L.t("Добавить")) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(L.t("Отмена")) } },
    )
}
