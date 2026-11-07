"""Select loopback ports usable by both TCP and UDP listeners in live tests."""
import socket


def free_port():
    # Windows keeps separate exclusion ranges for TCP and UDP. Selecting a
    # TCP ephemeral port alone can hand Mihomo a port it cannot bind for DNS
    # or SOCKS UDP. Start with a UDP allocation, then verify the TCP bind.
    for _ in range(128):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                udp.bind(('127.0.0.1', 0))
                port = udp.getsockname()[1]
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp:
                    tcp.bind(('127.0.0.1', port))
                    return port
        except OSError:
            continue
    raise OSError('Could not allocate a loopback port for both TCP and UDP')
