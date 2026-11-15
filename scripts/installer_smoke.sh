#!/usr/bin/env bash
# Destructive fixture setup ONLY for a dedicated GitHub Actions runner.
set -Eeuo pipefail
[[ ${GITHUB_ACTIONS:-} == true && ${EUID} -eq 0 ]] || { echo 'Dedicated CI runner only' >&2; exit 1; }
apt-get update -qq
apt-get install -y nginx certbot openssl
fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$fixture/ca.key" \
  -out "$fixture/ca.crt" -days 2 -subj '/CN=AKO CI Test CA' >/dev/null 2>&1
install -m 644 "$fixture/ca.crt" /usr/local/share/ca-certificates/ako-ci.crt
update-ca-certificates >/dev/null
mkdir -p /etc/letsencrypt/live/30na-dashboard /etc/30na
openssl req -new -newkey rsa:2048 -nodes -keyout /etc/letsencrypt/live/30na-dashboard/privkey.pem \
  -out "$fixture/leaf.csr" -subj '/CN=x.30na.test' >/dev/null 2>&1
printf 'subjectAltName=DNS:x.30na.test\nextendedKeyUsage=serverAuth\n' > "$fixture/extensions"
openssl x509 -req -in "$fixture/leaf.csr" -CA "$fixture/ca.crt" -CAkey "$fixture/ca.key" \
  -CAcreateserial -out /etc/letsencrypt/live/30na-dashboard/fullchain.pem \
  -days 2 -extfile "$fixture/extensions" >/dev/null 2>&1
cat > /etc/nginx/sites-available/30na <<'NGINX'
server {
    listen 80;
    server_name x.30na.test;
    return 200 'existing-30na-fixture';
}
server {
    listen 443 ssl;
    server_name x.30na.test;
    ssl_certificate /etc/letsencrypt/live/30na-dashboard/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/30na-dashboard/privkey.pem;
    return 200 'existing-30na-fixture';
}
NGINX
ln -s /etc/nginx/sites-available/30na /etc/nginx/sites-enabled/30na
nginx -t
systemctl restart nginx
before=$(sha256sum /etc/nginx/sites-available/30na)
printf '%s\n' 'CI-only-password-12345' > "$fixture/password"
chmod 600 "$fixture/password"
# Check-only must not create managed host files.
bash install.sh --domain x.30na.test --port 8443 --backend-port 9080 \
  --non-interactive --admin-email ci@example.com --admin-password-file "$fixture/password" --check-only
[[ ! -e /etc/ako-fx/install.json ]]
bash install.sh --domain x.30na.test --port 8443 --backend-port 9080 \
  --non-interactive --admin-email ci@example.com --admin-password-file "$fixture/password"
python3 scripts/installer_smoke.py seed
# Re-run: retain the existing admin and populated wallet, with no password input.
bash install.sh --domain x.30na.test --port 8443 --backend-port 9080 --non-interactive
python3 scripts/installer_smoke.py verify
[[ "$before" == "$(sha256sum /etc/nginx/sites-available/30na)" ]]
find /var/backups/ako-fx -name 'pre-install-*.db' -print -quit | grep -q .
ako-fx status
printf '%s\n' 'PASS: real Docker/Nginx/TLS, check-only, existing proxy, wallet, backup, repeated installation and admin preservation.'
