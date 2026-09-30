#!/bin/bash
# Selbstsigniertes Zertifikat für Entwicklung/Pilot generieren
# Für Produktion: Let's Encrypt oder gekauftes Zertifikat verwenden

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SSL_DIR="$SCRIPT_DIR/ssl"

mkdir -p "$SSL_DIR"

openssl req -x509 -nodes -days 365 \
    -newkey rsa:2048 \
    -keyout "$SSL_DIR/key.pem" \
    -out "$SSL_DIR/cert.pem" \
    -subj "/C=DE/ST=Bayern/L=Muenchen/O=FiBu-Agent/CN=localhost"

echo "Zertifikat erstellt in $SSL_DIR/"
echo "  cert.pem  (Zertifikat)"
echo "  key.pem   (Privater Schlüssel)"
echo ""
echo "Für Produktion: Let's Encrypt mit certbot verwenden."
