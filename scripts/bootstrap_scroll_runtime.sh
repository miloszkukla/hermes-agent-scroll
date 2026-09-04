#!/usr/bin/env bash
# Materialize the exact project-local runtime required by the Scroll sandbox.
set -euo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
UV_VERSION="0.12.9"
UV_ARCHIVE="uv-x86_64-unknown-linux-gnu.tar.gz"
UV_SHA256="ec7a99cd05e0cd7f80243f135ce1361c76835cb0ee60055d14d20eba8eba1460"
UV_URL="https://releases.astral.sh/github/uv/releases/download/${UV_VERSION}/${UV_ARCHIVE}"
PYTHON_RELEASE="20260901"
PYTHON_ARCHIVE="cpython-3.12.14+20260901-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz"
PYTHON_SHA256="72748da13197c1fb161e3afeef20a6a385ff24f2165e6e2758e47008e7faba4c"
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_RELEASE}/${PYTHON_ARCHIVE}"
UV_DIR="${ROOT}/.uv/tools/uv-x86_64-unknown-linux-gnu"
UV_BIN="${UV_DIR}/uv"
RUNTIME_DIR="${ROOT}/.scroll-runtime/cpython-3.12.14+20260901"
PYTHON_BIN="${RUNTIME_DIR}/bin/python3.12"
VENV_DIR="${ROOT}/.venv"
DOWNLOAD_DIR="${ROOT}/.scroll-runtime/downloads"

usage() {
    printf '%s\n' "usage: scripts/bootstrap_scroll_runtime.sh [--verify-only]"
}

case "${1:-}" in
    "") ;;
    --verify-only) VERIFY_ONLY=1 ;;
    --help|-h) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
esac

require_command() {
    command -v "$1" >/dev/null || { printf 'required command not found: %s\n' "$1" >&2; exit 1; }
}

verify_file() {
    local expected="$1" file="$2"
    printf '%s  %s\n' "$expected" "$file" | sha256sum --check --status || {
        printf 'digest mismatch: %s\n' "$file" >&2
        exit 1
    }
}

download() {
    local url="$1" expected="$2" destination="$3" temporary
    if [[ -f "$destination" ]]; then
        verify_file "$expected" "$destination"
        return
    fi
    mkdir -p "$(dirname -- "$destination")"
    temporary="$(mktemp "${destination}.tmp.XXXXXX")"
    trap 'rm -f -- "$temporary"' RETURN
    curl --fail --location --proto '=https' --tlsv1.2 --silent --show-error --output "$temporary" "$url"
    verify_file "$expected" "$temporary"
    mv -- "$temporary" "$destination"
    trap - RETURN
}

extract_uv() {
    local temporary
    temporary="$(mktemp -d "${ROOT}/.uv.bootstrap.XXXXXX")"
    trap 'rm -rf -- "$temporary"' RETURN
    tar -xzf "${DOWNLOAD_DIR}/${UV_ARCHIVE}" -C "$temporary"
    [[ -x "${temporary}/uv-x86_64-unknown-linux-gnu/uv" ]] || { printf 'unexpected uv archive layout\n' >&2; exit 1; }
    mkdir -p "$UV_DIR"
    install -m 0755 "${temporary}/uv-x86_64-unknown-linux-gnu/uv" "$UV_BIN"
    rm -rf -- "$temporary"
    trap - RETURN
}

extract_python() {
    local temporary
    [[ -x "$PYTHON_BIN" ]] && return
    temporary="$(mktemp -d "${ROOT}/.scroll-runtime.bootstrap.XXXXXX")"
    trap 'rm -rf -- "$temporary"' RETURN
    tar -xzf "${DOWNLOAD_DIR}/${PYTHON_ARCHIVE}" -C "$temporary"
    [[ -x "${temporary}/python/bin/python3.12" ]] || { printf 'unexpected CPython archive layout\n' >&2; exit 1; }
    mkdir -p "$(dirname -- "$RUNTIME_DIR")"
    mv -- "${temporary}/python" "$RUNTIME_DIR"
    rm -rf -- "$temporary"
    trap - RETURN
}

require_command curl
require_command install
require_command sha256sum
require_command tar
download "$UV_URL" "$UV_SHA256" "${DOWNLOAD_DIR}/${UV_ARCHIVE}"
download "$PYTHON_URL" "$PYTHON_SHA256" "${DOWNLOAD_DIR}/${PYTHON_ARCHIVE}"
extract_uv
extract_python
[[ "$("$UV_BIN" --version)" == "uv ${UV_VERSION} "* ]] || { printf 'unexpected uv version\n' >&2; exit 1; }
[[ "$("$PYTHON_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')" == "3.12.14" ]] || { printf 'unexpected CPython version\n' >&2; exit 1; }

if [[ "${VERIFY_ONLY:-0}" == 1 ]]; then
    exit 0
fi
if [[ -e "$VENV_DIR" ]]; then
    [[ -x "${VENV_DIR}/bin/python" ]] || { printf 'refusing to replace invalid existing .venv\n' >&2; exit 1; }
    [[ "$("${VENV_DIR}/bin/python" -c 'import sys; print(sys.base_prefix)')" == "$RUNTIME_DIR" ]] || {
        printf 'refusing to replace existing .venv with a different base Python; preserve or remove it explicitly first\n' >&2
        exit 1
    }
else
    "$UV_BIN" venv --python "$PYTHON_BIN" "$VENV_DIR"
fi
"$UV_BIN" sync --locked --extra scroll --python "$PYTHON_BIN"
