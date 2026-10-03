"""Корневые сертификаты для HTTPS на Linux.

Бэкенд собирается на Ubuntu, и встроенный OpenSSL ищет сертификаты по путям
Ubuntu (/usr/lib/ssl). На Fedora и Bazzite они лежат в /etc/pki, на Arch и
openSUSE — в своих местах, и без подсказки любой HTTPS-запрос (подписки,
проверки) падает с ошибкой проверки сертификата. Здесь до первого запроса
выбирается системный набор, а если его нет — встроенный certifi.
"""
import os
import sys

# Порядок важен только для систем, где лежат сразу несколько файлов.
SYSTEM_BUNDLES = (
    "/etc/ssl/certs/ca-certificates.crt",                 # Debian, Ubuntu, Arch, Gentoo
    "/etc/pki/tls/certs/ca-bundle.crt",                   # Fedora, Bazzite, RHEL
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",  # Fedora (прямой путь)
    "/etc/ssl/ca-bundle.pem",                             # openSUSE
    "/etc/ssl/cert.pem",                                  # Alpine, часть сборок Arch
)


def _certifi_bundle():
    try:
        import certifi
        return certifi.where()
    except Exception:
        return ""


def configure(environ=None, platform=None, exists=os.path.isfile, fallback=_certifi_bundle):
    """Указать OpenSSL набор сертификатов через SSL_CERT_FILE.

    Возвращает выбранный путь или "" (Windows, переменная уже задана, набора нет).
    Заданный пользователем SSL_CERT_FILE/SSL_CERT_DIR не трогаем.
    """
    environ = os.environ if environ is None else environ
    platform = sys.platform if platform is None else platform
    if platform == "win32" or environ.get("SSL_CERT_FILE") or environ.get("SSL_CERT_DIR"):
        return ""
    bundle = next((path for path in SYSTEM_BUNDLES if exists(path)), "") or fallback()
    if bundle and exists(bundle):
        environ["SSL_CERT_FILE"] = bundle
        return bundle
    return ""
