package com.sadness.vpn.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import android.os.PowerManager
import kotlinx.coroutines.delay
import com.sadness.vpn.vpn.Status
import kotlin.math.cos
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sin

/**
 * Живой фон главного экрана: большие мягкие пятна цвета плавают и перетекают
 * друг в друга. Гамма зависит от состояния VPN, скорость движения — от трафика.
 * Радиальные градиенты без размытия — одинаково работает на Android 8+.
 */
@Composable
fun Aurora(style: String, status: Status, bytesPerSec: Long, modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val power = remember { context.getSystemService(PowerManager::class.java) }
    val target = when (style) {
        "ocean" -> listOf(0xFF1FA2C9, 0xFF2E6BFF, 0xFF45D6A1, 0xFF173E8C)
        "sunset" -> listOf(0xFFFF7A59, 0xFFFF4F8B, 0xFFF2BD62, 0xFF8B3FB0)
        "neon" -> listOf(0xFFFF2BD6, 0xFF00E5FF, 0xFF8B7CFF, 0xFF39FF88)
        else -> when (status) {
        Status.ON -> listOf(0xFF45D6A1, 0xFF1FA2C9, 0xFF2E6BFF, 0xFF7CE0C3)
        Status.CONNECTING, Status.STOPPING -> listOf(0xFF8B7CFF, 0xFFFF7AB6, 0xFF45D6A1, 0xFFF2BD62)
        Status.OFF -> listOf(0xFF4B3FB0, 0xFF7A4BC8, 0xFF1E4A8E, 0xFF5A2A7A)
        }
    }
    val colors = target.map { animateColorAsState(Color(it), tween(1600), label = "aurora").value }
    val mbit = bytesPerSec * 8 / 1_000_000f
    val energyTarget = when (status) {
        Status.ON -> 0.45f + min(mbit / 15f, 1f) * 1.4f
        Status.CONNECTING, Status.STOPPING -> 1.8f
        Status.OFF -> 0.25f
    }
    val energy by animateFloatAsState(energyTarget, tween(1200), label = "energy")
    val phase = remember { mutableFloatStateOf(0f) }
    // Экономия: не каждый кадр экрана, а 30 к/с (в покое — 15), в энергосбережении
    // фон замирает. Состояние читается только при рисовании — без перекомпоновки.
    // Когда приложение свёрнуто, часы кадров стоят и анимация не тратит ничего.
    LaunchedEffect(Unit) {
        var last = 0L
        while (true) {
            withFrameNanos { t ->
                if (last != 0L && !power.isPowerSaveMode) phase.floatValue += (t - last) / 1e9f * energy
                last = t
            }
            delay(if (energy < 0.4f) 66 else 33)
        }
    }
    val alpha = if (Palette.dark) 0.62f else 0.36f
    val pulse = if (status == Status.CONNECTING) 0.12f else 0.05f
    Canvas(modifier) {
        val p = phase.floatValue
        val base = max(size.width, size.height)
        colors.forEachIndexed { i, c ->
            val k = i * 1.7f
            val center = Offset(
                size.width * (0.5f + 0.42f * sin(p * (0.31f + i * 0.07f) + k)),
                size.height * (0.32f + 0.28f * cos(p * (0.23f + i * 0.05f) + k * 1.3f)),
            )
            val r = base * (0.42f + pulse * sin(p * 1.1f + k))
            drawCircle(Brush.radialGradient(listOf(c.copy(alpha = alpha), c.copy(alpha = alpha * 0.35f), Color.Transparent), center, r), r, center)
        }
    }
}
