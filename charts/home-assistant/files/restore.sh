#!/bin/bash
# Restore one ha-backups object onto /config. Skip when the db is already there
# so a pod restart does not wipe recorder history from this session.
# amazon/aws-cli has sha256sum and dnf. tar and gzip are installed when missing.
# Prints a one-line status. Does not print the object, the file list, or secrets.
set -euo pipefail

config="${HA_CONFIG:-/config}"
archive="${HA_ARCHIVE:-/tmp/ha-backup.tar.gz}"
names="${HA_NAMES:-/tmp/ha-names.txt}"
db="${config}/home-assistant_v2.db"

# SHA-256 as standard base64, which is what S3 ChecksumSHA256 returns.
sha256_b64() {
  local hex oct i byte
  hex=$(sha256sum "$1") || return 1
  hex=${hex%% *}
  if [ "${#hex}" -ne 64 ]; then
    return 0
  fi
  oct=""
  i=0
  while [ "$i" -lt 64 ]; do
    byte=$((16#${hex:$i:2}))
    oct="${oct}$(printf '\\%03o' "$byte")"
    i=$((i + 2))
  done
  printf '%b' "$oct" | base64 | tr -d '\n'
}

# Package-manager output goes to stderr so stdout stays the one-line status.
ensure_tar_gzip() {
  if command -v tar >/dev/null 2>&1 && command -v gzip >/dev/null 2>&1; then
    return 0
  fi
  if command -v dnf >/dev/null 2>&1; then
    dnf install -y tar gzip >&2
  elif command -v yum >/dev/null 2>&1; then
    yum install -y tar gzip >&2
  elif command -v microdnf >/dev/null 2>&1; then
    microdnf install -y tar gzip >&2
  else
    echo "tar and gzip are required" >&2
    return 1
  fi
  if ! command -v tar >/dev/null 2>&1 || ! command -v gzip >/dev/null 2>&1; then
    echo "tar and gzip are required" >&2
    return 1
  fi
}

if [ -s "$db" ]; then
  echo '{"skipped":true}'
  exit 0
fi

key="${HA_KEY:-}"
bucket="${HA_BUCKET:-}"
case "$key" in
  *..*)
    echo "refusing backup key" >&2
    exit 1
    ;;
  ha-backups/*) ;;
  *)
    echo "refusing backup key" >&2
    exit 1
    ;;
esac
if [ -z "$bucket" ]; then
  echo "backup bucket is empty" >&2
  exit 1
fi

mkdir -p "$config"
aws s3api get-object \
  --bucket "$bucket" \
  --key "$key" \
  --checksum-mode ENABLED \
  "$archive" >/tmp/ha-get.json

sse=$(aws s3api head-object --bucket "$bucket" --key "$key" --checksum-mode ENABLED --query ServerSideEncryption --output text)
size=$(aws s3api head-object --bucket "$bucket" --key "$key" --checksum-mode ENABLED --query ContentLength --output text)
sum=$(aws s3api head-object --bucket "$bucket" --key "$key" --checksum-mode ENABLED --query ChecksumSHA256 --output text)
local_size=$(wc -c <"$archive" | tr -d '[:space:]')
local_sum=$(sha256_b64 "$archive" || true)

if [ "$sse" != "aws:kms" ]; then
  rm -f "$archive" /tmp/ha-get.json
  echo "object is not KMS encrypted" >&2
  exit 1
fi
if [ "$size" != "$local_size" ]; then
  rm -f "$archive" /tmp/ha-get.json
  echo "download size mismatch" >&2
  exit 1
fi
if [ -z "$sum" ] || [ "$sum" = "None" ] || [ "$sum" != "$local_sum" ]; then
  rm -f "$archive" /tmp/ha-get.json
  echo "checksum mismatch" >&2
  exit 1
fi

ensure_tar_gzip

tar -tzf "$archive" >"$names"
if grep -q -E '(^|/)\.\.(/|$)|^/' "$names"; then
  rm -f "$archive" "$names" /tmp/ha-get.json
  echo "archive path refused" >&2
  exit 1
fi
if ! grep -q -E '(^|/)home-assistant_v2\.db$' "$names"; then
  rm -f "$archive" "$names" /tmp/ha-get.json
  echo "archive is missing home-assistant_v2.db" >&2
  exit 1
fi
tar -xzf "$archive" -C "$config"
if [ ! -s "$db" ]; then
  echo "restore missing home-assistant_v2.db" >&2
  exit 1
fi
rm -f "$archive" "$names" /tmp/ha-get.json
echo '{"skipped":false}'
