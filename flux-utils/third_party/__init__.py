from .humidity import rel_to_dpt
import time
import asyncio

def cel_to_kel(T):
    return T + 273.15

def kel_to_cel(T):
    return T - 273.15

# T in C, P in hPa, RH in %
def dew_point(T, P, RH):
    return kel_to_cel(rel_to_dpt(cel_to_kel(T), P * 100, RH))

def normalize_pressure(P, altitude):
    g0 = 9.80665
    R = 8.3144598
    M = 0.0289644
    Tb = 288.15
    Lb = 0.0065
    P0 = 101325.00
    P1 = P0 * ((Tb - altitude * Lb) / Tb) ** (g0 * M / R / Lb)
    return P - P1 / 100

class WatchDog:
    def __init__(self, timeout=60, print_func=print):
        self.timeout = timeout
        self.ts = time.time()
        self.enable = False
        self.eprint = print_func

    def on(self):
        self.touch()
        self.enable = True

    def off(self):
        self.enable = False

    def touch(self):
        self.ts = time.time()

    async def loop(self):
        while True:
            if not self.enable:
                await asyncio.sleep(self.timeout / 2)
                continue
            time_expire = time.time() - self.ts
            if time_expire >= self.timeout:
                self.eprint(f"Watch dog timed out for {time_expire}s")
                exit(-1)
            else:
                await asyncio.sleep(self.timeout - time_expire)
