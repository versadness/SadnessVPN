package com.sadness.vpn.ui

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/**
 * Перевод интерфейса. Исходный текст — русский; для английского берётся из
 * словаря Strings.EN, а если строки там нет — остаётся русской (не пустой).
 * lang — состояние Compose: смена языка перерисовывает интерфейс сразу.
 */
object L {
    var lang by mutableStateOf("ru")

    fun t(ru: String): String = if (lang == "en") Strings.EN[ru] ?: ru else ru

    /** Склонение: 1 день, 2 дня, 5 дней / 1 day, 2 days. */
    fun plural(n: Long, one: String, few: String, many: String): String = t(
        if (lang == "en") (if (n == 1L) one else many) else {
            val m10 = n % 10; val m100 = n % 100
            when {
                m10 == 1L && m100 != 11L -> one
                m10 in 2..4 && m100 !in 12..14 -> few
                else -> many
            }
        }
    )
}
