#!/usr/bin/env bash
# Smart launcher for hololens_publisher.
#
# Non-interactive mode:
#   REC=true SIM=false PUB=true SHM=false HOST_DIR=./recordings ./run-publisher.sh
#
# Interactive mode:
#   ./run-publisher.sh
#   (prompts for mode/publish/shm/path)

set -euo pipefail

to_bool() {
  local raw="${1:-}"
  case "${raw,,}" in
    1|true|yes|y|on) echo "true" ;;
    *) echo "false" ;;
  esac
}

is_set() {
  local name="$1"
  [[ -n "${!name:-}" ]]
}

prompt_yes_no() {
  local msg="$1"
  local default="$2" # true|false
  local hint="[y/N]"
  [[ "$default" == "true" ]] && hint="[Y/n]"
  while true; do
    read -r -p "$msg $hint: " answer
    if [[ -z "${answer}" ]]; then
      echo "$default"
      return
    fi
    case "${answer,,}" in
      y|yes) echo "true"; return ;;
      n|no) echo "false"; return ;;
      *) echo "Please answer y or n." ;;
    esac
  done
}

interactive_mode="false"
if ! is_set REC && ! is_set SIM && ! is_set PUB && ! is_set SHM && ! is_set HOST_DIR && ! is_set host_dir && ! is_set SETTINGS_MODE && ! is_set ZENOH_ENABLED && ! is_set ZENOH_USE_SHM; then
  interactive_mode="true"
fi

# Resolve host recordings directory.
host_dir_val="${HOST_DIR:-${host_dir:-./recordings}}"

settings_mode_val="${SETTINGS_MODE:-}"
zenoh_enabled_val="${ZENOH_ENABLED:-}"
zenoh_use_shm_val="${ZENOH_USE_SHM:-}"

if [[ "$interactive_mode" == "true" ]]; then
  echo "Publisher start wizard"
  echo "Select mode:"
  echo "  1) live"
  echo "  2) record"
  echo "  3) simulation"
  read -r -p "Choice [1-3] (default 1): " mode_choice
  case "${mode_choice:-1}" in
    2) settings_mode_val="record" ;;
    3) settings_mode_val="simulation" ;;
    *) settings_mode_val="live" ;;
  esac

  zenoh_enabled_val="$(prompt_yes_no 'Publish to Zenoh?' 'true')"
  if [[ "$zenoh_enabled_val" == "true" ]]; then
    zenoh_use_shm_val="$(prompt_yes_no 'Use Zenoh shared memory (SHM)?' 'false')"
  else
    zenoh_use_shm_val="false"
  fi

  # Ask for host recordings directory only when mode needs recording files.
  if [[ "$settings_mode_val" == "record" || "$settings_mode_val" == "simulation" ]]; then
    read -r -p "Host recordings directory (default: ${host_dir_val}): " host_input
    if [[ -n "${host_input}" ]]; then
      host_dir_val="${host_input}"
    fi
  else
    echo "Live mode selected; skipping recordings directory prompt."
  fi
else
  # Backward-compatible mapping from legacy REC/SIM/PUB/SHM flags.
  if [[ -z "$settings_mode_val" ]]; then
    if [[ "$(to_bool "${SIM:-false}")" == "true" ]]; then
      settings_mode_val="simulation"
    elif [[ "$(to_bool "${REC:-false}")" == "true" ]]; then
      settings_mode_val="record"
    else
      settings_mode_val="live"
    fi
  fi

  if [[ -z "$zenoh_enabled_val" ]]; then
    if is_set PUB; then
      zenoh_enabled_val="$(to_bool "${PUB}")"
    else
      zenoh_enabled_val="true"
    fi
  else
    zenoh_enabled_val="$(to_bool "$zenoh_enabled_val")"
  fi

  if [[ -z "$zenoh_use_shm_val" ]]; then
    if is_set SHM; then
      zenoh_use_shm_val="$(to_bool "${SHM}")"
    else
      zenoh_use_shm_val="false"
    fi
  else
    zenoh_use_shm_val="$(to_bool "$zenoh_use_shm_val")"
  fi
fi

mkdir -p "$host_dir_val"

echo "Starting hololens_publisher with:"
echo "  SETTINGS_MODE=${settings_mode_val}"
echo "  ZENOH_ENABLED=${zenoh_enabled_val}"
echo "  ZENOH_USE_SHM=${zenoh_use_shm_val}"
echo "  host_dir=${host_dir_val}"

host_dir="$host_dir_val" \
SETTINGS_MODE="$settings_mode_val" \
ZENOH_ENABLED="$zenoh_enabled_val" \
ZENOH_USE_SHM="$zenoh_use_shm_val" \
SETTINGS_DATA_DIR="/root/app/recordings" \
docker compose up hololens_publisher
