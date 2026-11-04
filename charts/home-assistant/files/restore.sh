#!/bin/bash
# Restore one ha-backups object onto /config. Skip when the db is already there
# so a pod restart does not wipe recorder history from this session.
# Prints a one-line status. Does not print the object, the file list, or secrets.
set -euo pipefail

config="${HA_CONFIG:-/config}"
archive="${HA_ARCHIVE:-/tmp/ha-backup.tar.gz}"
names="${HA_NAMES:-/tmp/ha-names.txt}"
db="${config}/home-assistant_v2.db"

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
local_sum=$(openssl dgst -sha256 -binary "$archive" | openssl base64 -A)

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
