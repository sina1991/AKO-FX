#!/usr/bin/env bash
# AKO-FX bootstrap. Does not provision or restart Docker/Nginx itself.
set -Eeuo pipefail
umask 077

if [[ " ${*} " == *" --help "* || " ${*} " == *" -h "* ]]; then
    cat <<'HELP'
AKO-FX installer (Ubuntu 24.04, root)
Usage: bash install.sh [options]
  --domain DOMAIN                 Public DNS name (prompted if omitted)
  --port PORT                     HTTPS port (default: first free from 8443)
  --backend-port PORT             Loopback gateway port (first free from 9080)
  --admin-email EMAIL              Initial admin email, if none exists
  --admin-password-file PATH       Private file; only for non-interactive bootstrap
  --email EMAIL                   Let's Encrypt email, if a new cert is needed
  --cert PATH --key PATH           Explicit existing matching certificate/key
  --ref REF                       Source branch/tag/SHA (default: main)
  --check-only                    Read-only host preflight, no provisioning
  --non-interactive               Require all missing inputs as flags
Existing AKO-FX data and admin are reused. No docker down/prune or daemon reconfiguration.
HELP
    exit 0
fi
[[ ${EUID} -eq 0 ]] || { echo 'Run as root (sudo bash install.sh ...).' >&2; exit 1; }
check_only=0
ref=main
args=("$@")
for ((i=0; i<${#args[@]}; i++)); do
    case "${args[i]}" in
        --check-only) check_only=1 ;;
        --ref)
            (( i+1 < ${#args[@]} )) || { echo '--ref requires a value' >&2; exit 1; }
            ref=${args[i+1]}
            ;;
    esac
done
[[ "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._/-]*$ && "$ref" != *..* ]] || { echo 'Invalid ref' >&2; exit 1; }
if ! command -v python3 >/dev/null || ! command -v git >/dev/null; then
    [[ "$check_only" == 0 ]] || { echo 'check-only requires python3 and git; nothing installed.' >&2; exit 1; }
    source /etc/os-release
    [[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || { echo 'Automatic bootstrap supports Ubuntu 24.04 only.' >&2; exit 1; }
    apt-get update
    apt-get install -y python3 git ca-certificates
fi
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ required"'
source_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [[ -f "$source_root/scripts/installer.py" && -f "$source_root/ako_fx/server.py" ]] && git -C "$source_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    python3 "$source_root/scripts/installer.py" "${args[@]}"
else
    bootstrap_dir=$(mktemp -d /tmp/ako-fx-bootstrap.XXXXXXXX)
    trap 'rm -rf -- "$bootstrap_dir"' EXIT
    git init -q "$bootstrap_dir/source"
    git -C "$bootstrap_dir/source" remote add origin https://github.com/sina1991/AKO-FX.git
    git -C "$bootstrap_dir/source" fetch -q --depth=1 origin "$ref"
    git -C "$bootstrap_dir/source" checkout -q --detach FETCH_HEAD
    python3 "$bootstrap_dir/source/scripts/installer.py" "${args[@]}"
fi
