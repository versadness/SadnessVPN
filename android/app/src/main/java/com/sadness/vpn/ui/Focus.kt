package com.sadness.vpn.ui

import android.app.UiModeManager
import android.content.Context
import android.content.res.Configuration
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Рамка фокуса для пульта (Android TV) и клавиатуры. При касании пальцем
 * элементы фокус не получают, поэтому на телефоне рамки не видно.
 */
fun Modifier.tvFocus(): Modifier = composed {
    var focused by remember { mutableStateOf(false) }
    this.onFocusChanged { focused = it.isFocused }
        .border(if (focused) 2.dp else 0.dp, if (focused) Palette.Accent else Color.Transparent, RoundedCornerShape(12.dp))
}

/** clickable с рамкой фокуса — для всех нажимаемых элементов интерфейса. */
fun Modifier.clickableTv(onClick: () -> Unit): Modifier = this.tvFocus().clickable(onClick = onClick)

fun isTv(context: Context): Boolean =
    context.getSystemService(UiModeManager::class.java)?.currentModeType == Configuration.UI_MODE_TYPE_TELEVISION
