package com.sadness.vpn.data

import com.sadness.vpn.core.Json
import org.json.JSONObject
import java.security.SecureRandom
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

/**
 * Резервная копия в файл .svpn. В ней ссылки подписок — по сути личные пароли,
 * поэтому по умолчанию содержимое шифруется: AES-256-GCM, ключ из пароля через
 * PBKDF2-HMAC-SHA256 (200 000 итераций).
 */
object Backup {
    private const val FORMAT = "sadness-vpn-backup"
    private const val ITERATIONS = 200_000

    class WrongPassword : Exception("Неверный пароль резервной копии.")
    class NeedPassword : Exception("Резервная копия защищена паролем.")

    fun export(store: Store, state: State, includeHwid: Boolean, password: String?): ByteArray {
        val payload = store.encode(if (includeHwid) state else state.copy(hwid = "")).toMutableMap()
        val json = Json.encode(payload).toByteArray()
        val root: Map<String, Any?> = if (password.isNullOrEmpty()) {
            linkedMapOf("format" to FORMAT, "version" to 1, "encrypted" to false, "data" to payload)
        } else {
            val salt = ByteArray(16).also(SecureRandom()::nextBytes)
            val iv = ByteArray(12).also(SecureRandom()::nextBytes)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.ENCRYPT_MODE, key(password, salt), GCMParameterSpec(128, iv))
            }
            val b64 = Base64.getEncoder()
            linkedMapOf("format" to FORMAT, "version" to 1, "encrypted" to true, "kdf" to "PBKDF2WithHmacSHA256",
                "iterations" to ITERATIONS, "salt" to b64.encodeToString(salt), "iv" to b64.encodeToString(iv),
                "data" to b64.encodeToString(cipher.doFinal(json)))
        }
        return Json.encode(root).toByteArray()
    }

    fun isEncrypted(bytes: ByteArray): Boolean = runCatching { JSONObject(String(bytes)).optBoolean("encrypted") }.getOrDefault(false)

    /** Прочитать копию; HWID из файла берётся, только если он там есть. */
    fun import(store: Store, bytes: ByteArray, password: String?, current: State): State {
        val root = runCatching { JSONObject(String(bytes)) }.getOrNull()
        if (root == null || root.optString("format") != FORMAT) throw IllegalArgumentException("Это не резервная копия Sadness VPN.")
        val data: JSONObject = if (root.optBoolean("encrypted")) {
            if (password.isNullOrEmpty()) throw NeedPassword()
            val b64 = Base64.getDecoder()
            val iterations = root.optInt("iterations", ITERATIONS)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply {
                init(Cipher.DECRYPT_MODE, key(password, b64.decode(root.getString("salt")), iterations),
                    GCMParameterSpec(128, b64.decode(root.getString("iv"))))
            }
            val plain = try { cipher.doFinal(b64.decode(root.getString("data"))) } catch (_: javax.crypto.AEADBadTagException) { throw WrongPassword() }
            JSONObject(String(plain))
        } else {
            root.getJSONObject("data")
        }
        val restored = store.decode(data)
        return if (restored.hwid.isEmpty()) restored.copy(hwid = current.hwid) else restored
    }

    private fun key(password: String, salt: ByteArray, iterations: Int = ITERATIONS): SecretKeySpec {
        val spec = PBEKeySpec(password.toCharArray(), salt, iterations, 256)
        val bytes = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
        return SecretKeySpec(bytes, "AES")
    }
}
