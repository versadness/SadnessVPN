package com.sadness.vpn.vpn

import java.net.Inet4Address
import java.net.NetworkInterface

/**
 * Точка доступа телефона: адрес и подсеть, через которые к нему подключаются
 * другие устройства. У Android нет открытого API для этого, поэтому интерфейс
 * ищется по имени: ap0, swlan0, softap0, wlan1… (зависит от производителя).
 */
object Hotspot {
    data class Address(val ip: String, val cidr: String, val iface: String)

    private val NAMES = Regex("^(ap|swlan|softap|wlan[1-9]|wigig|rndis|bt-pan)\\d*$")

    fun addresses(): List<Address> = runCatching {
        NetworkInterface.getNetworkInterfaces().toList()
            .filter { it.isUp && !it.isLoopback && NAMES.matches(it.name) }
            .flatMap { iface ->
                iface.interfaceAddresses.mapNotNull { address ->
                    val ip = address.address as? Inet4Address ?: return@mapNotNull null
                    if (!ip.isSiteLocalAddress) return@mapNotNull null
                    Address(ip.hostAddress ?: return@mapNotNull null, network(ip, address.networkPrefixLength.toInt()), iface.name)
                }
            }
    }.getOrDefault(emptyList())

    /** 192.168.43.1 с /24 → 192.168.43.0/24. */
    private fun network(ip: Inet4Address, prefix: Int): String {
        val bytes = ip.address
        val value = bytes.fold(0L) { acc, b -> (acc shl 8) or (b.toLong() and 0xFF) }
        val mask = if (prefix == 0) 0L else (0xFFFFFFFFL shl (32 - prefix)) and 0xFFFFFFFFL
        val net = value and mask
        return "${net shr 24 and 0xFF}.${net shr 16 and 0xFF}.${net shr 8 and 0xFF}.${net and 0xFF}/$prefix"
    }
}
