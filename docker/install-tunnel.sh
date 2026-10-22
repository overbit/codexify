#!/bin/sh
# Use the same release and archive hashes as the native application. A change
# to the upstream source layout fails the build rather than skipping verification.
set -eu
arch=${1:?target architecture required}
source_file=${2:?Rust tunnel source required}
destination=${3:?output file required}
case "$arch" in
    amd64|arm64) ;;
    *) printf 'Unsupported tunnel architecture: %s\n' "$arch" >&2; exit 1 ;;
esac
version=$(sed -n 's/^pub const TUNNEL_CLIENT_VERSION: \&str = "\([0-9.]*\)";/\1/p' "$source_file")
checksum=$(sed -n "s/.*(\"linux\", \"$arch\") => \"\([a-f0-9]\{64\}\)\".*/\1/p" "$source_file")
[ -n "$version" ] && [ "${#checksum}" -eq 64 ] || {
    printf 'Could not read pinned tunnel version/checksum from %s\n' "$source_file" >&2
    exit 1
}
archive=$(mktemp)
trap 'rm -f "$archive"' 0
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
    --retry 3 --connect-timeout 15 --max-time 180 \
    "https://github.com/openai/tunnel-client/releases/download/v$version/tunnel-client-runtime-v$version-linux-$arch.zip" \
    --output "$archive"
printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check --status
unzip -p "$archive" tunnel-client-runtime > "$destination"
chmod 755 "$destination"
# Preserve the notices shipped inside the checksum-verified release archive.
license_dir="$(dirname "$destination")/tunnel-licenses"
mkdir -p "$license_dir"
for notice in LICENSE NOTICE "tunnel-client-runtime-linux-$arch-licenses.txt"; do
    unzip -p "$archive" "$notice" > "$license_dir/$notice"
done
