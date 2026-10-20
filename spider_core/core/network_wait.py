"""
Block until network is reachable, or timeout.

Usage:
    from core.network_wait import wait_for_network
    if not wait_for_network():
        sys.exit(1)
"""
import socket
import time


def wait_for_network(host="api.deepseek.com", port=443, timeout=300):
    """Wait for TCP connectivity to `host:port`, up to `timeout` seconds.
    Returns True if connected, False on timeout.
    """
    waited = 0
    while waited < timeout:
        try:
            socket.create_connection((host, port), timeout=5)
            print(f"[OK] Network ready (waited {waited}s)")
            return True
        except OSError:
            time.sleep(10)
            waited += 10
    print(f"[FAIL] No network after {timeout}s")
    return False
