#!/usr/bin/env python3

import time
import argparse
import sys
from dateutil import parser as date_parser


parser = argparse.ArgumentParser(description='Report WiFi Scan Result')
parser.add_argument('--berlin', type=int, default=600, help='Time before removing the AP/client from the list')
args = parser.parse_args()

def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)

log_path = f'/dev/shm/flux_wifi_monitor-01.csv'

def run():
    ap_counter = 0
    station_counter = 0
    section = 'ap'
    with open(log_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith('BSSID'):
                section = 'ap'
            elif line.startswith('Station'):
                section = 'station'
            else:
                last_time = line.split(',')[2]
                if time.time() - date_parser.parse(last_time).timestamp() > args.berlin:
                    continue
                if section == 'ap':
                    ap_counter += 1
                elif section == 'station':
                    station_counter += 1
    timestamp = str(int(time.time())) + "000000000"
    if ap_counter > 0 or station_counter > 0:
        print(f"wifi_monitor ap_count={ap_counter}i,station_count={station_counter}i {timestamp}")
    else:
        eprint('no active ap or station found. is wifi monitor running?')


if __name__ == '__main__':
    try:
        run()
    except FileNotFoundError:
        eprint(f'logfile {log_path} not found. is wifi monitor running?')
        sys.exit(1)
