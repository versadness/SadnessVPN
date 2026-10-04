package com.sadness.vpn.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/**
 * Палитра десктопной версии (ui/static/css/redesign.css) и её светлый вариант.
 * Цвета читаются из состояния Compose — смена темы перерисовывает интерфейс сразу.
 */
object Palette {
    /** "dark" | "light" | "system". */
    var mode by mutableStateOf("dark")
    /** Тёмная ли сейчас системная тема (обновляет SadnessTheme). */
    var systemDark by mutableStateOf(true)
    val dark: Boolean get() = mode == "dark" || (mode == "system" && systemDark)

    fun apply(theme: String) { mode = theme }

    private fun pick(dark: Long, light: Long) = Color(if (this.dark) dark else light)

    val Bg get() = pick(0xFF080A0F, 0xFFF4F6F9)
    val Surface get() = pick(0xFF181C26, 0xFFFFFFFF)
    val Surface2 get() = pick(0xFF1F2430, 0xFFEEF1F5)
    val Field get() = pick(0xFF151922, 0xFFE9ECF1)
    val Border get() = pick(0x14FFFFFF, 0x1F0B1220)
    val Text get() = pick(0xFFF5F6FA, 0xFF141821)
    val Text2 get() = pick(0xFFAEB4C3, 0xFF454D5E)
    val Text3 get() = pick(0xFF9199AD, 0xFF687083)
    val Accent get() = pick(0xFF45D6A1, 0xFF13976D)
    val AccentSoft get() = pick(0x1A45D6A1, 0x1F13976D)
    val Warn get() = pick(0xFFF2BD62, 0xFFB67608)
    val Danger get() = pick(0xFFFF6F7D, 0xFFD32F45)
    val Purple get() = pick(0xFF8B7CFF, 0xFF6B5CE6)
    val Track get() = pick(0xFF2A3040, 0xFFD3D8E1)
}

@Composable
fun SadnessTheme(content: @Composable () -> Unit) {
    Palette.systemDark = isSystemInDarkTheme()
    val scheme = if (Palette.dark) darkColorScheme(
        primary = Palette.Accent, onPrimary = Palette.Bg, secondary = Palette.Purple,
        background = Palette.Bg, onBackground = Palette.Text, surface = Palette.Surface, onSurface = Palette.Text,
        surfaceVariant = Palette.Surface2, onSurfaceVariant = Palette.Text2, outline = Palette.Border, error = Palette.Danger,
    ) else lightColorScheme(
        primary = Palette.Accent, onPrimary = Color.White, secondary = Palette.Purple,
        background = Palette.Bg, onBackground = Palette.Text, surface = Palette.Surface, onSurface = Palette.Text,
        surfaceVariant = Palette.Surface2, onSurfaceVariant = Palette.Text2, outline = Palette.Border, error = Palette.Danger,
    )
    MaterialTheme(colorScheme = scheme, content = content)
}

fun pingColor(ms: Int?): Color = when {
    ms == null -> Palette.Text3
    ms < 0 -> Palette.Danger
    ms < 120 -> Palette.Accent
    else -> Palette.Warn
}

fun formatBytes(bytes: Long): String {
    fun trim(value: Double, digits: Int) = "%.${digits}f".format(java.util.Locale.ROOT, value)
        .let { if ('.' in it) it.trimEnd('0').trimEnd('.') else it }.replace('.', if (L.lang == "en") '.' else ',')
    return when {
        bytes < 1024 -> "$bytes " + L.t("Б")
        bytes < 1024L * 1024 -> trim(bytes / 1024.0, 0) + " " + L.t("КБ")
        bytes < 1024L * 1024 * 1024 -> trim(bytes / 1024.0 / 1024, 1) + " " + L.t("МБ")
        else -> trim(bytes / 1024.0 / 1024 / 1024, 2) + " " + L.t("ГБ")
    }
}

fun formatSpeed(bytesPerSec: Long): String {
    val mbit = bytesPerSec * 8 / 1_000_000.0
    return if (mbit >= 10) "%.0f".format(mbit) else "%.1f".format(mbit).replace('.', ',')
}

fun formatDuration(ms: Long): String {
    val s = ms / 1000
    return "%02d:%02d:%02d".format(s / 3600, s / 60 % 60, s % 60)
}

/** Флаг из названия сервера или нейтральный значок. */
fun flagOf(remark: String): String {
    val sb = StringBuilder()
    var i = 0
    while (i < remark.length) {
        val cp = remark.codePointAt(i)
        if (cp in 0x1F1E6..0x1F1FF) sb.appendCodePoint(cp) else if (sb.isNotEmpty()) break
        if (sb.codePointCount(0, sb.length) == 2) return sb.toString()
        i += Character.charCount(cp)
    }
    return "🌐"
}

/** Название без флага в начале — флаг показывается отдельно. */
fun cleanRemark(remark: String): String {
    var i = 0
    while (i < remark.length) {
        val cp = remark.codePointAt(i)
        if (cp in 0x1F1E6..0x1F1FF || Character.isWhitespace(cp)) i += Character.charCount(cp) else break
    }
    return remark.substring(i).ifEmpty { remark }
}
