package com.sadness.vpn.core

import com.sadness.vpn.ui.Updates
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Разбор настоящего ответа GitHub API (снимок в test/resources/releases.json). */
class UpdatesTest {
    private val body = javaClass.getResource("/releases.json")!!.readText()

    @Test fun findsNewestAndroidReleaseForTheAbi() {
        val info = Updates.parse(body, "arm64", "1.0.0")!!
        assertEquals("1.1.0", info.version)
        assertTrue(info.name.endsWith("-arm64.apk"))
        assertEquals(64, info.sha256.length)
        assertTrue(info.notes.isNotEmpty())
        assertTrue(info.url.startsWith("https://github.com/"))
        assertEquals("1.1.0", Updates.parse(body, "armv7", "1.0.0")!!.version)
    }

    @Test fun noUpdateWhenCurrentIsNewestOrNoApk() {
        assertNull(Updates.parse(body, "arm64", "1.1.0"))
        assertNull(Updates.parse(body, "arm64", "1.2.0"))
        assertNull(Updates.parse(body, "mips", "1.0.0"))
    }

    @Test fun versionsCompareNumerically() {
        assertTrue(Updates.newer("1.10.0", "1.9.9"))
        assertTrue(Updates.newer("1.2.0", "1.1.0-beta"))
        assertTrue(!Updates.newer("1.1.0", "1.1.0"))
    }
}
