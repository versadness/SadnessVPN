package com.sadness.vpn.core

import java.net.URLDecoder
import java.nio.charset.StandardCharsets
import java.util.Base64

/** Сервер подписки — те же поля, что в engine/config.py десктопа. */
typealias Server = MutableMap<String, Any?>

fun Server.str(key: String, default: String = ""): String = this[key]?.toString() ?: default

/** urllib.parse.unquote: проценты раскрываются, «+» остаётся плюсом. */
fun unquote(value: String): String = try {
    URLDecoder.decode(value.replace("+", "%2B"), StandardCharsets.UTF_8.name())
} catch (_: IllegalArgumentException) {
    value
}

/** urllib.parse.parse_qsl: «+» — пробел, пустые значения отбрасываются. */
fun parseQuery(query: String): Map<String, String> {
    val result = LinkedHashMap<String, String>()
    for (part in query.split('&', ';')) {
        if (part.isEmpty()) continue
        val eq = part.indexOf('=')
        if (eq < 0) continue
        val key = decodePlus(part.substring(0, eq))
        val value = decodePlus(part.substring(eq + 1))
        if (value.isNotEmpty()) result[key] = value
    }
    return result
}

private fun decodePlus(value: String): String = try {
    URLDecoder.decode(value, StandardCharsets.UTF_8.name())
} catch (_: IllegalArgumentException) {
    value
}

/** base64.b64decode без строгой проверки: лишние символы отбрасываются, допускается URL-алфавит. */
fun lenientBase64(value: String): ByteArray {
    val clean = value.filter { it.isLetterOrDigit() || it == '+' || it == '/' || it == '-' || it == '_' }
        .replace('-', '+').replace('_', '/')
    val padded = clean + "=".repeat((4 - clean.length % 4) % 4)
    return Base64.getDecoder().decode(padded)
}

fun strictBase64(value: String): ByteArray = Base64.getDecoder().decode(value)

/** Минимальный сериализатор JSON для конфигурации ядра и хранилища. */
object Json {
    fun encode(value: Any?): String = StringBuilder().also { write(it, value) }.toString()

    private fun write(out: StringBuilder, value: Any?) {
        when (value) {
            null -> out.append("null")
            is String -> string(out, value)
            is Boolean -> out.append(value)
            is Int, is Long, is Short, is Byte -> out.append(value)
            is Double -> out.append(if (value % 1.0 == 0.0 && kotlin.math.abs(value) < 1e15) value.toLong().toString() else value.toString())
            is Float -> write(out, value.toDouble())
            is Number -> out.append(value)
            is Map<*, *> -> {
                out.append('{')
                var first = true
                for ((k, v) in value) {
                    if (!first) out.append(',')
                    first = false
                    string(out, k.toString())
                    out.append(':')
                    write(out, v)
                }
                out.append('}')
            }
            is Iterable<*> -> {
                out.append('[')
                var first = true
                for (item in value) {
                    if (!first) out.append(',')
                    first = false
                    write(out, item)
                }
                out.append(']')
            }
            is Array<*> -> write(out, value.asList())
            else -> string(out, value.toString())
        }
    }

    private fun string(out: StringBuilder, value: String) {
        out.append('"')
        for (ch in value) {
            when (ch) {
                '"' -> out.append("\\\"")
                '\\' -> out.append("\\\\")
                '\n' -> out.append("\\n")
                '\r' -> out.append("\\r")
                '\t' -> out.append("\\t")
                else -> if (ch < ' ' || ch == ' ' || ch == ' ') {
                    out.append(String.format("\\u%04x", ch.code))
                } else out.append(ch)
            }
        }
        out.append('"')
    }
}

/** Глубокая копия вложенных Map/List — аналог copy.deepcopy. */
@Suppress("UNCHECKED_CAST")
fun deepCopy(value: Any?): Any? = when (value) {
    is Map<*, *> -> LinkedHashMap<String, Any?>().also { copy -> value.forEach { (k, v) -> copy[k.toString()] = deepCopy(v) } }
    is List<*> -> value.map { deepCopy(it) }.toMutableList()
    else -> value
}

fun printable(value: String): String = buildString {
    var i = 0
    while (i < value.length) {
        val cp = value.codePointAt(i)
        val n = Character.charCount(cp)
        val type = Character.getType(cp)
        val ok = !Character.isISOControl(cp) && type != Character.FORMAT.toInt() &&
            type != Character.UNASSIGNED.toInt() && type != Character.LINE_SEPARATOR.toInt() &&
            type != Character.PARAGRAPH_SEPARATOR.toInt() && type != Character.SURROGATE.toInt() &&
            (type != Character.SPACE_SEPARATOR.toInt() || cp == ' '.code)
        if (ok) appendCodePoint(cp)
        i += n
    }
}
