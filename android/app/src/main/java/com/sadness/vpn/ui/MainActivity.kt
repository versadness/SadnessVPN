package com.sadness.vpn.ui

import android.Manifest
import android.app.Activity
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Color
import android.net.Uri
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings as AndroidSettings
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.AltRoute
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.RssFeed
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color as CColor
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.journeyapps.barcodescanner.ScanContract
import com.journeyapps.barcodescanner.ScanOptions
import com.sadness.vpn.vpn.Status
import com.sadness.vpn.vpn.VpnToggle
import java.io.File

class MainActivity : ComponentActivity() {
    private val model: AppModel by viewModels()
    private var batteryRestricted by mutableStateOf(false)

    // Разрешение на VPN система спрашивает один раз; дальше prepare() возвращает null.
    private val vpnPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) model.connect()
        else model.message(L.t("Без разрешения Android не даст создать VPN."))
    }
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }
    private val qrScanner = registerForActivityResult(ScanContract()) { result ->
        result.contents?.let { model.importText(it) }
    }
    private val confPicker = registerForActivityResult(ActivityResultContracts.GetContent()) { uri ->
        uri ?: return@registerForActivityResult
        val name = runCatching {
            contentResolver.query(uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null)?.use { c ->
                if (c.moveToFirst()) c.getString(0) else null
            }
        }.getOrNull().orEmpty()
        val text = runCatching { contentResolver.openInputStream(uri)?.use { it.readBytes().take(256 * 1024).toByteArray().decodeToString() } }.getOrNull()
        if (text.isNullOrBlank()) model.message(L.t("Не удалось прочитать файл.")) else model.importText(text, name)
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        applySystemBars()
        setContent {
            SadnessTheme {
                LaunchedEffect(Palette.dark) { applySystemBars() }
                App(model, batteryRestricted,
                    onConnect = ::requestConnect,
                    onFixBattery = ::fixBattery,
                    onScanQr = ::scanQr,
                    onPickFile = { confPicker.launch("*/*") },
                    readClipboard = ::clipboardText,
                    onInstall = ::installUpdate)
            }
        }
        if (savedInstanceState == null) handleIntent(intent)
        // «Подключаться при запуске»: только при холодном старте и если разрешение
        // на VPN уже выдано — без системных окон поверх только что открытого приложения.
        if (savedInstanceState == null && model.ui.value.data.settings.connectOnLaunch &&
            model.vpn.value.status == Status.OFF && model.ui.value.data.selected() != null &&
            VpnService.prepare(this) == null) {
            model.connect()
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handleIntent(intent)
    }

    override fun onResume() {
        super.onResume()
        batteryRestricted = !getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName)
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        // Android 10+ отдаёт буфер обмена только приложению в фокусе.
        if (hasFocus) model.offerClipboard(clipboardText())
    }

    private fun applySystemBars() {
        val style = if (Palette.dark) SystemBarStyle.dark(Color.TRANSPARENT) else SystemBarStyle.light(Color.TRANSPARENT, Color.TRANSPARENT)
        enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
    }

    /** Ссылки vless://, hy2://, sadnessvpn://, «Поделиться» и запуск из шторки/виджета. */
    private fun handleIntent(intent: Intent?) {
        when (intent?.action) {
            Intent.ACTION_VIEW -> intent.dataString?.let { model.importText(it) }
            Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)?.let { model.importText(it) }
            VpnToggle.ACTION_CONNECT -> if (model.vpn.value.status == Status.OFF) requestConnect()
            // Только в отладочной сборке: разовый запуск фонового обновления подписок для проверки.
            "com.sadness.vpn.DEBUG_RUN_WORK" -> if (com.sadness.vpn.BuildConfig.DEBUG) {
                androidx.work.WorkManager.getInstance(this).enqueue(
                    androidx.work.OneTimeWorkRequestBuilder<com.sadness.vpn.data.SubscriptionWork>().build())
            }
        }
    }

    private fun clipboardText(): String? = runCatching {
        getSystemService(ClipboardManager::class.java).primaryClip?.takeIf { it.itemCount > 0 }?.getItemAt(0)?.coerceToText(this)?.toString()
    }.getOrNull()

    private fun scanQr() {
        qrScanner.launch(ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setBeepEnabled(false)
            .setOrientationLocked(true).setPrompt(L.t("Наведите камеру на QR-код подписки или сервера")))
    }

    private fun requestConnect() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        val intent = VpnService.prepare(this)
        if (intent != null) vpnPermission.launch(intent) else model.connect()
    }

    /**
     * Снять фоновые ограничения: системный запрос «без ограничений батареи»,
     * а на Xiaomi/HyperOS — ещё и экран автозапуска. Включает пользователь сам.
     */
    private fun fixBattery() {
        val power = getSystemService(PowerManager::class.java)
        if (!power.isIgnoringBatteryOptimizations(packageName)) {
            runCatching {
                startActivity(Intent(AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
            }.onFailure { runCatching { startActivity(Intent(AndroidSettings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)) } }
        }
        if (Build.MANUFACTURER.lowercase() in setOf("xiaomi", "redmi", "poco")) {
            runCatching {
                startActivity(Intent().setComponent(ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity")))
            }
        }
    }

    /** Отдать скачанный APK установщику Android (разрешение «из этого источника» — один раз). */
    private fun installUpdate(file: File) {
        if (Build.VERSION.SDK_INT >= 26 && !packageManager.canRequestPackageInstalls()) {
            model.message(L.t("Разрешите установку из Sadness VPN и нажмите «Обновить» ещё раз."))
            startActivity(Intent(AndroidSettings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:$packageName")))
            return
        }
        val uri = FileProvider.getUriForFile(this, "$packageName.files", file)
        startActivity(Intent(Intent.ACTION_VIEW).setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}

private data class Tab(val title: String, val icon: ImageVector)

@Composable
fun App(model: AppModel, batteryRestricted: Boolean, onConnect: () -> Unit, onFixBattery: () -> Unit, onScanQr: () -> Unit,
        onPickFile: () -> Unit, readClipboard: () -> String?, onInstall: (File) -> Unit) {
    val ui by model.ui.collectAsStateWithLifecycle()
    val vpn by model.vpn.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    val snackbar = remember { SnackbarHostState() }
    val tabs = listOf(
        Tab(L.t("Главная"), Icons.Outlined.Home),
        Tab(L.t("Серверы"), Icons.Outlined.Dns),
        Tab(L.t("Маршруты"), Icons.Outlined.AltRoute),
        Tab(L.t("Подписки"), Icons.Outlined.RssFeed),
        Tab(L.t("Настройки"), Icons.Outlined.Settings),
    )

    LaunchedEffect(ui.message) {
        if (ui.message.isNotEmpty()) {
            snackbar.showSnackbar(ui.message)
            model.clearMessage()
        }
    }
    // Ссылка, открытая из Telegram, сразу показывает подписки.
    LaunchedEffect(ui.data.groups.size) { if (ui.data.groups.isNotEmpty() && ui.data.selected() == null) tab = 3 }

    val context = androidx.compose.ui.platform.LocalContext.current
    val config = androidx.compose.ui.platform.LocalConfiguration.current
    // Планшет, раскладушка в раскрытом виде, Android TV: вкладки сбоку, на главной — две колонки.
    val wide = config.screenWidthDp >= 720 || isTv(context)
    if (wide) {
        WideLayout(ui, vpn, model, tabs, tab, { tab = it }, snackbar, batteryRestricted, onConnect, onFixBattery, onScanQr, onPickFile, readClipboard)
        ui.update?.let { info -> UpdateDialog(info, ui.updateProgress, model, onInstall) }
        return
    }

    Box(Modifier.fillMaxSize().background(Palette.Bg)) {
        val modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(bottom = 76.dp)
        when (tab) {
            0 -> HomeScreen(ui, vpn, model, Modifier.fillMaxSize(), batteryRestricted, onFixBattery, onConnect, onOpenServers = { tab = 1 })
            1 -> ServersScreen(ui, vpn, model, modifier, onOpenSubscriptions = { tab = 3 })
            2 -> RoutesScreen(ui, model, modifier)
            3 -> SubscriptionsScreen(ui, model, modifier, onScanQr, onPickFile, readClipboard)
            else -> SettingsScreen(ui, model, modifier)
        }
        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().navigationBarsPadding()) {
            SnackbarHost(snackbar, Modifier.padding(horizontal = 8.dp)) { data ->
                Snackbar(data, containerColor = Palette.Surface2, contentColor = Palette.Text, shape = RoundedCornerShape(12.dp))
            }
            FloatingNav(tabs, tab, glass = tab == 0) { tab = it }
        }
    }

    ui.update?.let { info -> UpdateDialog(info, ui.updateProgress, model, onInstall) }
}

@Composable
private fun UpdateDialog(info: UpdateInfo, progress: Int, model: AppModel, onInstall: (File) -> Unit) {
    AlertDialog(
        onDismissRequest = { if (progress < 0) model.dismissUpdate() },
        title = { Text(L.t("Вышла версия ") + info.version, fontWeight = FontWeight.Medium) },
        text = {
            Column {
                info.notes.forEach { Text("• $it", color = Palette.Text2, fontSize = 13.sp, modifier = Modifier.padding(bottom = 4.dp)) }
                Spacer(Modifier.height(6.dp))
                Text("${formatBytes(info.size)} · GitHub · " + L.t("подпись проверяет Android"), color = Palette.Text3, fontSize = 12.sp)
                if (progress >= 0) {
                    Spacer(Modifier.height(10.dp))
                    LinearProgressIndicator(progress = { progress / 100f }, modifier = Modifier.fillMaxWidth(),
                        color = Palette.Accent, trackColor = Palette.Track, drawStopIndicator = {})
                }
            }
        },
        confirmButton = {
            TextButton(onClick = { model.downloadUpdate(onInstall) }, enabled = progress < 0) {
                Text(if (progress >= 0) "$progress%" else L.t("Обновить"), color = Palette.Accent)
            }
        },
        dismissButton = { TextButton(onClick = model::dismissUpdate, enabled = progress < 0) { Text(L.t("Позже")) } },
    )
}

@Composable
private fun WideLayout(ui: UiState, vpn: com.sadness.vpn.vpn.ConnState, model: AppModel, tabs: List<Tab>, tab: Int, onTab: (Int) -> Unit,
                       snackbar: SnackbarHostState, batteryRestricted: Boolean, onConnect: () -> Unit, onFixBattery: () -> Unit,
                       onScanQr: () -> Unit, onPickFile: () -> Unit, readClipboard: () -> String?) {
    Box(Modifier.fillMaxSize().background(Palette.Bg)) {
        Row(Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding()) {
            // Боковая панель вкладок.
            Column(Modifier.width(92.dp).fillMaxSize().background(Palette.Field).padding(vertical = 16.dp),
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(6.dp)) {
                tabs.forEachIndexed { index, item ->
                    val on = index == tab
                    Column(Modifier.width(80.dp).clip(RoundedCornerShape(14.dp)).background(if (on) Palette.AccentSoft else Palette.Field)
                        .clickableTv { onTab(index) }.padding(vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Icon(item.icon, contentDescription = item.title, tint = if (on) Palette.Accent else Palette.Text3, modifier = Modifier.size(24.dp))
                        Text(item.title, fontSize = 11.sp, color = if (on) Palette.Accent else Palette.Text3, maxLines = 1)
                    }
                }
            }
            val content = Modifier.fillMaxSize()
            when (tab) {
                0 -> Row(Modifier.fillMaxSize()) {
                    Box(Modifier.width(420.dp)) {
                        HomeScreen(ui, vpn, model, content, batteryRestricted, onFixBattery, onConnect, onOpenServers = { onTab(1) })
                    }
                    Box(Modifier.weight(1f).fillMaxSize().background(Palette.Field.copy(alpha = 0.35f))) {
                        ServersScreen(ui, vpn, model, content, onOpenSubscriptions = { onTab(3) })
                    }
                }
                else -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.TopCenter) {
                    Box(Modifier.widthIn(max = 760.dp)) {
                        when (tab) {
                            1 -> ServersScreen(ui, vpn, model, content, onOpenSubscriptions = { onTab(3) })
                            2 -> RoutesScreen(ui, model, content)
                            3 -> SubscriptionsScreen(ui, model, content, onScanQr, onPickFile, readClipboard)
                            else -> SettingsScreen(ui, model, content)
                        }
                    }
                }
            }
        }
        SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter).navigationBarsPadding().padding(16.dp)) { data ->
            Snackbar(data, containerColor = Palette.Surface2, contentColor = Palette.Text, shape = RoundedCornerShape(12.dp))
        }
    }
}

/** Плавающая нижняя панель — скруглённая, с отступом от краёв. */
@Composable
private fun FloatingNav(tabs: List<Tab>, selected: Int, glass: Boolean = false, onSelect: (Int) -> Unit) {
    val bg = if (glass) CColor.Black.copy(alpha = 0.22f) else Palette.Field
    Row(
        Modifier.padding(horizontal = 10.dp, vertical = 8.dp).fillMaxWidth()
            .clip(RoundedCornerShape(22.dp)).background(bg)
            .border(1.dp, if (glass) CColor.White.copy(alpha = 0.08f) else Palette.Border, RoundedCornerShape(22.dp)).padding(horizontal = 4.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceAround,
    ) {
        tabs.forEachIndexed { index, item ->
            val on = index == selected
            Column(
                Modifier.weight(1f).clip(RoundedCornerShape(14.dp))
                    .background(if (on) (if (glass) CColor.White.copy(alpha = 0.14f) else Palette.AccentSoft) else CColor.Transparent)
                    .clickableTv { onSelect(index) }.padding(vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(item.icon, contentDescription = item.title, tint = if (on) (if (glass) CColor.White else Palette.Accent) else if (glass) CColor.White.copy(alpha = 0.7f) else Palette.Text3, modifier = Modifier.size(22.dp))
                Text(item.title, fontSize = 10.sp, color = if (on) (if (glass) CColor.White else Palette.Accent) else if (glass) CColor.White.copy(alpha = 0.7f) else Palette.Text3, maxLines = 1)
            }
        }
    }
}
