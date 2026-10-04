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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Apps
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
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
    Tab("Приложения", Icons.Outlined.Apps),
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
    LaunchedEffect(vpn.error) {
        if (vpn.error.isNotEmpty()) snackbar.showSnackbar(vpn.error)
    }

    Scaffold(
        containerColor = Palette.Bg,
        snackbarHost = {
            SnackbarHost(snackbar) { data ->
                Snackbar(data, containerColor = Palette.Surface2, contentColor = Palette.Text, shape = RoundedCornerShape(12.dp))
            }
        },
        bottomBar = {
            NavigationBar(containerColor = Palette.Bg, tonalElevation = 0.dp) {
                TABS.forEachIndexed { index, item ->
                    NavigationBarItem(
                        selected = tab == index,
                        onClick = { tab = index },
                        icon = { Icon(item.icon, contentDescription = item.title) },
                        label = { Text(item.title) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Palette.Accent, selectedTextColor = Palette.Accent,
                            unselectedIconColor = Palette.Text3, unselectedTextColor = Palette.Text3,
                            indicatorColor = Palette.AccentSoft,
                        ),
                    )
                }
            }
        },
    ) { padding ->
        val modifier = Modifier.padding(padding)
        when (tab) {
            0 -> HomeScreen(ui, vpn, modifier, onConnect = onConnect, onDisconnect = model::disconnect, onOpenServers = { tab = 1 })
            1 -> ServersScreen(ui, vpn, model, modifier)
            2 -> AppsScreen(ui, model, modifier)
            else -> SettingsScreen(ui, model, modifier)
        }
    }
}
