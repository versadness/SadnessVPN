package com.sadness.vpn.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Download
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.Upload
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.graphics.drawable.toBitmap
import com.sadness.vpn.vpn.AppTraffic
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.LocalDate

// ── Трафик по приложениям ──

@Composable
fun TrafficScreen(modifier: Modifier, onBack: () -> Unit) {
    val context = LocalContext.current
    var days by remember { mutableStateOf(1) }
    val rows by produceState<List<Pair<String, Long>>>(emptyList(), days) {
        value = withContext(Dispatchers.IO) { AppTraffic.summary(context, days) }
    }
    val total = rows.sumOf { it.second }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BackTitle(L.t("Трафик приложений"), onBack)
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            Chip(L.t("Сегодня"), days == 1) { days = 1 }
            Chip(L.t("7 дней"), days == 7) { days = 7 }
            Chip(L.t("30 дней"), days == 30) { days = 30 }
        }
        Panel(Modifier.fillMaxWidth()) {
            Column {
                Text(L.t("Через VPN") + " · " + if (days == 1) L.t("сегодня") else "$days " + L.plural(days.toLong(), "день", "дня", "дней"),
                    color = Palette.Text3, fontSize = 12.sp)
                Text(formatBytes(total), color = Palette.Text, fontSize = 22.sp, fontWeight = FontWeight.Medium)
            }
        }
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            Text(L.t("Учёт по приложениям доступен на Android 10 и новее."), color = Palette.Text3, fontSize = 13.sp)
        } else if (rows.isEmpty()) {
            Text(L.t("Пока пусто: трафик появится, когда приложения поработают через VPN."), color = Palette.Text3, fontSize = 13.sp)
        } else CardBox {
            val max = rows.first().second.coerceAtLeast(1)
            rows.take(40).forEachIndexed { index, (pkg, bytes) ->
                if (index > 0) RowDivider()
                Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    TrafficIcon(pkg)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(appLabel(context, pkg), color = Palette.Text, maxLines = 1)
                        LinearProgressIndicator(progress = { bytes.toFloat() / max }, modifier = Modifier.padding(top = 4.dp).fillMaxWidth().height(4.dp)
                            .clip(RoundedCornerShape(2.dp)), color = Palette.Accent, trackColor = Palette.Track, drawStopIndicator = {})
                    }
                    Spacer(Modifier.width(10.dp))
                    Text(formatBytes(bytes), color = Palette.Text2, fontSize = 13.sp)
                }
            }
        }
        Text(L.t("Считается трафик через VPN; то, что идёт напрямую по маршрутам, сюда не входит."),
            color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 4.dp))
        Spacer(Modifier.height(24.dp))
    }
}

private fun appLabel(context: android.content.Context, pkg: String): String = when {
    pkg == "?" -> L.t("Не определено")
    pkg.startsWith("uid:") -> L.t("Система") + " (" + pkg.removePrefix("uid:") + ")"
    else -> runCatching { context.packageManager.getApplicationLabel(context.packageManager.getApplicationInfo(pkg, 0)).toString() }.getOrDefault(pkg)
}

@Composable
private fun TrafficIcon(pkg: String) {
    val context = LocalContext.current
    val icon by produceState<ImageBitmap?>(null, pkg) {
        value = withContext(Dispatchers.IO) {
            runCatching { context.packageManager.getApplicationIcon(pkg).toBitmap(96, 96).asImageBitmap() }.getOrNull()
        }
    }
    val bitmap = icon
    if (bitmap != null) Image(bitmap, null, Modifier.size(30.dp).clip(RoundedCornerShape(8.dp)))
    else Box(Modifier.size(30.dp).clip(RoundedCornerShape(8.dp)).background(Palette.Track))
}

// ── Резервная копия ──

@Composable
fun BackupScreen(model: AppModel, modifier: Modifier, onBack: () -> Unit) {
    val context = LocalContext.current
    var includeHwid by remember { mutableStateOf(true) }
    var protect by remember { mutableStateOf(true) }
    var password by remember { mutableStateOf("") }
    var pendingRestore by remember { mutableStateOf<ByteArray?>(null) }
    var askPassword by remember { mutableStateOf(false) }
    var restorePassword by remember { mutableStateOf("") }
    var passwordError by remember { mutableStateOf("") }
    var confirmRestore by remember { mutableStateOf(false) }

    val saver = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/octet-stream")) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        runCatching {
            val bytes = model.exportBackup(includeHwid, if (protect) password else null)
            context.contentResolver.openOutputStream(uri, "wt")!!.use { it.write(bytes) }
        }.onSuccess { model.message(L.t("Резервная копия сохранена.")) }
            .onFailure { model.message(L.t("Не удалось сохранить файл.")) }
    }
    val opener = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        uri ?: return@rememberLauncherForActivityResult
        val bytes = runCatching { context.contentResolver.openInputStream(uri)?.use { it.readBytes() } }.getOrNull()
        if (bytes == null || bytes.size > 8 * 1024 * 1024) { model.message(L.t("Не удалось прочитать файл.")); return@rememberLauncherForActivityResult }
        pendingRestore = bytes
        confirmRestore = true
    }

    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BackTitle(L.t("Резервная копия"), onBack)
        Panel(Modifier.fillMaxWidth()) {
            Column {
                Text(L.t("Что сохраняется"), color = Palette.Text, fontWeight = FontWeight.Medium)
                Text(L.t("Подписки (со ссылками), свои серверы и WireGuard, маршруты, правила, приложения, настройки."),
                    color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(top = 4.dp))
            }
        }
        CardBox {
            ToggleRow(L.t("Сохранить ID устройства"), L.t("Новый телефон займёт то же место у провайдера"), includeHwid) { includeHwid = it }
            RowDivider()
            ToggleRow(L.t("Защитить паролем"), L.t("Ссылки подписок — личные; файл будет зашифрован"), protect) { protect = it }
            if (protect) {
                OutlinedTextField(password, { password = it }, singleLine = true, label = { Text(L.t("Пароль (не меньше 6 символов)")) },
                    visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp))
            }
        }
        val canSave = !protect || password.length >= 6
        SmallButton(L.t("Сохранить в файл"), if (canSave) Palette.Accent else Palette.Track, Palette.Bg, Modifier.fillMaxWidth()) {
            if (canSave) saver.launch("sadness-vpn-${LocalDate.now()}.svpn")
            else model.message(L.t("Пароль — не меньше 6 символов."))
        }
        SmallButton(L.t("Восстановить из файла"), Palette.Surface2, Palette.Text, Modifier.fillMaxWidth()) { opener.launch(arrayOf("*/*")) }
        Text(L.t("Файл .svpn можно перенести на новый телефон или ТВ-приставку. Восстановление заменяет текущие подписки и настройки."),
            color = Palette.Text3, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 4.dp))
        Spacer(Modifier.height(24.dp))
    }

    if (confirmRestore) {
        AlertDialog(onDismissRequest = { confirmRestore = false; pendingRestore = null },
            title = { Text(L.t("Восстановить из копии?")) },
            text = { Text(L.t("Текущие подписки, серверы и настройки будут заменены содержимым файла.")) },
            confirmButton = {
                TextButton(onClick = {
                    confirmRestore = false
                    val bytes = pendingRestore ?: return@TextButton
                    when (val error = model.importBackup(bytes, null)) {
                        null -> pendingRestore = null
                        "need-password" -> askPassword = true
                        else -> { model.message(error); pendingRestore = null }
                    }
                }) { Text(L.t("Восстановить")) }
            },
            dismissButton = { TextButton(onClick = { confirmRestore = false; pendingRestore = null }) { Text(L.t("Отмена")) } })
    }
    if (askPassword) {
        AlertDialog(onDismissRequest = { askPassword = false; pendingRestore = null },
            title = { Text(L.t("Пароль резервной копии")) },
            text = {
                Column {
                    OutlinedTextField(restorePassword, { restorePassword = it; passwordError = "" }, singleLine = true,
                        visualTransformation = PasswordVisualTransformation(), isError = passwordError.isNotEmpty())
                    if (passwordError.isNotEmpty()) Text(passwordError, color = Palette.Danger, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    val bytes = pendingRestore ?: return@TextButton
                    val error = model.importBackup(bytes, restorePassword)
                    if (error == null) { askPassword = false; pendingRestore = null; restorePassword = ""; passwordError = "" } else passwordError = error
                }) { Text(L.t("Восстановить")) }
            },
            dismissButton = { TextButton(onClick = { askPassword = false; pendingRestore = null }) { Text(L.t("Отмена")) } })
    }
}

// ── Отчёт об ошибке ──

@Composable
fun ReportScreen(model: AppModel, modifier: Modifier, onBack: () -> Unit) {
    val context = LocalContext.current
    val report by produceState("…") { value = withContext(Dispatchers.IO) { model.bugReport() } }
    Column(modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BackTitle(L.t("Сообщить об ошибке"), onBack)
        Panel(Modifier.fillMaxWidth()) {
            Column {
                Text(L.t("Что попадёт в отчёт"), color = Palette.Text, fontWeight = FontWeight.Medium)
                Text(L.t("✓ версия приложения и Android, модель телефона\n✓ последние 300 строк журнала ядра\n✓ настройки (без паролей)\n✓ протокол и страна сервера\n✗ адреса серверов, ключи, ссылки подписок, HWID"),
                    color = Palette.Text2, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
            }
        }
        Panel(Modifier.fillMaxWidth()) {
            Box(Modifier.heightIn(max = 320.dp).verticalScroll(rememberScrollState())) {
                Text(report, fontFamily = FontFamily.Monospace, fontSize = 10.sp, color = Palette.Text2)
            }
        }
        SmallButton(L.t("Отправить (Telegram, почта…)"), Palette.Accent, Palette.Bg, Modifier.fillMaxWidth()) {
            context.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_SUBJECT, "Sadness VPN — отчёт об ошибке").putExtra(Intent.EXTRA_TEXT, report), L.t("Отправить отчёт")))
        }
        SmallButton(L.t("Скопировать"), Palette.Surface2, Palette.Text, Modifier.fillMaxWidth()) {
            context.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("report", report))
            model.message(L.t("Отчёт скопирован"))
        }
        Spacer(Modifier.height(24.dp))
    }
}
