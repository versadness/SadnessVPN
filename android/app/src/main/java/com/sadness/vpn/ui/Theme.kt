package com.sadness.vpn.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

/** Палитра десктопной версии (ui/static/css/redesign.css). */
object Palette {
    val Bg = Color(0xFF080A0F)
    val Surface = Color(0xFF181C26)
    val Surface2 = Color(0xFF1F2430)
    val Field = Color(0xFF151922)
    val Border = Color(0x14FFFFFF)
    val Text = Color(0xFFF5F6FA)
    val Text2 = Color(0xFFAEB4C3)
    val Text3 = Color(0xFF9199AD)
    val Accent = Color(0xFF45D6A1)
    val AccentSoft = Color(0x1A45D6A1)
    val Warn = Color(0xFFF2BD62)
    val Danger = Color(0xFFFF6F7D)
    val Purple = Color(0xFF8B7CFF)
    val Track = Color(0xFF2A3040)
}

@Composable
fun SadnessTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = darkColorScheme(
            primary = Palette.Accent,
            onPrimary = Palette.Bg,
            secondary = Palette.Purple,
            background = Palette.Bg,
            onBackground = Palette.Text,
            surface = Palette.Surface,
            onSurface = Palette.Text,
            surfaceVariant = Palette.Surface2,
            onSurfaceVariant = Palette.Text2,
            outline = Palette.Border,
            error = Palette.Danger,
        ),
        content = content,
    )
}

fun pingColor(ms: Int?): Color = when {
    ms == null -> Palette.Text3
    ms < 0 -> Palette.Danger
    ms < 120 -> Palette.Accent
    else -> Palette.Warn
}

fun formatBytes(bytes: Long): String {
    fun trim(value: Double, digits: Int) = "%.${digits}f".format(java.util.Locale.ROOT, value)
        .let { if ('.' in it) it.trimEnd('0').trimEnd('.') else it }.replace('.', ',')
    return when {
        bytes < 1024 -> "$bytes Б"
        bytes < 1024L * 1024 -> trim(bytes / 1024.0, 0) + " КБ"
        bytes < 1024L * 1024 * 1024 -> trim(bytes / 1024.0 / 1024, 1) + " МБ"
        else -> trim(bytes / 1024.0 / 1024 / 1024, 2) + " ГБ"
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
