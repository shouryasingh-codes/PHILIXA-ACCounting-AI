"""Explicit verified TLS initialization for frozen and ordinary Tally clients.

Do not inherit SSLKEYLOGFILE or depend on frozen importlib resource extraction.
No client disables certificate or hostname verification.
"""
from pathlib import Path
import ssl
import sys

import certifi
import httpx


def ca_path():
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'certifi' / 'cacert.pem'
    return Path(certifi.where())


def tls_context():
    path = ca_path()
    if not path.is_file():
        raise FileNotFoundError('Connector CA resource missing')
    # create_default_context also reads SSLKEYLOGFILE even with HTTPX trust_env=False.
    # An unavailable debug-log directory can therefore prevent HTTP-only Tally reads.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=str(path))
    if context.verify_mode != ssl.CERT_REQUIRED or not context.check_hostname:
        raise RuntimeError('TLS verification configuration invalid')
    return context


def sync_client(**options):
    if 'verify' in options or 'trust_env' in options:
        raise ValueError('TLS settings are owned by the connector transport')
    return httpx.Client(verify=tls_context(), trust_env=False, **options)


def async_client(**options):
    if 'verify' in options or 'trust_env' in options:
        raise ValueError('TLS settings are owned by the connector transport')
    return httpx.AsyncClient(verify=tls_context(), trust_env=False, **options)
