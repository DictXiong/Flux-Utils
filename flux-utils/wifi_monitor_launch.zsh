#!/usr/bin/env zsh
set -ex

kill_process() {
    pkill airodump-ng || true
}

trap kill_process EXIT
kill_process
rm /dev/shm/flux_wifi_monitor* || true
airodump-ng ${FLUX_WIFI_DEV:-wlan0} --background 1 --band bga --write /dev/shm/flux_wifi_monitor --output-format csv --write-interval 30
