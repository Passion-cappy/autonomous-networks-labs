#!/bin/sh
# Compose launcher shared by local checks and GitLab CI. It contains no topology.
set -eu
stage=${1:?Use pr03..pr07}; shift
case "$stage" in
  pr03) COMPOSE_FILE=compose.yaml ;;
  pr04) COMPOSE_FILE=compose.yaml:compose.network.yaml ;;
  pr05) COMPOSE_FILE=compose.yaml:compose.network.yaml:compose.monitoring.yaml ;;
  pr06) COMPOSE_FILE=compose.yaml:compose.network.yaml:compose.monitoring.yaml:compose.resilience.yaml ;;
  pr07) COMPOSE_FILE=compose.yaml:compose.network.yaml:compose.monitoring.yaml:compose.resilience.yaml:compose.ai.yaml ;;
  *) echo 'Use pr03..pr07' >&2; exit 2 ;;
esac
export COMPOSE_FILE COMPOSE_PATH_SEPARATOR=:
exec docker compose "$@"
