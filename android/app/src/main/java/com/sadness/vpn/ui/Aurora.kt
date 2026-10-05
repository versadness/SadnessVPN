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
import android.graphics.RenderNode
import android.graphics.RuntimeShader
import android.os.Build
import android.os.PowerManager
import androidx.annotation.RequiresApi
import androidx.compose.foundation.layout.Spacer
import androidx.compose.runtime.State
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.drawscope.drawIntoCanvas
import androidx.compose.ui.graphics.nativeCanvas
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
        "ocean" -> listOf(0xFF04224A, 0xFF1FA2C9, 0xFF2E6BFF, 0xFF7CE0FF)
        "sunset" -> listOf(0xFF3A0C3F, 0xFFFF4F8B, 0xFFFF8A4C, 0xFFFFD36B)
        "neon" -> listOf(0xFF14003A, 0xFFFF2BD6, 0xFF00E5FF, 0xFF7C4DFF)
        else -> when (status) {
        Status.ON -> listOf(0xFF0F8F7A, 0xFF45D6A1, 0xFF1FA2C9, 0xFF2E5BFF)
        Status.CONNECTING, Status.STOPPING -> listOf(0xFF8B7CFF, 0xFFFF6FB1, 0xFF38E0B0, 0xFFFFC25C)
        Status.OFF -> listOf(0xFF2B1F6E, 0xFF5B3BB5, 0xFF1B3F8F, 0xFF8A4FD0)
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
    /** Реальное время для смены сцен — не зависит от трафика. */
    val clock = remember { mutableFloatStateOf(0f) }
    // Экономия: не каждый кадр экрана, а 30 к/с (в покое — 15), в энергосбережении
    // фон замирает. Состояние читается только при рисовании — без перекомпоновки.
    // Когда приложение свёрнуто, часы кадров стоят и анимация не тратит ничего.
    LaunchedEffect(Unit) {
        var last = 0L
        while (true) {
            withFrameNanos { t ->
                if (last != 0L && !power.isPowerSaveMode) {
                    val dt = min((t - last) / 1e9f, 0.1f)
                    phase.floatValue += dt * energy
                    clock.floatValue += dt
                }
                last = t
            }
            delay(if (energy < 0.4f) 66 else 33)
        }
    }
    if (Build.VERSION.SDK_INT >= 33) {
        ShaderAurora(colors, phase, clock, energy, modifier)
        return
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

/** Сцена держится HOLD секунд, затем FADE секунд перетекает в следующую. */
private const val HOLD = 16f
private const val FADE = 5f

/**
 * Android 13+: три сцены-шейдера (жидкий градиент, сияние, перламутр) по кругу.
 * Переход — не простое затухание: новая сцена «протекает» сквозь старую по
 * шумовой маске. Рисуется в слой в 2 раза меньше экрана и растягивается
 * с фильтрацией — картинка мягкая, а пикселей в 4 раза меньше.
 */
@RequiresApi(33)
@Composable
private fun ShaderAurora(colors: List<Color>, phase: State<Float>, clock: State<Float>, energy: Float, modifier: Modifier) {
    val shader = remember { RuntimeShader(AURORA_AGSL) }
    val paint = remember { android.graphics.Paint().apply { this.shader = shader } }
    val node = remember { RenderNode("aurora").apply { setUseCompositingLayer(true, android.graphics.Paint().apply { isFilterBitmap = true }) } }
    Spacer(modifier.drawBehind {
        val w = (size.width / 2f).toInt().coerceAtLeast(1)
        val h = (size.height / 2f).toInt().coerceAtLeast(1)
        val c = clock.value
        val period = HOLD + FADE
        val scene = (c / period).toInt() % 3
        val k = ((c % period - HOLD) / FADE).coerceIn(0f, 1f)
        shader.setFloatUniform("R", w.toFloat(), h.toFloat())
        shader.setFloatUniform("T", phase.value)
        shader.setFloatUniform("E", energy)
        shader.setFloatUniform("A", scene.toFloat())
        shader.setFloatUniform("B", ((scene + 1) % 3).toFloat())
        shader.setFloatUniform("K", k * k * (3 - 2 * k))
        colors.forEachIndexed { i, col -> shader.setFloatUniform("C$i", col.red, col.green, col.blue) }
        node.setPosition(0, 0, w, h)
        val rc = node.beginRecording()
        rc.drawPaint(paint)
        node.endRecording()
        drawIntoCanvas { canvas ->
            val nc = canvas.nativeCanvas
            nc.save()
            nc.scale(size.width / w, size.height / h)
            nc.drawRenderNode(node)
            nc.restore()
        }
    })
}

private const val AURORA_AGSL = """
uniform float2 R; uniform float T; uniform float E; uniform float A; uniform float B; uniform float K;
uniform float3 C0; uniform float3 C1; uniform float3 C2; uniform float3 C3;
float h(float2 p) { return fract(sin(dot(p, float2(127.1, 311.7))) * 43758.5453); }
float n(float2 p) { float2 i = floor(p); float2 f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(h(i), h(i + float2(1, 0)), f.x), mix(h(i + float2(0, 1)), h(i + 1.0), f.x), f.y); }
float fbm(float2 p) { float v = 0.0; float a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * n(p); p = p * 2.03 + float2(1.7, 9.2); a *= 0.5; } return v; }
float3 pal(float x) { x = fract(x) * 4.0;
  return x < 1.0 ? mix(C0, C1, x) : x < 2.0 ? mix(C1, C2, x - 1.0) : x < 3.0 ? mix(C2, C3, x - 2.0) : mix(C3, C0, x - 3.0); }
float3 lava(float2 p) {
  float2 s = p * 1.5; float2 q = float2(fbm(s + T * 0.08), fbm(s - T * 0.1 + 3.0));
  float2 r = float2(fbm(s + 2.2 * q + float2(1.7, 9.2) + T * 0.13), fbm(s + 2.2 * q + float2(8.3, 2.8) - T * 0.11));
  float f = fbm(s + 2.6 * r); float3 c = pal(f * 1.3 + length(q) * 0.4 + T * 0.02);
  c *= 0.25 + 1.25 * f * f; c += pow(max(0.0, f - 0.58), 2.5) * 3.5 * mix(float3(1), C3, 0.4);
  return c * (1.0 - 0.6 * dot(p, p)); }
float3 aurora(float2 p) {
  float3 c = mix(float3(0.01, 0.015, 0.04), C0 * 0.25, smoothstep(-0.6, 0.6, p.y));
  float2 g = floor(p * 150.0); float2 l = fract(p * 150.0) - 0.5; c += step(0.993, h(g)) * h(g + 3.0) * smoothstep(0.45, 0.0, length(l)) * 1.2;
  for (int i = 0; i < 4; i++) { float fi = float(i); float k = fbm(float2(p.x * 1.6 + fi * 3.1, T * 0.12 + fi));
    float cy = 0.18 + 0.22 * k - fi * 0.07; float dy = p.y - cy; float a = dy > 0.0 ? exp(-dy * (3.5 + fi)) : exp(dy * 28.0);
    float st = 0.55 + 0.45 * n(float2(p.x * 38.0 + fi * 13.0 + k * 6.0, T * 0.4));
    c += pal(fi * 0.22 + p.x * 0.25 + 0.15) * a * st * (0.55 + 0.25 * E) * (1.0 - fi * 0.15); }
  return c * (1.0 - 0.35 * dot(p, p)); }
float3 ink(float2 p) {
  float2 s = p * 1.7; float w = fbm(s * 1.3 - T * 0.07); float f = fbm(s + w * 1.8 + float2(T * 0.05, -T * 0.04));
  float3 ir = 0.5 + 0.5 * cos(6.283 * (f * 2.2 + float3(0.0, 0.33, 0.67)) + T * 0.25);
  float3 c = mix(pal(f * 1.5), ir, 0.42) * smoothstep(0.2, 0.75, f) * 1.15; c += pow(max(0.0, f - 0.6), 2.0) * 2.5;
  return c * (1.0 - 0.5 * dot(p, p)); }
float3 scene(float m, float2 p) { return m < 0.5 ? lava(p) : (m < 1.5 ? aurora(p) : ink(p)); }
half4 main(float2 fc) {
  float2 p = (fc - 0.5 * R) / R.y; p.y = -p.y;
  float3 c = scene(A, p);
  if (K > 0.001) {
    float w = clamp((K - fbm(p * 1.8 + T * 0.05) * 0.6) / 0.4, 0.0, 1.0);
    c = mix(c, scene(B, p), w * w * (3.0 - 2.0 * w));
  }
  return half4(half3(max(c, 0.0)), 1.0);
}
"""
