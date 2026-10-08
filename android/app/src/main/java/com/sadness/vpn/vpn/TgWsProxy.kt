package com.sadness.vpn.vpn

import android.util.Log
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import javax.crypto.Cipher
import javax.crypto.spec.IvParameterSpec
import javax.crypto.spec.SecretKeySpec
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLSocket
import javax.net.ssl.SSLSocketFactory

/**
 * Telegram WS Proxy — локальный MTProto-прокси, как в ПК-версии (порт Flowseal/tg-ws-proxy, MIT).
 *
 * Telegram подключается к 127.0.0.1, прокси расшифровывает obfuscated2-рукопожатие, узнаёт
 * дата-центр и ведёт трафик к Telegram через WebSocket (kws*.web.telegram.org). Если WebSocket
 * недоступен — через Cloudflare-домены проекта, в крайнем случае напрямую по TCP.
 * Приложение исключено из VPN, поэтому прокси ходит мимо туннеля: Telegram работает,
 * даже когда до VPN-сервера не достучаться.
 */
object TgWsProxy {
    const val PORT = 1443
    private const val TAG = "tg-ws-proxy"
    private const val WS_PATH = "/apiws"
    private const val DC_FAIL_MS = 60_000L

    private val DC_REDIRECTS = mapOf(2 to "149.154.167.220", 4 to "149.154.167.220")
    private val DC_IPS = mapOf(1 to "149.154.175.50", 2 to "149.154.167.51", 3 to "149.154.175.100",
        4 to "149.154.167.91", 5 to "149.154.171.5", 203 to "91.105.192.100")
    private val DC_TEST_IPS = mapOf(1 to "149.154.175.10", 2 to "149.154.167.40", 3 to "149.154.175.117")
    private val CF_DOMAINS = listOf("pclead", "offshor", "cakeisalie", "noskomnadzor", "lovetrue", "sorokdva",
        "pyatdesyatdva", "kartoshka", "sorokodin", "pyatdesyatodin", "notelega", "ebally", "nebally",
        "havegreatday", "pomogite", "fixtelega", "sadnews", "onedaychamp", "stopblocking", "nothingthere")
        .map { "$it.co.uk" }

    private val TAGS = setOf(0xEFEFEFEF.toInt(), 0xEEEEEEEE.toInt(), 0xDDDDDDDD.toInt())
    private const val ABRIDGED = 0xEFEFEFEF.toInt()

    private val rnd = SecureRandom()
    private val exec = Executors.newCachedThreadPool { r -> Thread(r, TAG).apply { isDaemon = true } }
    private val conns: MutableSet<Socket> = ConcurrentHashMap.newKeySet()
    private val dcFailUntil = ConcurrentHashMap<String, Long>()
    private val wsBlacklist: MutableSet<String> = ConcurrentHashMap.newKeySet()
    private val cfActive = ConcurrentHashMap<Int, String>()
    @Volatile private var server: ServerSocket? = null

    val running: Boolean get() = server?.isClosed == false

    fun newSecret(): String = ByteArray(16).also { rnd.nextBytes(it) }.joinToString("") { "%02x".format(it) }

    fun link(secret: String, port: Int = PORT) = "tg://proxy?server=127.0.0.1&port=$port&secret=dd$secret"

    @Synchronized
    fun start(secretHex: String, port: Int = PORT): Boolean {
        if (running) return true
        val secret = hex(secretHex) ?: return false
        val ss = try {
            ServerSocket().apply { reuseAddress = true; bind(InetSocketAddress(InetAddress.getByName("127.0.0.1"), port)) }
        } catch (e: IOException) {
            Log.w(TAG, "port $port busy: $e"); return false
        }
        server = ss
        dcFailUntil.clear(); wsBlacklist.clear()
        Thread({
            while (!ss.isClosed) {
                val c = try { ss.accept() } catch (_: IOException) { break }
                exec.execute { handle(c, secret) }
            }
        }, "$TAG-accept").apply { isDaemon = true }.start()
        Log.i(TAG, "listening on 127.0.0.1:$port")
        return true
    }

    @Synchronized
    fun stop() {
        runCatching { server?.close() }
        server = null
        conns.toList().forEach { runCatching { it.close() } }
        conns.clear()
    }

    // ---- соединение клиента ----

    private class Hs(val dc: Int, val media: Boolean, val tag: ByteArray, val prekeyIv: ByteArray)

    private fun handle(c: Socket, secret: ByteArray) {
        conns.add(c)
        var up: Upstream? = null
        try {
            c.tcpNoDelay = true
            c.soTimeout = 10_000
            val cin = c.getInputStream()
            val init = readN(cin, 64) ?: return
            val hs = parseHandshake(init, secret)
            if (hs == null) {
                Log.w(TAG, "bad handshake (wrong secret)")
                return
            }
            c.soTimeout = 0
            var dc = hs.dc
            val test = dc >= 10000
            if (test) dc -= 10000
            val relay = relayInit(hs.tag, if (hs.media) -dc else dc)
            val ctx = Ctx(hs.prekeyIv, secret, relay)
            val proto = le32(hs.tag, 0)
            up = connect(dc, hs.media, test) ?: run { Log.w(TAG, "DC$dc: no route"); return }
            conns.add(up.socket)
            up.send(relay, relay)
            bridge(cin, c.getOutputStream(), up, ctx, if (up.framed) Splitter(proto) else null)
        } catch (_: IOException) {
        } catch (e: Exception) {
            Log.w(TAG, "session: $e")
        } finally {
            runCatching { c.close() }; conns.remove(c)
            up?.let { runCatching { it.socket.close() }; conns.remove(it.socket) }
        }
    }

    private fun parseHandshake(init: ByteArray, secret: ByteArray): Hs? {
        val prekeyIv = init.copyOfRange(8, 56)
        val key = sha256(prekeyIv.copyOfRange(0, 32), secret)
        val dec = ctr(key, prekeyIv.copyOfRange(32, 48)).update(init)
        val tag = dec.copyOfRange(56, 60)
        if (le32(tag, 0) !in TAGS) return null
        val idx = ((dec[60].toInt() and 0xFF) or (dec[61].toInt() shl 8)).toShort().toInt()
        return Hs(kotlin.math.abs(idx), idx < 0, tag, prekeyIv)
    }

    private fun relayInit(tag: ByteArray, dcIdx: Int): ByteArray {
        val r = ByteArray(64)
        while (true) {
            rnd.nextBytes(r)
            val start = le32(r, 0)
            if (r[0] == 0xEF.toByte()) continue
            if (start in RESERVED_STARTS) continue
            if (r[4] == 0.toByte() && r[5] == 0.toByte() && r[6] == 0.toByte() && r[7] == 0.toByte()) continue
            break
        }
        val enc = ctr(r.copyOfRange(8, 40), r.copyOfRange(40, 56)).update(r)
        val tail = ByteArray(8)
        System.arraycopy(tag, 0, tail, 0, 4)
        tail[4] = dcIdx.toByte(); tail[5] = (dcIdx shr 8).toByte()
        tail[6] = rnd.nextInt().toByte(); tail[7] = rnd.nextInt().toByte()
        for (i in 0 until 8) r[56 + i] = (tail[i].toInt() xor enc[56 + i].toInt() xor r[56 + i].toInt()).toByte()
        return r
    }

    private val RESERVED_STARTS = listOf(
        byteArrayOf(0x48, 0x45, 0x41, 0x44), byteArrayOf(0x50, 0x4F, 0x53, 0x54), byteArrayOf(0x47, 0x45, 0x54, 0x20),
        byteArrayOf(0xee.toByte(), 0xee.toByte(), 0xee.toByte(), 0xee.toByte()),
        byteArrayOf(0xdd.toByte(), 0xdd.toByte(), 0xdd.toByte(), 0xdd.toByte()),
        byteArrayOf(0x16, 0x03, 0x01, 0x02),
    ).map { le32(it, 0) }.toSet()

    /** Шифры: клиент ↔ прокси (ключ с секретом) и прокси ↔ Telegram (обычная обфускация). */
    private class Ctx(prekeyIv: ByteArray, secret: ByteArray, relay: ByteArray) {
        val cltDec: Cipher = ctr(sha256(prekeyIv.copyOfRange(0, 32), secret), prekeyIv.copyOfRange(32, 48))
        val cltEnc: Cipher
        val tgEnc: Cipher = ctr(relay.copyOfRange(8, 40), relay.copyOfRange(40, 56))
        val tgDec: Cipher
        init {
            val rc = prekeyIv.reversedArray()
            cltEnc = ctr(sha256(rc.copyOfRange(0, 32), secret), rc.copyOfRange(32, 48))
            val rr = relay.copyOfRange(8, 56).reversedArray()
            tgDec = ctr(rr.copyOfRange(0, 32), rr.copyOfRange(32, 48))
            cltDec.update(ByteArray(64)); tgEnc.update(ByteArray(64))
        }
    }

    // ---- выбор пути к Telegram ----

    private fun connect(dc: Int, media: Boolean, test: Boolean): Upstream? {
        val key = "$dc${if (test) "t" else ""}${if (media) "m" else ""}"
        val target = DC_REDIRECTS[dc]
        val now = System.currentTimeMillis()
        if (!test && target != null && key !in wsBlacklist && now >= (dcFailUntil[key] ?: 0)) {
            var redirects = 0
            val domains = wsDomains(dc, media)
            for (d in domains) {
                try {
                    return WsUp.open(target, d, 5_000)
                } catch (e: WsRedirect) {
                    redirects++
                } catch (e: Exception) {
                    Log.i(TAG, "DC$dc ws $d: $e")
                    break
                }
            }
            if (redirects == domains.size) wsBlacklist.add(key) else dcFailUntil[key] = now + DC_FAIL_MS
        }
        if (!test) {
            val current = cfActive[dc]
            val order = listOfNotNull(current) + CF_DOMAINS.shuffled().filter { it != current }
            for (base in order.take(6)) {
                val host = "kws$dc.$base"
                try {
                    val ws = WsUp.open(host, host, 8_000)
                    cfActive[dc] = base
                    return ws
                } catch (e: Exception) {
                    Log.i(TAG, "DC$dc cf: $e")
                }
            }
        }
        val ip = (if (test) DC_TEST_IPS else DC_IPS)[dc] ?: return null
        return try {
            TcpUp(Socket().apply { tcpNoDelay = true; connect(InetSocketAddress(ip, 443), 10_000) })
        } catch (e: IOException) {
            Log.i(TAG, "DC$dc tcp: $e"); null
        }
    }

    private fun wsDomains(dc: Int, media: Boolean): List<String> {
        val d = if (dc == 203) 2 else dc
        val a = "kws$d.web.telegram.org"; val b = "kws$d-1.web.telegram.org"
        return if (media) listOf(b, a) else listOf(a, b)
    }

    private fun bridge(cin: InputStream, cout: OutputStream, up: Upstream, ctx: Ctx, splitter: Splitter?) {
        val down = exec.submit {
            try {
                while (true) {
                    val data = up.recv() ?: break
                    if (data.isEmpty()) continue
                    cout.write(ctx.cltEnc.update(ctx.tgDec.update(data)))
                    cout.flush()
                }
            } catch (_: Exception) {
            } finally {
                runCatching { up.socket.close() }
            }
        }
        val buf = ByteArray(65536)
        try {
            while (true) {
                val n = cin.read(buf)
                if (n < 0) break
                if (n == 0) continue
                val plain = ctx.cltDec.update(buf, 0, n)
                val cipher = ctx.tgEnc.update(plain)
                if (splitter == null) up.send(plain, cipher) else splitter.split(plain, cipher).forEach { up.send(it, it) }
            }
            splitter?.flush()?.let { up.send(it, it) }
        } catch (_: Exception) {
        } finally {
            runCatching { up.socket.close() }
            down.cancel(true)
        }
    }

    /** Режет поток на отдельные пакеты MTProto: каждый уходит своим WS-кадром. */
    private class Splitter(private val proto: Int) {
        private var plain = ByteArray(0)
        private var cipher = ByteArray(0)
        private var disabled = false

        fun split(p: ByteArray, c: ByteArray): List<ByteArray> {
            if (disabled) return listOf(c)
            plain += p; cipher += c
            val out = ArrayList<ByteArray>()
            var off = 0
            while (off < cipher.size) {
                val len = next(off, cipher.size - off) ?: break
                if (len <= 0) {
                    out += cipher.copyOfRange(off, cipher.size); off = cipher.size; disabled = true; break
                }
                out += cipher.copyOfRange(off, off + len); off += len
            }
            if (off > 0) { plain = plain.copyOfRange(off, plain.size); cipher = cipher.copyOfRange(off, cipher.size) }
            return out
        }

        fun flush(): ByteArray? = cipher.takeIf { it.isNotEmpty() }?.also { cipher = ByteArray(0); plain = ByteArray(0) }

        private fun next(off: Int, avail: Int): Int? {
            if (proto == ABRIDGED) {
                val first = plain[off].toInt() and 0xFF
                val (len, hdr) = if (first == 0x7F || first == 0xFF) {
                    if (avail < 4) return null
                    ((plain[off + 1].toInt() and 0xFF) or ((plain[off + 2].toInt() and 0xFF) shl 8) or
                        ((plain[off + 3].toInt() and 0xFF) shl 16)) * 4 to 4
                } else (first and 0x7F) * 4 to 1
                if (len <= 0) return 0
                return (hdr + len).takeIf { it <= avail }
            }
            if (avail < 4) return null
            val len = le32(plain, off) and 0x7FFFFFFF
            if (len <= 0) return 0
            return (4 + len).takeIf { it <= avail }
        }
    }

    // ---- транспорт к Telegram ----

    private interface Upstream {
        val socket: Socket
        val framed: Boolean
        fun send(plain: ByteArray, cipher: ByteArray)
        fun recv(): ByteArray?
    }

    private class TcpUp(override val socket: Socket) : Upstream {
        override val framed = false
        private val out = socket.getOutputStream()
        private val inp = socket.getInputStream()
        private val buf = ByteArray(65536)
        override fun send(plain: ByteArray, cipher: ByteArray) { out.write(cipher); out.flush() }
        override fun recv(): ByteArray? { val n = inp.read(buf); return if (n < 0) null else buf.copyOf(n) }
    }

    private class WsRedirect : IOException("redirect")

    private class WsUp(override val socket: SSLSocket) : Upstream {
        override val framed = true
        private val out = socket.getOutputStream()
        private val inp = socket.getInputStream()
        private val lock = Any()
        private val frag = java.io.ByteArrayOutputStream()

        override fun send(plain: ByteArray, cipher: ByteArray) = frame(0x2, cipher)

        private fun frame(op: Int, data: ByteArray) {
            val n = data.size
            val hdr = java.io.ByteArrayOutputStream(14)
            hdr.write(0x80 or op)
            when {
                n < 126 -> hdr.write(0x80 or n)
                n < 65536 -> { hdr.write(0x80 or 126); hdr.write(n shr 8); hdr.write(n) }
                else -> { hdr.write(0x80 or 127); for (i in 7 downTo 0) hdr.write((n.toLong() shr (8 * i)).toInt()) }
            }
            val mask = ByteArray(4).also { rnd.nextBytes(it) }
            hdr.write(mask)
            val body = ByteArray(n) { (data[it].toInt() xor mask[it and 3].toInt()).toByte() }
            synchronized(lock) { out.write(hdr.toByteArray()); out.write(body); out.flush() }
        }

        override fun recv(): ByteArray? {
            while (true) {
                val h = readN(inp, 2) ?: return null
                val fin = h[0].toInt() and 0x80 != 0
                val op = h[0].toInt() and 0x0F
                var len = (h[1].toInt() and 0x7F).toLong()
                if (len == 126L) { val e = readN(inp, 2) ?: return null; len = ((e[0].toLong() and 0xFF) shl 8) or (e[1].toLong() and 0xFF) }
                else if (len == 127L) { val e = readN(inp, 8) ?: return null; len = e.fold(0L) { a, b -> (a shl 8) or (b.toLong() and 0xFF) } }
                if (len > 16L * 1024 * 1024) throw IOException("ws frame too large")
                val mask = if (h[1].toInt() and 0x80 != 0) readN(inp, 4) ?: return null else null
                val p = readN(inp, len.toInt()) ?: return null
                if (mask != null) for (i in p.indices) p[i] = (p[i].toInt() xor mask[i and 3].toInt()).toByte()
                when (op) {
                    0x8 -> { runCatching { frame(0x8, p.copyOf(minOf(2, p.size))) }; return null }
                    0x9 -> { runCatching { frame(0xA, p) }; continue }
                    0xA -> continue
                    0x0, 0x1, 0x2 -> {
                        if (fin && frag.size() == 0) return p
                        frag.write(p)
                        if (!fin) continue
                        return frag.toByteArray().also { frag.reset() }
                    }
                }
            }
        }

        companion object {
            fun open(host: String, domain: String, timeout: Int): WsUp {
                val raw = Socket().apply { tcpNoDelay = true; connect(InetSocketAddress(host, 443), timeout) }
                val s = try {
                    (SSLSocketFactory.getDefault() as SSLSocketFactory).createSocket(raw, domain, 443, true) as SSLSocket
                } catch (e: IOException) { raw.close(); throw e }
                try {
                    s.soTimeout = timeout
                    s.startHandshake()
                    if (!HttpsURLConnection.getDefaultHostnameVerifier().verify(domain, s.session)) throw IOException("bad cert for $domain")
                    val key = Base64.getEncoder().encodeToString(ByteArray(16).also { rnd.nextBytes(it) })
                    s.outputStream.write(("GET $WS_PATH HTTP/1.1\r\nHost: $domain\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n" +
                        "Sec-WebSocket-Key: $key\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Protocol: binary\r\n\r\n").toByteArray())
                    s.outputStream.flush()
                    val status = readHeaders(s.inputStream)
                    if (status in listOf(301, 302, 303, 307, 308)) throw WsRedirect()
                    if (status != 101) throw IOException("ws handshake HTTP $status")
                    s.soTimeout = 0
                    return WsUp(s)
                } catch (e: Exception) {
                    runCatching { s.close() }; throw e
                }
            }

            private fun readHeaders(inp: InputStream): Int {
                val line = StringBuilder(); var status = 0; var first = true
                while (true) {
                    val b = inp.read()
                    if (b < 0) throw IOException("ws: connection closed")
                    if (b == '\n'.code) {
                        val l = line.toString().trim(); line.setLength(0)
                        if (l.isEmpty()) return status
                        if (first) { status = l.split(' ').getOrNull(1)?.toIntOrNull() ?: 0; first = false }
                    } else if (line.length < 8192) line.append(b.toChar())
                }
            }
        }
    }

    // ---- утилиты ----

    private fun ctr(key: ByteArray, iv: ByteArray): Cipher =
        Cipher.getInstance("AES/CTR/NoPadding").apply { init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), IvParameterSpec(iv)) }

    private fun sha256(a: ByteArray, b: ByteArray): ByteArray = MessageDigest.getInstance("SHA-256").run { update(a); digest(b) }

    private fun le32(b: ByteArray, o: Int): Int =
        (b[o].toInt() and 0xFF) or ((b[o + 1].toInt() and 0xFF) shl 8) or ((b[o + 2].toInt() and 0xFF) shl 16) or ((b[o + 3].toInt() and 0xFF) shl 24)

    private fun hex(s: String): ByteArray? {
        if (!Regex("^[0-9a-f]{32}$").matches(s)) return null
        return ByteArray(16) { s.substring(it * 2, it * 2 + 2).toInt(16).toByte() }
    }

    private fun readN(inp: InputStream, n: Int): ByteArray? {
        val b = ByteArray(n); var off = 0
        while (off < n) { val r = inp.read(b, off, n - off); if (r < 0) return null; off += r }
        return b
    }
}
