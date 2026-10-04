package com.sadness.vpn.ui

import android.Manifest
import android.app.Activity
import android.content.pm.PackageManager
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.graphics.Color
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
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material.icons.outlined.RssFeed
import androidx.compose.ui.Alignment
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.sp
import com.sadness.vpn.vpn.Status
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Apps
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle

class MainActivity : ComponentActivity() {
    private val model: AppModel by viewModels()

    // Разрешение на VPN система спрашивает один раз; дальше prepare() возвращает null.
    private val vpnPermission = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (result.resultCode == Activity.RESULT_OK) model.connect()
        else model.message("Без разрешения Android не даст создать VPN.")
    }
    private val notificationPermission = registerForActivityResult(ActivityResultContracts.RequestPermission()) { }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Интерфейс всегда тёмный — значки строки состояния светлые.
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.dark(Color.TRANSPARENT),
        )
        setContent {
            SadnessTheme { App(model, onConnect = ::requestConnect) }
        }
        // «Подключаться при запуске»: только при холодном старте и если разрешение
        // на VPN уже выдано — без системных окон поверх только что открытого приложения.
        if (savedInstanceState == null && model.ui.value.data.settings.connectOnLaunch &&
            model.vpn.value.status == Status.OFF && model.ui.value.data.selected() != null &&
            VpnService.prepare(this) == null) {
            model.connect()
        }
    }

    private fun requestConnect() {
        if (Build.VERSION.SDK_INT >= 33 &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            notificationPermission.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        val intent = VpnService.prepare(this)
        if (intent != null) vpnPermission.launch(intent) else model.connect()
    }
}

private data class Tab(val title: String, val icon: ImageVector)

private val TABS = listOf(
    Tab("Главная", Icons.Outlined.Home),
    Tab("Серверы", Icons.Outlined.Dns),
    Tab("Прилож.", Icons.Outlined.Apps),
    Tab("Подписки", Icons.Outlined.RssFeed),
    Tab("Настройки", Icons.Outlined.Settings),
)

@Composable
fun App(model: AppModel, onConnect: () -> Unit) {
    val ui by model.ui.collectAsStateWithLifecycle()
    val vpn by model.vpn.collectAsStateWithLifecycle()
    var tab by rememberSaveable { mutableIntStateOf(0) }
    val snackbar = remember { SnackbarHostState() }

    LaunchedEffect(ui.message) {
        if (ui.message.isNotEmpty()) {
            snackbar.showSnackbar(ui.message)
            model.clearMessage()
        }
    }

    Box(Modifier.fillMaxSize().background(Palette.Bg)) {
        val modifier = Modifier.fillMaxSize().statusBarsPadding().navigationBarsPadding().padding(bottom = 76.dp)
        when (tab) {
            0 -> HomeScreen(ui, vpn, modifier, onConnect = onConnect, onDisconnect = model::disconnect, onOpenServers = { tab = 1 })
            1 -> ServersScreen(ui, vpn, model, modifier, onOpenSubscriptions = { tab = 3 })
            2 -> AppsScreen(ui, model, modifier)
            3 -> SubscriptionsScreen(ui, model, modifier)
            else -> SettingsScreen(ui, model, modifier)
        }
        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().navigationBarsPadding()) {
            SnackbarHost(snackbar, Modifier.padding(horizontal = 8.dp)) { data ->
                Snackbar(data, containerColor = Palette.Surface2, contentColor = Palette.Text, shape = RoundedCornerShape(12.dp))
            }
            FloatingNav(tab) { tab = it }
        }
    }
}

/** Плавающая нижняя панель — скруглённая, с отступом от краёв. */
@Composable
private fun FloatingNav(selected: Int, onSelect: (Int) -> Unit) {
    Row(
        Modifier.padding(horizontal = 10.dp, vertical = 8.dp).fillMaxWidth()
            .clip(RoundedCornerShape(22.dp)).background(Palette.Field)
            .border(1.dp, Palette.Border, RoundedCornerShape(22.dp)).padding(horizontal = 4.dp, vertical = 6.dp),
        horizontalArrangement = Arrangement.SpaceAround,
    ) {
        TABS.forEachIndexed { index, item ->
            val on = index == selected
            Column(
                Modifier.weight(1f).clip(RoundedCornerShape(14.dp))
                    .background(if (on) Palette.AccentSoft else Palette.Field)
                    .clickable { onSelect(index) }.padding(vertical = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(item.icon, contentDescription = item.title, tint = if (on) Palette.Accent else Palette.Text3, modifier = Modifier.size(22.dp))
                Text(item.title, fontSize = 10.sp, color = if (on) Palette.Accent else Palette.Text3, maxLines = 1)
            }
        }
    }
}
