#!/bin/sh
# Download a published native binary; no Python, sudo, or agent-config changes.
set -eu
umask 077

fail() { printf 'signalweave: %s\n' "$*" >&2; exit 1; }
version=latest
replace=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version) [ "$#" -ge 2 ] || fail '--version needs vMAJOR.MINOR.PATCH'; version=$2; shift 2 ;;
        --replace) replace=true; shift ;;
        --help) printf '%s\n' 'Usage: sh install.sh [--version vMAJOR.MINOR.PATCH] [--replace]' 'Installs to ~/.local/bin (or SIGNALWEAVE_INSTALL_DIR).'; exit 0 ;;
        *) fail "Unknown argument: $1" ;;
    esac
done
valid_version() {
    case "$1" in *[!v0-9.]*) return 1 ;; esac
    printf '%s\n' "$1" | LC_ALL=C grep -Eq '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$'
}
[ "$version" = latest ] || valid_version "$version" || fail 'Invalid stable release version'
for tool in curl tar awk grep mktemp uname chmod mkdir ln mv; do
    command -v "$tool" >/dev/null 2>&1 || fail "Required command missing: $tool"
done
if command -v sha256sum >/dev/null 2>&1; then
    checksum() { sha256sum "$1" | awk '{print $1}'; }
elif command -v shasum >/dev/null 2>&1; then
    checksum() { shasum -a 256 "$1" | awk '{print $1}'; }
else
    fail 'sha256sum or shasum is required'
fi
case "$(uname -s)/$(uname -m)" in
    Darwin/arm64) target=darwin-arm64 ;;
    Darwin/x86_64) target=darwin-x86_64 ;;
    Linux/x86_64) target=linux-x86_64 ;;
    *) fail 'Supported systems: macOS ARM64/x64 and Linux x64 (glibc)';;
esac
release_base=https://github.com/waddle-zoo/signal-weave/releases
download() {
    curl --fail --silent --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 15 --max-time 300 --retry 2 "$@"
}
if [ "$version" = latest ]; then
    resolved=$(download --output /dev/null --write-out '%{url_effective}' "$release_base/latest") || fail 'Cannot resolve latest published release'
    case "$resolved" in "$release_base/tag/"*) version=${resolved#"$release_base/tag/"} ;; *) fail 'Unexpected release redirect' ;; esac
    valid_version "$version" || fail 'Latest release is not a stable version'
fi
install_dir=${SIGNALWEAVE_INSTALL_DIR:-"${HOME:?HOME must be set}/.local/bin"}
case "$install_dir" in /*) ;; *) fail 'Install directory must be absolute' ;; esac
[ ! -L "$install_dir" ] || fail 'Install directory must not be a symlink'
destination=$install_dir/signalweave
[ ! -L "$destination" ] || fail 'Existing executable is a symlink; refusing replacement'
if [ -e "$destination" ]; then
    [ -f "$destination" ] || fail 'Existing destination is not a regular file'
    [ "$replace" = true ] || fail 'Already installed; rerun with --replace to upgrade explicitly'
fi
mkdir -p "$install_dir"
# Staging on the destination filesystem makes replacement a single rename.
stage=$(mktemp -d "$install_dir/.signalweave-install.XXXXXXXX") || fail 'Cannot create staging directory'
cleanup() { rm -f "$stage/archive.tar.gz" "$stage/checksum" "$stage/names" "$stage/types" "$stage/signalweave"; rmdir "$stage"; }
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
asset=signalweave-$version-$target.tar.gz
download --output "$stage/checksum" "$release_base/download/$version/$asset.sha256" || fail 'No checksum available for this release/platform'
download --output "$stage/archive.tar.gz" "$release_base/download/$version/$asset" || fail 'Release download failed'
# Parse only a single conventional SHA256 line; never execute a downloaded path.
expected=$(awk -v name="$asset" 'NF == 2 && $2 == name && length($1) == 64 && $1 !~ /[^0-9a-f]/ {sum=$1; valid++} END {if (NR != 1 || valid != 1) exit 1; print sum}' "$stage/checksum") || fail 'Malformed release checksum'
actual=$(checksum "$stage/archive.tar.gz")
[ "$actual" = "$expected" ] || fail 'Checksum mismatch; nothing installed'
tar -tzf "$stage/archive.tar.gz" > "$stage/names" || fail 'Invalid archive'
awk '($0 != "signalweave" && $0 != "LICENSE" && $0 != "build-info.json") || seen[$0]++ {exit 1} END {if (NR != 3 || !seen["signalweave"] || !seen["LICENSE"] || !seen["build-info.json"]) exit 1}' "$stage/names" || fail 'Unexpected archive paths'
tar -tvzf "$stage/archive.tar.gz" > "$stage/types" || fail 'Invalid archive metadata'
awk 'substr($0,1,1) != "-" {exit 1} END {if (NR != 3) exit 1}' "$stage/types" || fail 'Archive contains a link or special file'
# Stream the exact member: no archive-controlled paths are ever extracted.
tar -xOzf "$stage/archive.tar.gz" signalweave > "$stage/signalweave" || fail 'Cannot read executable'
[ -s "$stage/signalweave" ] || fail 'Empty executable'
chmod 755 "$stage/signalweave"
# A failed startup must not replace a working installation.
"$stage/signalweave" --help >/dev/null || fail 'Executable cannot run on this system; existing installation unchanged'
if [ "$replace" = true ]; then
    [ ! -L "$destination" ] || fail 'Destination became a symlink'
    [ ! -e "$destination" ] || [ -f "$destination" ] || fail 'Destination is not a regular file'
    mv -f "$stage/signalweave" "$destination"
else
    # Hard-link creation atomically refuses a concurrently created destination.
    ln "$stage/signalweave" "$destination" || fail 'Destination exists; nothing replaced'
fi
printf 'Installed SignalWeave %s at %s\nNext: "%s" setup\n' "$version" "$destination" "$destination"
printf '%s\n' 'Add ~/.local/bin to PATH if needed. No shell or agent configuration was changed.'
