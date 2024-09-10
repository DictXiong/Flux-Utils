#!/usr/bin/env python3
## for Juwei S1B/S1WB

import time
import sys
import argparse
import serial
import asyncio
from third_party import WatchDog


parser = argparse.ArgumentParser(description="Read data from electricity meter")
parser.add_argument("--debug", action="store_true", help="debug mode")
parser.add_argument("--interval", metavar='N', type=int, default=3, help="print every N data")
parser.add_argument("--dev", type=str, help="serial device (SPP)")
parser.add_argument("--address", type=str, help="address (BLE)")
parser.add_argument("--scan-ble", action="store_true", help="scan BLE devices")
args = parser.parse_args()
assert args.interval > 0


def eprint(*args, **kwargs):
    print("electricity-meter:", *args, file=sys.stderr, **kwargs)

watch_dog = WatchDog(120, eprint)

def parse_data(raw_data):
    voltage = int.from_bytes(raw_data[5:7], "big") / 10.0
    current = int.from_bytes(raw_data[8:10], "big") / 1000.0
    power = int.from_bytes(raw_data[11:13], "big") / 10.0
    kwh = int.from_bytes(raw_data[15:17], "big") / 100.0
    price = int.from_bytes(raw_data[19:20], "big") / 100.0
    freq = int.from_bytes(raw_data[20:22], "big") / 10.0
    coef = int.from_bytes(raw_data[22:24], "big") / 1000.0
    temperature = int.from_bytes(raw_data[25:26], "big")
    h = int.from_bytes(raw_data[26:28], "big")
    m = int.from_bytes(raw_data[28:29], "big")
    s = int.from_bytes(raw_data[29:30], "big")
    ans = {
        "voltage": voltage,
        "current": current,
        "power": power,
        "kwh": kwh,
        "price": price,
        "freq": freq,
        "coef": coef,
        "temperature": temperature,
        "h": h,
        "m": m,
        "s": s,
    }
    return ans


def debug_print(data):
    eprint(
        f'{data["voltage"]}V {data["current"]}A {data["power"]}W {data["coef"]} {data["freq"]}Hz {data["kwh"]}kwh {data["temperature"]}c {data["h"]}:{data["m"]}:{data["s"]} ￥{data["price"]}'
    )


def influx_print(data):
    timestamp = str(int(time.time())) + "000000000"
    print(
        f"electricity_meter voltage={data['voltage']},current={data['current']},power={data['power']},electricity={data['kwh']},frequency={data['freq']},factor={data['coef']},temperature={data['temperature']} {timestamp}",
        flush=True,
    )


def run_spp(path):
    print_count = 0
    ser = serial.Serial(path, 9600, timeout=1)
    reconnect_count = 0
    reconnect_threshold = 20
    worked = False
    while True:
        raw_data = ser.read(36)
        if len(raw_data) == 0:
            raw_data = ser.read(36)
        if len(raw_data) < 32 or raw_data[0:4] != b"\xff\x55\x01\x01":
            worked = False
            if reconnect_count > reconnect_threshold:
                raise serial.SerialException("too many errors")
            eprint(
                f"invalid data (len={len(raw_data)}), retry {reconnect_count}/{reconnect_threshold}"
            )
            reconnect_count += 1
            continue
        reconnect_count = 0
        data = parse_data(raw_data)
        if not worked:
            eprint("successfully got data")
            worked = True
        if args.debug:
            debug_print(data)
        if print_count % args.interval == 0:
            influx_print(data)
            print_count = 0
        print_count += 1


async def scan_ble():
    import bleak
    def device_str(d, adv):
        return f"{d.name} ({d.address}) RSSI: {adv.rssi} dBm"

    eprint("Scanning...")
    devices = await asyncio.wait_for(bleak.BleakScanner.discover(timeout=10, return_adv=True), timeout=20)
    for k, v in devices.items():
        d = v[0]
        adv = v[1]
        if d.name is not None and d.name.startswith("S1BP"):
            eprint(device_str(d, adv))


async def run_ble(address):
    import bleak
    eprint(f"Job started on {address}")
    print_count = 0
    worked = False
    watch_dog.on()

    def notify_cb(sender, data):
        watch_dog.touch()
        nonlocal print_count
        nonlocal worked
        if len(data) == 36 and data[0:4] == b"\xff\x55\x01\x01":
            data = parse_data(data)
            if not worked:
                eprint("Successfully got data")
                worked = True
            if args.debug:
                debug_print(data)
            if print_count % args.interval == 0:
                influx_print(data)
                print_count = 0
            print_count += 1
        else:
            worked = False
            eprint(f"Invalid data {data} (len={len(data)}))")

    def disconnect_cb(client):
        eprint(f"Disconnected callback")

    while True:
        watch_dog.touch()
        worked = False
        try:
            eprint(f"Connecting to {address}")
            async with bleak.BleakClient(
                address, disconnected_callback=disconnect_cb
            ) as client:
                eprint("Connected")
                while True:
                    watch_dog.touch()
                    if not client.is_connected:
                        eprint("Disconnected")
                        break
                    await client.start_notify(
                        "0000ffe1-0000-1000-8000-00805f9b34fb", notify_cb
                    )
                    while client.is_connected:
                        await asyncio.sleep(10)
        except Exception as e:
            if isinstance(e, bleak.exc.BleakDeviceNotFoundError):
                eprint(f"{address} not found, retrying in 60 seconds")
                await asyncio.sleep(60)
            elif "[org.bluez.Error.InProgress]" in str(e):
                eprint(f"Device busy, retrying in 20 seconds")
                await asyncio.sleep(20)
            else:
                eprint(
                    f"Failed connecting, retrying in 10 seconds. Error {type(e)}: {str(e)}"
                )
                await asyncio.sleep(10)


async def main():
    if args.scan_ble:
        await scan_ble()
    if args.address:
        await asyncio.gather(watch_dog.loop(), run_ble(args.address))
    elif args.dev:
        while True:
            try:
                run_spp(args.dev)
            except serial.SerialException as e:
                eprint(f"failed to connect: {str(e)}. retry ...")
                time.sleep(10)
    else:
        eprint("No device specified. Either --dev or --address is required.")
        exit(1)


if __name__ == "__main__":
    asyncio.run(main())
