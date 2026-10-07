package com.sadness.vpn

import com.sadness.vpn.data.RuApps
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RuAppsTest {
    @Test fun russianAppsAreRecommended() {
        listOf("ru.sberbankmobile", "ru.ozon.app.android", "com.wildberries.ru", "ru.yandex.yandexmaps",
            "com.vkontakte.android", "ru.oneme.app", "com.idamob.tinkoff.android", "ru.rostel").forEach {
            assertTrue(it, RuApps.isRecommended(it))
        }
    }

    @Test fun foreignAndVpnNeedingAppsStayInVpn() {
        listOf("org.telegram.messenger", "com.google.android.youtube", "com.discord", "ru.radolyn.ayugram",
            "com.instagram.android", "com.russian.fake").forEach {
            assertFalse(it, RuApps.isRecommended(it))
        }
    }
}
