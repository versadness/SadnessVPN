package com.sadness.vpn.data

import android.content.Context
import android.content.Intent

/**
 * Российские приложения, которые плохо работают через VPN (банки, госуслуги,
 * маркетплейсы, операторы): они видят зарубежный адрес и блокируют вход или
 * тормозят. «Рекомендуемые исключения» пускают их напрямую.
 *
 * Распознаём по имени пакета: всё с префиксом ru. и известные российские
 * пакеты с другими префиксами. Отдельные приложения пользователь может вернуть
 * в VPN — они хранятся в Settings.recommendedOff.
 */
object RuApps {
    private val PREFIXES = listOf(
        "ru.", "com.yandex.", "com.vkontakte.", "com.vk.", "com.wildberries.", "com.avito.",
        "com.idamob.tinkoff.", "com.alfabank.", "com.sberbank.", "com.gosuslugi.", "com.mts.",
        "com.kinopoisk.", "com.ozon.", "com.megafon.", "com.beeline.", "com.tele2.",
    )
    private val KNOWN = setOf(
        "com.wildberries.ru", "com.avito.android", "com.vkontakte.android", "com.vk.vkvideo",
        "com.yandex.browser", "com.idamob.tinkoff.android", "com.kaspersky.who_calls",
        "com.punicapp.whoosh", "com.deliveryclub", "com.sbermarket.client", "com.citymobil",
        "com.sportmaster.app", "com.hh.android", "com.lamoda.lite", "com.hoff.app",
        "com.drivee.passenger", "com.ivi.client", "com.okko.android", "com.dodopizza.app",
    )
    /** Приложения с подходящим пакетом, которым VPN как раз нужен. */
    private val NEVER = setOf("ru.radolyn.ayugram", "ru.nekogram.android")

    fun isRecommended(pkg: String): Boolean =
        pkg !in NEVER && (pkg in KNOWN || PREFIXES.any { pkg.startsWith(it) })

    /** Установленные приложения с иконкой, подходящие под рекомендацию. */
    fun installed(context: Context, off: Set<String>): List<String> {
        val pm = context.packageManager
        val launcher = listOf(Intent.CATEGORY_LAUNCHER, Intent.CATEGORY_LEANBACK_LAUNCHER).flatMap { cat ->
            runCatching { pm.queryIntentActivities(Intent(Intent.ACTION_MAIN).addCategory(cat), 0) }.getOrDefault(emptyList())
                .map { it.activityInfo.packageName }
        }.toSet()
        return launcher.filter { it != context.packageName && it !in off && isRecommended(it) }
    }
}
