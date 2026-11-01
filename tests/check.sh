#!/bin/sh
# Trusted test utility; Python is installed here, not on the student's host.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=${NETLAB_PROJECT_DIR:-$(CDPATH= cd -- "$HERE/.." && pwd)}
stage=${1:-pr03}
case "$stage" in pr0[3-7]) ;; *) echo 'Use: sh tests/check.sh pr03..pr07 [--quick]' >&2; exit 2 ;; esac
shift || true
cd "$ROOT"
ROOT=$(pwd)
OUT=${NETLAB_RESULTS_DIR:-$ROOT/results/checks}
mkdir -p "$OUT"
export_report() {
  report_id=$1
  case "$report_id" in ''|*[!a-zA-Z0-9_-]*) echo 'Invalid report identifier.' >&2; return 2 ;; esac
  mkdir -p "$ROOT/docs/reports"
  cp "$OUT/$report_id/report.md" "$ROOT/docs/reports/$stage.md"
  printf '[INFO] Git report: docs/reports/%s.md\n' "$stage"
}
preflight_error() {
  code=$1
  reason=$2
  action=$3
  id="env-$(date -u +%Y%m%dT%H%M%SZ)-$$"
  mkdir -p "$OUT/$id"
  case "$stage" in pr03) count=7 ;; pr04) count=12 ;; pr05) count=14 ;; pr06) count=16 ;; pr07) count=23 ;; esac
  maximum=10; [ "$stage" != pr07 ] || maximum=12
  cat > "$OUT/$id/report.md" <<EOF
---
id: netlab-check-$id
type: runtime-report
discipline: proektuvannia-avtonomykh-merezh
status: draft
version: 1
updated: '$(date -u +%Y-%m-%d)'
sources: []
---

# $stage: перевірку не запущено

Оцінка /$maximum не визначена: середовище перевірки ще не готове. Це не автоматичний нуль. Усі роботи оцінюються автоматично після повного запуску.

Виконано 0/$count; $count перевірок стенда заблоковані.

Очікується: робочий Docker Linux engine, .env і зібрана тестова утиліта.

Факт: $reason

Наступна дія: $action

Після виправлення повторіть sh tests/check.sh $stage. Подробиці збірки, якщо вона починалася: results/checks/bootstrap.log.
EOF
  printf '{"schema":1,"stage":"%s","status":"environment-not-ready","machine_score":null,"max_points":%s,"completed_checks":0,"total_checks":%s,"counts":{"blocked":%s}}\n' "$stage" "$maximum" "$count" "$count" > "$OUT/$id/assessment.json"
  printf '{"run_id":"%s","report":"%s/assessment.json"}\n' "$id" "$id" > "$OUT/latest-$stage.json"
  export_report "$id"
  printf '[ERROR] %s\nNext: %s\nReport: results/checks/%s/report.md\n' "$reason" "$action" "$id" >&2
  exit "$code"
}
if ! docker info >/dev/null 2>&1; then
  preflight_error 2 'Docker server is unavailable.' 'Start Linux engine; run docker version; see docs/platforms.md.'
fi
if [ ! -f .env ]; then
  preflight_error 1 '.env is missing.' 'Run cp .env.example .env in the project root.'
fi
probe_image=${NETLAB_PROBE_IMAGE:-$(sed -n 's/^BASE_IMAGE=//p' .env | tr -d '\r')}
cli_image=${NETLAB_CLI_IMAGE:-$(sed -n 's/^CI_IMAGE=//p' .env | tr -d '\r')}
case "$probe_image" in python:[0-9]*-alpine) ;; *) preflight_error 1 'Invalid BASE_IMAGE.' 'Restore the reviewed numbered Python tag from .env.example.' ;; esac
case "$cli_image" in docker:[0-9]*-cli) ;; *) preflight_error 1 'Invalid CI_IMAGE.' 'Restore the reviewed numbered Docker CLI tag from .env.example.' ;; esac
host_path() {
  if command -v cygpath >/dev/null 2>&1; then cygpath -am "$1"; else printf '%s\n' "$1"; fi
}
export MSYS_NO_PATHCONV=1
echo '[INFO] Preparing the test utility from official Docker Hub images (first run downloads packages).'
if ! docker image inspect "$probe_image" >/dev/null 2>&1; then
  docker pull "$probe_image" || preflight_error 2 'Python probe image pull failed.' 'Check access to Docker Hub and retry.'
fi
if ! docker image inspect "$cli_image" >/dev/null 2>&1; then
  docker pull "$cli_image" || preflight_error 2 'Docker CLI image pull failed.' 'Check access to Docker Hub and retry.'
fi
if ! docker build --build-arg "DOCKER_IMAGE=$cli_image" -f "$(host_path "$HERE/Dockerfile.checks")" -t autonomous-netlab/checks:local "$(host_path "$HERE")" >"$OUT/bootstrap.log" 2>&1; then
  tail -n 12 "$OUT/bootstrap.log" >&2
  preflight_error 2 'Test utility build failed.' 'Read bootstrap.log; retry Docker Hub and Alpine package repository access.'
fi
group=$(sh "$HERE/compose.sh" "$stage" --profile monitoring --profile ai config --format json 2>/dev/null | sed -n 's/^  "name": "\([^"]*\)".*/\1/p' | head -n 1)
group=${group:-${COMPOSE_PROJECT_NAME:-autonomous-netlab}}
case "$group" in *[!a-z0-9_-]*|'') preflight_error 1 'Invalid Compose project name.' 'Use lowercase Latin letters, digits, underscore or hyphen.' ;; esac
anchor=$(docker create --name "$group-paths-$$" --label "com.docker.compose.project=$group" --label com.docker.compose.service=checks --mount "type=bind,source=$(host_path "$ROOT"),target=/project" --mount "type=bind,source=$(host_path "$HERE"),target=/checks,readonly" --mount "type=bind,source=$(host_path "$OUT"),target=/output" autonomous-netlab/checks:local -c 'pass')
trap 'docker rm -f "$anchor" >/dev/null 2>&1 || true' EXIT
project_source=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/project"}}{{.Source}}{{end}}{{end}}' "$anchor")
checks_source=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/checks"}}{{.Source}}{{end}}{{end}}' "$anchor")
output_source=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/output"}}{{.Source}}{{end}}{{end}}' "$anchor")
linux_path() {
  case "$1" in
    [A-Za-z]:/*) drive=$(printf '%s' "$1" | cut -c1 | tr '[:upper:]' '[:lower:]'); printf '/run/desktop/mnt/host/%s/%s\n' "$drive" "${1#??/}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}
project_path=$(linux_path "$project_source")
checks_path=$(linux_path "$checks_source")
output_path=$(linux_path "$output_source")
docker rm "$anchor" >/dev/null
trap - EXIT
result=0
# Never export a previous report if the controller fails before writing a new one.
rm -f "$OUT/latest-$stage.json"
docker run --rm --name "$group-check-$stage-$$" --label "com.docker.compose.project=$group" --label com.docker.compose.service=checks --network none --cap-drop ALL --cap-add CHOWN --security-opt no-new-privileges:true --memory 192m --pids-limit 96 \
  --mount type=bind,source=/var/run/docker.sock,target=/var/run/docker.sock \
  --mount "type=bind,source=$project_source,target=$project_path" \
  --mount "type=bind,source=$checks_source,target=$checks_path,readonly" \
  --mount "type=bind,source=$output_source,target=/output" \
  -e COMPOSE_PROJECT_NAME -e COMPOSE_IGNORE_ORPHANS=1 -e "NETLAB_CI_WITHOUT_MODEL=${NETLAB_CI_WITHOUT_MODEL:-0}" \
  -e "NETLAB_PROBE_IMAGE=$probe_image" \
  -e "NETLAB_TRUSTED_GRADER=${NETLAB_TRUSTED_GRADER:-}" \
  autonomous-netlab/checks:local "$checks_path/run.py" "$stage" --project "$project_path" --output-source "$output_path" "$@" || result=$?
if [ ! -f "$OUT/latest-$stage.json" ]; then
  preflight_error 2 'Test controller did not create a fresh report.' 'Read Docker output and retry the complete check; do not submit an old report.'
fi
report_id=$(sed -n 's/.*"run_id": *"\([^"]*\)".*/\1/p' "$OUT/latest-$stage.json" | head -n 1)
export_report "$report_id"
exit "$result"
