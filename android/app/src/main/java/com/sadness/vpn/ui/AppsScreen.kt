package com.sadness.vpn.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextField
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.graphics.drawable.toBitmap
import com.sadness.vpn.data.AppsMode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
fun AppsScreen(ui: UiState, model: AppModel, modifier: Modifier, onBack: () -> Unit) {
    LaunchedEffect(Unit) { model.loadApps() }
    val settings = ui.data.settings
    var query by remember { mutableStateOf("") }
    var showSystem by remember { mutableStateOf(false) }
    Column(modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BackTitle(L.t("Приложения"), onBack)
        Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(Palette.Field).padding(3.dp)) {
            for ((mode, title) in listOf(AppsMode.ALL to L.t("Все"), AppsMode.ONLY to L.t("Только эти"), AppsMode.EXCEPT to L.t("Кроме этих"))) {
                val on = settings.appsMode == mode
                Text(title, textAlign = TextAlign.Center, fontSize = 13.sp,
                    color = if (on) Palette.Text else Palette.Text3,
                    modifier = Modifier.weight(1f).clip(RoundedCornerShape(10.dp))
                        .background(if (on) Palette.Track else Palette.Field)
                        .clickableTv { model.setAppsMode(mode) }.padding(vertical = 8.dp))
            }
        }
        val hint = when (settings.appsMode) {
            AppsMode.ALL -> L.t("Через VPN идут все приложения.")
            AppsMode.ONLY -> L.t("Через VPN идут только отмеченные: ") + settings.apps.size
            AppsMode.EXCEPT -> L.t("Отмеченные идут напрямую, остальные через VPN. Исключено: ") + settings.apps.size
        }
        Text(hint, color = Palette.Text3, fontSize = 12.sp)
        if (settings.appsMode != AppsMode.ALL) {
            TextField(query, { query = it }, singleLine = true, placeholder = { Text(L.t("Поиск приложений")) },
                leadingIcon = { Icon(Icons.Outlined.Search, null) },
                modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)),
                colors = TextFieldDefaults.colors(focusedContainerColor = Palette.Field, unfocusedContainerColor = Palette.Field,
                    focusedIndicatorColor = Palette.Field, unfocusedIndicatorColor = Palette.Field))
            if (ui.appsLoading) {
                Box(Modifier.fillMaxWidth().padding(24.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = Palette.Accent)
                }
            }
            val q = query.trim().lowercase()
            val list = ui.apps.filter { (showSystem || !it.system || it.pkg in settings.apps) &&
                (q.isEmpty() || q in it.label.lowercase() || q in it.pkg) }
                .sortedBy { it.pkg !in settings.apps }
            LazyColumn(verticalArrangement = Arrangement.spacedBy(2.dp), modifier = Modifier.weight(1f)) {
                items(list, key = { it.pkg }) { app ->
                    Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).clickableTv { model.toggleApp(app.pkg) }
                        .padding(horizontal = 6.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        AppIcon(app.pkg)
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(app.label, color = Palette.Text, maxLines = 1)
                            Text(app.pkg, color = Palette.Text3, fontSize = 11.sp, maxLines = 1)
                        }
                        Switch(checked = app.pkg in settings.apps, onCheckedChange = { model.toggleApp(app.pkg) },
                            colors = SwitchDefaults.colors(checkedTrackColor = Palette.Accent, checkedThumbColor = Palette.Text,
                                uncheckedTrackColor = Palette.Track, uncheckedThumbColor = Palette.Text2, uncheckedBorderColor = Palette.Track))
                    }
                }
                item {
                    Text(if (showSystem) L.t("Скрыть системные") else L.t("Показать системные"), color = Palette.Accent, fontSize = 13.sp,
                        modifier = Modifier.fillMaxWidth().clickableTv { showSystem = !showSystem }.padding(14.dp), textAlign = TextAlign.Center)
                }
            }
        }
    }
}

@Composable
private fun AppIcon(pkg: String) {
    val context = LocalContext.current
    val icon by produceState<ImageBitmap?>(null, pkg) {
        value = withContext(Dispatchers.IO) {
            runCatching { context.packageManager.getApplicationIcon(pkg).toBitmap(96, 96).asImageBitmap() }.getOrNull()
        }
    }
    val bitmap = icon
    if (bitmap != null) Image(bitmap, null, Modifier.size(34.dp).clip(RoundedCornerShape(8.dp)))
    else Box(Modifier.size(34.dp).clip(RoundedCornerShape(8.dp)).background(Palette.Track))
}
