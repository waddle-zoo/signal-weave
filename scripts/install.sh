#!/bin/sh
# Download a published native binary; no Python, sudo, or agent-config changes.
set -eu
umask 077

fail() { printf 'signalweave: %s\n' "$*" >&2; exit 1; }
version=latest
replace=false
run_setup=false
quiet=false
while [ "$#" -gt 0 ]; do
    case "$1" in
        --version) [ "$#" -ge 2 ] || fail '--version needs vMAJOR.MINOR.PATCH[rcN]'; version=$2; shift 2 ;;
        --replace) replace=true; shift ;;
        --setup) run_setup=true; shift ;;
        --quiet|-q) quiet=true; shift ;;
        --help) printf '%s\n' 'Usage: sh install.sh [--version vMAJOR.MINOR.PATCH[rcN]] [--replace] [--setup] [--quiet]' 'Installs to ~/.local/bin (or SIGNALWEAVE_INSTALL_DIR). --setup launches the guided first-run wizard.' '--quiet suppresses installer progress and success messages, not setup prompts or errors.' 'Previews require an explicit version.'; exit 0 ;;
        *) fail "Unknown argument: $1" ;;
    esac
done
valid_version() {
    case "$1" in *[!vrc0-9.]*) return 1 ;; esac
    printf '%s\n' "$1" | LC_ALL=C grep -Eq '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(rc[1-9][0-9]*)?$'
}
[ "$version" = latest ] || valid_version "$version" || fail 'Invalid release version'
for tool in curl tar awk grep sed mktemp uname chmod mkdir ln mv; do
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
interactive=false
if [ -t 2 ] && [ "${TERM:-}" != dumb ]; then interactive=true; fi
note() {
    [ "$quiet" = false ] || return 0
    if [ "$interactive" = true ] && [ -z "${NO_COLOR:-}" ]; then
        printf '\033[36m%s\033[0m\n' "$*" >&2
    else
        printf '%s\n' "$*" >&2
    fi
}
download() {
    download_progress=--silent
    if [ "${1:-}" = --progress ]; then
        shift
        if [ "$interactive" = true ] && [ "$quiet" = false ]; then download_progress=--progress-bar; fi
    fi
    curl --fail "$download_progress" --show-error --location --proto '=https' --proto-redir '=https' \
        --connect-timeout 15 --max-time 300 --retry 2 "$@"
}
install_dir=${SIGNALWEAVE_INSTALL_DIR:-"${HOME:?HOME must be set}/.local/bin"}
case "$install_dir" in /*) ;; *) fail 'Install directory must be absolute' ;; esac
[ ! -L "$install_dir" ] || fail 'Install directory must not be a symlink'
destination=$install_dir/signalweave
[ ! -L "$destination" ] || fail 'Existing executable is a symlink; refusing replacement'

print_path_guidance() {
    [ "$quiet" = false ] || return 0
    signalweave_command=$(command -v signalweave 2>/dev/null || true)
    [ "$signalweave_command" = "$destination" ] && return 0
    if [ -n "$signalweave_command" ]; then
        printf '%s\n' 'Another signalweave command currently takes precedence over this installation.'
    fi
    escaped_install_dir=$(printf '%s' "$install_dir" | sed 's/[\\$"`]/\\&/g')
    printf 'To run this installation by name in this shell, use: export PATH="%s:$PATH"\n' "$escaped_install_dir"
    printf '%s\n' 'Check with: signalweave --version. If it still resolves elsewhere, inspect shell aliases/functions with: type -a signalweave'
}

resume_command() {
    printf '"%s" setup' "$destination"
}

read_installed_version() {
    installed_version_output=$("$destination" --version 2>/dev/null) || fail 'Cannot identify the installed SignalWeave version; use --replace to upgrade explicitly'
    case "$installed_version_output" in
        'SignalWeave '*) installed_version=${installed_version_output#'SignalWeave '} ;;
        *) fail 'Installed executable did not report a SignalWeave version; use --replace to upgrade explicitly' ;;
    esac
    valid_version "v$installed_version" || fail 'Installed executable reported an unsupported SignalWeave version; use --replace to upgrade explicitly'
}

handle_setup_interrupt() {
    printf '\nSetup was canceled. The binary and completed local setup are preserved; resume with: ' >&2
    resume_command >&2
    printf '\n' >&2
    exit 130
}

run_wizard() {
    if [ -t 0 ]; then
        "$destination" setup
    elif ( : </dev/tty ) 2>/dev/null; then
        # With curl | sh, stdin is the installer source. Read wizard answers
        # from the controlling terminal instead of the consumed download pipe.
        "$destination" setup </dev/tty
    else
        printf 'Setup needs an interactive terminal. The binary is installed; resume in a terminal with: ' >&2
        resume_command >&2
        printf '\n' >&2
        return 2
    fi
}

run_setup_flow() {
    trap handle_setup_interrupt INT
    printf '%s\n' 'Starting guided setup. Your provider and BI credentials are entered in the terminal and stored in your private SignalWeave home.'
    if run_wizard; then
        printf 'Setup finished. Verify source access with "%s" health --live.\n' "$destination"
        return 0
    else
        status=$?
        if [ "$status" -eq 130 ]; then
            printf 'Setup was canceled. The binary and completed local setup are preserved; resume with: ' >&2
        else
            printf 'Setup did not finish (exit status %s). The binary is installed; resume safely with: ' "$status" >&2
        fi
        resume_command >&2
        printf '\nCompleted setup is preserved.\n' >&2
        return "$status"
    fi
}

if [ -e "$destination" ]; then
    [ -f "$destination" ] || fail 'Existing destination is not a regular file'
    if [ "$replace" != true ]; then
        read_installed_version
        if [ "$version" != latest ] && [ "$version" != "v$installed_version" ]; then
            fail "Installed SignalWeave v$installed_version differs from requested $version; use --replace to upgrade or --replace --setup to upgrade and resume setup"
        fi
        if [ "$run_setup" = true ]; then
            printf 'Already installed SignalWeave v%s at %s; keeping it and resuming setup. Use --replace --setup to upgrade and resume setup.\n' "$installed_version" "$destination"
            if run_setup_flow; then
                print_path_guidance
                exit 0
            else
                status=$?
                print_path_guidance
                exit "$status"
            fi
        fi
        fail "SignalWeave v$installed_version already installed; resume setup with \"$destination\" setup or use --replace to upgrade explicitly"
    fi
fi
if [ "$version" = latest ]; then
    note 'Resolving the latest release...'
    resolved=$(download --output /dev/null --write-out '%{url_effective}' "$release_base/latest") || fail 'Cannot resolve latest published release'
    case "$resolved" in "$release_base/tag/"*) version=${resolved#"$release_base/tag/"} ;; *) fail 'Unexpected release redirect' ;; esac
    valid_version "$version" || fail 'Latest release is not a stable version'
    case "$version" in *rc*) fail 'Latest must not resolve to a preview; select previews with --version' ;; esac
fi
mkdir -p "$install_dir"
install_dir=$(cd "$install_dir" && pwd -P) || fail 'Cannot resolve install directory'
destination=$install_dir/signalweave
[ ! -L "$destination" ] || fail 'Existing executable is a symlink; refusing replacement'
# Staging on the destination filesystem makes replacement a single rename.
stage=$(mktemp -d "$install_dir/.signalweave-install.XXXXXXXX") || fail 'Cannot create staging directory'
app_dir=
retain_runtime=false
cleanup() {
    # app_dir is one exact private mktemp child, never a caller-supplied deletion target.
    if [ -n "$app_dir" ] && [ "$retain_runtime" = false ]; then rm -rf "$app_dir"; fi
    rm -f "$stage/archive.tar.gz" "$stage/checksum" "$stage/names" "$stage/types" "$stage/signalweave"
    rmdir "$stage"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM
asset=signalweave-$version-$target.tar.gz
note "[1/4] Downloading SignalWeave $version ($target)"
download --output "$stage/checksum" "$release_base/download/$version/$asset.sha256" || fail 'No checksum available for this release/platform'
download --progress --output "$stage/archive.tar.gz" "$release_base/download/$version/$asset" || fail 'Release download failed'
note '[2/4] Verifying checksum and archive'
# Parse only a single conventional SHA256 line; never execute a downloaded path.
expected=$(awk -v name="$asset" 'NF == 2 && $2 == name && length($1) == 64 && $1 !~ /[^0-9a-f]/ {sum=$1; valid++} END {if (NR != 1 || valid != 1) exit 1; print sum}' "$stage/checksum") || fail 'Malformed release checksum'
actual=$(checksum "$stage/archive.tar.gz")
[ "$actual" = "$expected" ] || fail 'Checksum mismatch; nothing installed'
tar -tzf "$stage/archive.tar.gz" > "$stage/names" || fail 'Invalid archive'
awk '
    seen[$0]++ {bad=1; exit}
    $0 != "signalweave" && $0 != "LICENSE" && $0 != "build-info.json" {
        if ($0 !~ /^_internal\/[A-Za-z0-9_.+@\/ -]+$/) {bad=1; exit}
        n=split($0, parts, "/")
        for (i=1; i<=n; i++) if (parts[i] == "" || parts[i] == "." || parts[i] == "..") {bad=1; exit}
    }
    NR > 20003 {bad=1; exit}
    END {if (bad || NR < 3 || !seen["signalweave"] || !seen["LICENSE"] || !seen["build-info.json"]) exit 1}
' "$stage/names" || fail 'Unexpected archive paths'
tar -tvzf "$stage/archive.tar.gz" > "$stage/types" || fail 'Invalid archive metadata'
awk 'substr($0,1,1) != "-" {bad=1; exit} END {if (bad || NR < 3 || NR > 20003) exit 1}' "$stage/types" || fail 'Archive contains a link or special file'
note '[3/4] Preparing executable and checking startup...'
if grep -q '^_internal/' "$stage/names"; then
    runtime_root=$install_dir/.signalweave-runtime
    [ ! -L "$runtime_root" ] || fail 'Runtime directory must not be a symlink'
    mkdir -p "$runtime_root"
    chmod 700 "$runtime_root"
    runtime_count=0
    for existing_runtime in "$runtime_root"/v*; do
        [ -e "$existing_runtime" ] || [ -L "$existing_runtime" ] || continue
        runtime_name=${existing_runtime##*/}
        if printf '%s\n' "$runtime_name" | LC_ALL=C grep -Eq '^v[0-9]+\.[0-9]+\.[0-9]+(rc[0-9]+)?\.[A-Za-z0-9]{8}$'; then
            runtime_count=$((runtime_count + 1))
            if [ "$runtime_count" -ge 128 ]; then
                escaped_destination=$(printf '%s' "$destination" | sed 's/[\\$"`]/\\&/g')
                fail "Runtime retention limit reached (128). Stop servers, then run: \"$escaped_destination\" uninstall. Reinstall afterward; local data is kept by default."
            fi
        fi
    done
    app_dir=$(mktemp -d "$runtime_root/$version.XXXXXXXX") || fail 'Cannot create private runtime directory'
    # Every archive member was validated as a regular file with a bounded,
    # relative allowlisted path. No links, parent traversal or special files.
    tar -xzf "$stage/archive.tar.gz" -C "$app_dir" --no-same-owner || fail 'Cannot unpack runtime'
    escaped_native=$(printf '%s' "$app_dir/signalweave" | sed 's/[\\$"`]/\\&/g')
    printf '#!/bin/sh\n# SignalWeave managed runtime v1\nexec "%s" "$@"\n' "$escaped_native" > "$stage/signalweave"
else
    # Older releases remain installable as a single regular executable.
    tar -xOzf "$stage/archive.tar.gz" signalweave > "$stage/signalweave" || fail 'Cannot read executable'
fi
[ -s "$stage/signalweave" ] || fail 'Empty executable'
chmod 755 "$stage/signalweave"
# A failed startup must not replace a working installation.
"$stage/signalweave" --help >/dev/null || fail 'Executable cannot run on this system; existing installation unchanged'
if [ -n "$app_dir" ]; then
    printf '%s\n' 'signalweave-managed-runtime-v1' > "$app_dir/install-marker"
    # Retain before publishing: interruption after an atomic rename must not
    # delete a runtime now referenced by the launcher. Uninstall reclaims old builds.
    retain_runtime=true
fi
if [ "$replace" = true ]; then
    [ ! -L "$destination" ] || fail 'Destination became a symlink'
    [ ! -e "$destination" ] || [ -f "$destination" ] || fail 'Destination is not a regular file'
    mv -f "$stage/signalweave" "$destination"
else
    # Hard-link creation atomically refuses a concurrently created destination.
    ln "$stage/signalweave" "$destination" || fail 'Destination exists; nothing replaced'
fi
note '[4/4] Ready'
if [ "$quiet" = false ]; then printf 'Installed SignalWeave %s at %s\n' "$version" "$destination"; fi
if [ "$run_setup" = true ]; then
    if run_setup_flow; then
        print_path_guidance
    else
        status=$?
        print_path_guidance
        exit "$status"
    fi
else
    if [ "$quiet" = false ]; then
        if [ -f "${SIGNALWEAVE_HOME:-"${HOME}/.signalweave"}/config.toml" ]; then
            printf 'Configuration and cards kept. Check: "%s" health\n' "$destination"
            printf '%s\n' 'Restart or reconnect your agent to use the new version.'
        else
            printf 'Next: "%s" setup\n' "$destination"
        fi
    fi
    print_path_guidance
fi
if [ "$quiet" = false ]; then
    if [ "$run_setup" = true ]; then
        printf '%s\n' 'No shell profile was changed. Agent connections, if confirmed, were handled by setup.'
    else
        printf '%s\n' 'No shell profile or agent configuration was changed.'
    fi
fi
