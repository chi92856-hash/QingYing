"""Use the Windows desktop network configuration in frozen and source runs."""
import os
import urllib.request


def desktop_proxies():
    # Windows desktop shortcuts do not inherit the terminal's proxy variables.
    # Prefer the user's system setting, shared by their ordinary Edge session.
    if os.name == 'nt':
        proxies = urllib.request.getproxies_registry()
        if proxies:
            return proxies
    return urllib.request.getproxies()


def extractor_proxy():
    proxies = desktop_proxies()
    return proxies.get('https') or proxies.get('http') or proxies.get('all')
