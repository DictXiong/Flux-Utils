#!/usr/bin/env python3

import time
import sys
import argparse
import asyncio
import contextlib
from bleak import BleakScanner, BleakClient, exc
from third_party import dew_point, normalize_pressure, WatchDog

def eprint(*args, **kwargs):
    print("blitz:", *args, file=sys.stderr, **kwargs)


parser = argparse.ArgumentParser(description='Read data from Blitz sensors')
parser.add_argument('--debug', action='store_true', help='debug mode')
parser.add_argument('--min-interval', metavar='N', type=int, default=120, help='print every N seconds')
parser.add_argument('--scan', action='store_true', help='scan BLE devices')
parser.add_argument('--altitude', type=float, default=None, help='local altitude')
parser.add_argument('sensors', metavar='name,addr[,mask]', type=str, help='(multiple) sensor names and addresss', nargs='*')
args = parser.parse_args()
assert args.min_interval >= 60

gatt_report = "0000f121-0000-1000-8000-00805f9b34fb"
watch_dog = WatchDog(120, eprint)


class BLESensorStatus:
    def __init__(self):
        self.is_htu21d_online = False
        self.is_bmp280_online = False
        self.is_gy302_online = False
        self.is_sht4x_online = False
        self.is_end_of_battery = False

    def parse(self, data:int):
        assert data >= 0 and data <= 255
        self.is_htu21d_online = (data & 0x80) != 0
        self.is_bmp280_online = (data & 0x40) != 0
        self.is_gy302_online = (data & 0x20) != 0
        self.is_sht4x_online = (data & 0x10) != 0
        self.is_end_of_battery = (data & 0x01) != 0
        assert not (self.is_htu21d_online and self.is_sht4x_online)

    def __str__(self) -> str:
        return f"HTU21D: {self.is_htu21d_online}, BMP280: {self.is_bmp280_online}, GY302: {self.is_gy302_online}, SHT4X: {self.is_sht4x_online}, Battery: {self.is_end_of_battery}"

'''
report data
0     0x12
1     device_status (7: HTU21D, 6: BMP280, 5: GY302, 4: SHT4x, 0: low battery)
2:3   supply voltage (*1000)
4:5   htu21d/sht4x temperature (raw)
6:7   htu21d/sht4x humidity (raw)
8:11  bmp280 pressure (*25600)
12:13 bmp280 temperature (*100)
14:15 gy302 light (*1.2)
16    0x23
'''
def parse_data(raw_data:bytearray, mask=0xff):
    def supply_voltage(data:bytearray):
        assert len(data) == 2
        return int.from_bytes(data, byteorder='little', signed=False) / 1000.0
    def htu21d_temperature(data:bytearray):
        assert len(data) == 2
        return int.from_bytes(data, byteorder='little', signed=False) * 175.72 / 65536.0 - 46.85
    def htu21d_humidity(data:bytearray):
        assert len(data) == 2
        ans = int.from_bytes(data, byteorder='little', signed=False) * 125.0 / 65536.0 - 6.0
        if ans > 100:
            ans = 100.0
        if ans < 0:
            ans = 0.0
        return ans
    def sht4x_temperature(data:bytearray):
        assert len(data) == 2
        return int.from_bytes(data, byteorder='little', signed=False) * 175.0 / 65535.0 - 45.0
    def sht4x_humidity(data:bytearray):
        assert len(data) == 2
        ans = int.from_bytes(data, byteorder='little', signed=False) * 125.0 / 65535.0 - 6.0
        if ans > 100:
            ans = 100.0
        if ans < 0:
            ans = 0.0
        return ans
    def bmp280_pressure(data:bytearray):
        assert len(data) == 4
        return int.from_bytes(data, byteorder='little', signed=False) / 25600.0
    def bmp280_temperature(data:bytearray):
        assert len(data) == 2
        return int.from_bytes(data, byteorder='little', signed=True) / 100.0
    def gy302_light(data:bytearray):
        assert len(data) == 2
        return int.from_bytes(data, byteorder='little', signed=False) / 1.2
    assert len(raw_data) == 17
    ans = {}
    ble_sensor_status = BLESensorStatus()
    ble_sensor_status.parse(raw_data[1] & mask)
    ans["status"] = ble_sensor_status
    ans["supply_voltage"] = supply_voltage(raw_data[2:4])
    if ble_sensor_status.is_sht4x_online:
        ans["temperature"] = sht4x_temperature(raw_data[4:6])
        ans["humidity"] = sht4x_humidity(raw_data[6:8])
    elif ble_sensor_status.is_htu21d_online:
        ans["temperature"] = htu21d_temperature(raw_data[4:6])
        ans["humidity"] = htu21d_humidity(raw_data[6:8])
    if ble_sensor_status.is_bmp280_online:
        ans["pressure"] = bmp280_pressure(raw_data[8:12])
        ans["temperature_aux"] = bmp280_temperature(raw_data[12:14])
    if ble_sensor_status.is_gy302_online:
        ans["light"] = gy302_light(raw_data[14:16])
    return ans


async def scan(address=None):
    def device_str(d, adv):
        return f"{d.name} ({d.address}) RSSI: {adv.rssi} dBm"
    eprint("Scanning...")
    if address is None:
        devices = await asyncio.wait_for(BleakScanner.discover(timeout=10, return_adv=True), timeout=20)
        for k,v in devices.items():
            d = v[0]
            adv = v[1]
            if d.name is not None and d.name.startswith("Blitz"):
                eprint(device_str(d, adv))
    else:
        device = await BleakScanner.find_device_by_address(address, timeout=10, return_adv=True)
        if device is not None:
            return device
        eprint(f"device {address} not found")


def debug_print(sensor, data):
    ans = str(data["status"]) + f", Supply voltage: {data['supply_voltage']} V"
    if data["status"].is_sht4x_online:
        ans += f", SHT4X: {data['temperature']} C, {data['humidity']} %"
    elif data["status"].is_htu21d_online:
        ans += f", HTU21D: {data['temperature']} C, {data['humidity']} %"
    if data["status"].is_bmp280_online:
        ans += f", BMP280: {data['pressure']} hPa, {data['temperature_aux']} C"
    if data["status"].is_gy302_online:
        ans += f", GY302: {data['light']} lux"
    eprint(f"{sensor}: {ans}")


def influx_print(sensor, data):
    timestamp = int(time.time() * 1000000000)
    measurement = f"blitz,sensor={sensor}"
    print(f"{measurement} supply_voltage={data['supply_voltage']} {timestamp}", flush=True)
    if data["status"].is_htu21d_online or data["status"].is_sht4x_online:
        print(f"{measurement} temperature={data['temperature']},humidity={data['humidity']} {timestamp}", flush=True)
    if data["status"].is_bmp280_online:
        print(f"{measurement} pressure={data['pressure']} {timestamp}", flush=True)
        if args.altitude:
            print(f"{measurement} pressure_normalized={normalize_pressure(data['pressure'], args.altitude)} {timestamp}", flush=True)
        temp_tag = "temperature_aux" if data["status"].is_htu21d_online or data["status"].is_sht4x_online else "temperature"
        print(f"{measurement} {temp_tag}={data['temperature_aux']} {timestamp}", flush=True)
    if "temperature" in data and "pressure" in data and "humidity" in data:
        print(f"{measurement} dew_point={dew_point(data['temperature'], data['pressure'], data['humidity'])} {timestamp}", flush=True)
    if data["status"].is_gy302_online:
        print(f"{measurement} light={data['light']} {timestamp}", flush=True)


async def blitz_access(name, address, lock, latency, mask=0xff):
    def named_print(*args, **kwargs):
        eprint(f"[{name}]", *args, **kwargs)
    def cb(client):
        named_print(f"Disconnected callback")
    await asyncio.sleep(latency)
    named_print(f"Job started for {address} with mask {mask}")
    timeout_count = 0
    while True:
        worked = False
        try:
            named_print(f"Will connect to {address}")
            async with contextlib.AsyncExitStack() as stack:
                async with lock:
                    named_print(f"Scanning...")
                    # may hang, may be a bug. so use a custom watch dog
                    watch_dog.on()
                    device = await BleakScanner.find_device_by_address(address, timeout=20)
                    watch_dog.off()
                    if device is None:
                        raise exc.BleakDeviceNotFoundError(f"Device {address} not found")
                    named_print(f"Found {device.name}, connecting...")
                    client = BleakClient(device, timeout=60, disconnected_callback=cb)
                    watch_dog.on()
                    await stack.enter_async_context(client)
                    watch_dog.off()
            # async with BleakClient(address, timeout=60, disconnected_callback=cb) as client:
                named_print(f"Connected")
                while True:
                    if not client.is_connected:
                        break
                    start_time = time.time()
                    try:
                        async with lock:
                            raw_data = await client.read_gatt_char(gatt_report)
                    except Exception as e:
                        if "Not connected" in str(e):
                            break
                        named_print(f"Failed reading data, retrying in 3 seconds. Error {type(e)}: {str(e)}")
                        worked = False
                        await asyncio.sleep(3)
                        continue
                    if len(raw_data) != 17 or raw_data[0] != 0x12 or raw_data[16] != 0x23:
                        named_print(f"Invalid data: {raw_data}")
                        if raw_data == b"\x00" * 17:
                            named_print(f"Device is not ready, retrying in 30 seconds")
                            await asyncio.sleep(30)
                        worked = False
                        continue
                    data = parse_data(raw_data, mask)
                    if not worked:
                        worked = True
                        named_print(f"Successfully got data")
                    if not data["status"].is_sht4x_online and not data["status"].is_htu21d_online and not data["status"].is_bmp280_online and not data["status"].is_gy302_online:
                        named_print(f"WARNING: No sensor online!")
                    if data["status"].is_end_of_battery:
                        named_print(f"WARNING: Low battery!")
                    if args.debug:
                        debug_print(name, data)
                    influx_print(name, data)
                    timeout_count = 0
                    sleep_time = args.min_interval - (time.time() - start_time)
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)
            named_print(f"Disconnected, retrying in 3 seconds")
            await asyncio.sleep(3)
        except Exception as e:
            watch_dog.off()
            if isinstance(e, exc.BleakDeviceNotFoundError):
                named_print(f"{address} not found, retrying in 60 seconds")
                await asyncio.sleep(60)
            elif "No powered Bluetooth adapters found" in str(e):
                named_print(f"No available BT adapters, retrying in 60 seconds")
                await asyncio.sleep(60)
            elif "[org.bluez.Error.InProgress]" in str(e):
                named_print(f"Device busy, retrying in 20 seconds")
                await asyncio.sleep(20)
            else:
                named_print(f"Failed connecting, retrying in 3 seconds. Error {type(e)}: {str(e)}")
                if isinstance(e, asyncio.exceptions.TimeoutError):
                    timeout_count += 1
                    if timeout_count > 10:
                        named_print(f"Too many timeouts, wait 60 seconds")
                        await asyncio.sleep(60)
                        # await scan(address)
                        # timeout_count = 0
                await asyncio.sleep(3)

async def main():
    if args.scan:
        await scan()
    tasks = []
    lock = asyncio.Lock()
    for index, sensor in enumerate(args.sensors):
        sensor_info = sensor.strip().split(",")
        if len(sensor_info) == 1:
            address = sensor_info[0]
            name = "".join(address.split(":")[-2:])
            mask = 0xff
        elif len(sensor_info) == 2:
            name, address = sensor_info
            mask = 0xff
        elif len(sensor_info) == 3:
            name, address, mask = sensor_info
            mask = int(mask,16)
        else:
            eprint(f"Invalid sensor format {sensor}")
            exit(1)
        tasks.append(asyncio.create_task(blitz_access(name, address, lock=lock, latency=index*20, mask=mask)))
    if tasks:
        tasks.append(asyncio.create_task(watch_dog.loop()))
        await asyncio.wait(tasks)
    else:
        eprint("No sensor specified")
        exit(1)

if __name__ == "__main__":
    asyncio.run(main())
