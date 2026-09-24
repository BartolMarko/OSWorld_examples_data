#!/usr/bin/env bash
# NON-sudo setup for the mock newsletter HTTPS server.
#
# Does two things (neither needs root):
#   1. Uses mkcert to sign trusted certs for the given domains, storing them
#      in ~/.local/share/newsletter-mock/.
#   2. Installs the matching local CA into Chrome's trust DB (~/.pki/nssdb),
#      so Chrome shows no "Your connection is not private" warning.
#
# Usage:
#   ./setup_certs.sh                                        # default domains
#   ./setup_certs.sh example.com foo.io bar.net             # custom domains
set -euo pipefail

# Domains from command line, or sensible defaults.
DOMAINS=("$@")
if [[ ${#DOMAINS[@]} -eq 0 ]]; then
    DOMAINS=(techdaily.com dealsweekly.com codebytes.io)
fi

# Stable location shared with test_newsletter_serve.sh.
CERT_DIR="$HOME/.local/share/newsletter-mock"
CERT="$CERT_DIR/domains.pem"
KEY="$CERT_DIR/domains-key.pem"

missing=0
for d in "${DOMAINS[@]}"; do
    grep -qF "$d" /etc/hosts 2>/dev/null || missing=1
done
if [[ $missing -ne 0 ]]; then
    echo ">> Add this line to /etc/hosts first:"
    echo "    127.0.0.1 ${DOMAINS[*]}"
    echo ""
    echo "    sudo bash -c 'echo \"127.0.0.1 ${DOMAINS[*]}\" >> /etc/hosts'"
    exit 1
fi

for tool in mkcert certutil; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo ">> Missing '$tool'. Install it:"
        echo "    sudo apt update && sudo apt install -y mkcert libnss3-tools"
        exit 1
    fi
done

# The Chrome trust DB lives in YOUR home dir, so this must run as non root.
if [[ ${EUID} -eq 0 ]]; then
    echo ">> Do not run this script with sudo. Run it as your normal user:"
    echo "    ./setup_certs.sh"
    exit 1
fi

mkdir -p "$CERT_DIR"
rm -f "$CERT" "$KEY"
mkcert -cert-file "$CERT" -key-file "$KEY" "${DOMAINS[@]}" >/dev/null 2>&1
echo ">> Wrote certs for: ${DOMAINS[*]}"
echo ">>   $CERT_DIR/domains.pem"

# Chrome on Linux reads user certificates from ~/.pki/nssdb.
NSS_DIR="$HOME/.pki/nssdb"
NSSDB="sql:$NSS_DIR"
NSS_NAME="mkcert local CA"

mkdir -p "$NSS_DIR"
if [[ ! -f "$NSS_DIR/cert9.db" ]]; then
    certutil -d "$NSSDB" -N --empty-password >/dev/null 2>&1
fi

certutil -d "$NSSDB" -D -n "$NSS_NAME" 2>/dev/null || true
certutil -d "$NSSDB" -A -t C,, -n "$NSS_NAME" \
    -i "$HOME/.local/share/mkcert/rootCA.pem"

echo ">> Installed local CA into Chrome's trust DB (~/.pki/nssdb)."
echo
echo "Setup complete. Now start the server with:"
echo "    sudo ./test_newsletter_serve.sh ${DOMAINS[*]}"
echo
echo "Then open https://${DOMAINS[0]}/ and click 'Unsubscribe' (downloads a PDF)."
