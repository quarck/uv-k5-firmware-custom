#!/usr/bin/env bash
# viewlog.sh -- pull the spectrum logger's store off the radio, render it, open it.
#
#   ./viewlog.sh                  # finds the cable, if there is exactly one
#   ./viewlog.sh /dev/ttyUSB1     # or name the port
#   PORT=/dev/ttyUSB1 ./viewlog.sh
#
# Writes logs/log_<date>_<time>.csv, renders logs/log_<date>_<time>.html beside
# it, and opens that. Stops at the first failure: a dump that did not happen is
# not worth rendering.

set -euo pipefail

# Run from the repo, so the python scripts and logs/ are found wherever this is
# called from.
cd "$(dirname "$(readlink -f "$0")")"

PY=$(command -v python3 || command -v python) || true
if [ -z "$PY" ]; then
    echo "viewlog: no python on PATH" >&2
    exit 1
fi

# The device pattern is overridable: some cables come up as /dev/ttyACM*, and
# the tests use it to fake a port.
glob=${K5_PORT_GLOB:-/dev/ttyUSB*}

port=${1:-${PORT:-}}
if [ -z "$port" ]; then
    ports=()
    for p in $glob; do
        [ -e "$p" ] && ports+=("$p")
    done
    case ${#ports[@]} in
        0)
            echo "viewlog: nothing matching $glob -- is the programming cable plugged in?" >&2
            exit 1
            ;;
        1)
            port=${ports[0]}
            echo "viewlog: using $port"
            ;;
        *)
            echo "viewlog: several ports visible, name the one you want:" >&2
            printf '  %s\n' "${ports[@]}" >&2
            exit 1
            ;;
    esac
fi

if [ ! -e "$port" ]; then
    echo "viewlog: $port does not exist" >&2
    exit 1
fi
if [ ! -r "$port" ] || [ ! -w "$port" ]; then
    echo "viewlog: $port is not read/write for you -- are you in the dialout group?" >&2
fi

stamp=$(date +%Y%m%d_%H%M%S)
csv="logs/log_$stamp.csv"
html="logs/log_$stamp.html"
mkdir -p logs

echo "viewlog: dumping to $csv"
"$PY" k5logdump.py -p "$port" dump "$csv"

echo "viewlog: rendering $html"
"$PY" k5logview.py "$csv" -o "$html"

if command -v xdg-open >/dev/null 2>&1; then
    echo "viewlog: opening $html"
    # Detached and quiet: xdg-open hands off to a browser that then owns the
    # terminal's stderr otherwise.
    xdg-open "$html" >/dev/null 2>&1 &
else
    echo "viewlog: no xdg-open here; the report is at $html"
fi
