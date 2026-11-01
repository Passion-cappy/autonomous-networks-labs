#!/bin/sh
# Compatibility entry point: the full check includes and restores the experiments.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec sh "$HERE/check.sh" "${1:-pr06}"
