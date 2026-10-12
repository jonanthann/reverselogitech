#!/usr/bin/env python3
"""Diagnóstico: desliga a memória interna por alguns segundos, pede a taxa direto
ao mouse, mede os pacotes crus e depois religa a memória interna.

Uso: python3 testar_host_mode.py [indice]   (padrão 4 = 2000 Hz)
Índices: 0=125 1=250 2=500 3=1000 4=2000 5=4000 6=8000
"""
import os, select, sys, time

SWID = 0x0A
RATES = [125, 250, 500, 1000, 2000, 4000, 8000]
idx = int(sys.argv[1]) if len(sys.argv) > 1 else 4


def find_nodes():
    hidpp = mouse = None
    for n in sorted(os.listdir("/sys/class/hidraw")):
        p = f"/sys/class/hidraw/{n}/device"
        if "046D:0000C54D" not in open(f"{p}/uevent").read().upper():
            continue
        desc = open(f"{p}/report_descriptor", "rb").read()
        if desc.startswith(b"\x05\x01\x09\x02"):
            mouse = f"/dev/{n}"
        elif b"\x85\x11" in desc:
            hidpp = f"/dev/{n}"
    return hidpp, mouse


hidpp_path, mouse_path = find_nodes()
fd = os.open(hidpp_path, os.O_RDWR)


def req(fidx, func, params=b""):
    for _ in range(4):
        os.write(fd, (bytes([0x11, 1, fidx, (func << 4) | SWID]) + params).ljust(20, b"\0"))
        end = time.monotonic() + 1
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            d = os.read(fd, 64)
            if d[1] != 1:
                continue
            if d[2] == 0xFF and d[3] == fidx:
                raise IOError(f"erro HID++ {d[5]:#x}")
            if d[0] == 0x11 and d[2] == fidx and d[3] == ((func << 4) | SWID):
                return d[4:20]
    raise TimeoutError("mouse nao respondeu")


def feat(fid):
    return req(0, 0, fid.to_bytes(2, "big"))[0]


op, rr = feat(0x8100), feat(0x8061)


def measure(seconds=8):
    mfd = os.open(mouse_path, os.O_RDONLY | os.O_NONBLOCK)
    n, t0, t1 = 0, None, None
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        r, _, _ = select.select([mfd], [], [], 0.1)
        if r:
            try:
                os.read(mfd, 64)
            except BlockingIOError:
                continue
            t = time.monotonic()
            t0 = t0 or t
            t1 = t
            n += 1
    os.close(mfd)
    return n / (t1 - t0) if n > 1 else 0


try:
    req(op, 1, b"\x02")  # host mode
    time.sleep(0.3)
    req(rr, 3, bytes([idx]))
    time.sleep(0.3)
    print(f"host mode, pedido {RATES[idx]} Hz, mouse diz {RATES[req(rr, 2)[0]]} Hz")
    print("MEXA O MOUSE AGORA (8 s)...")
    print(f"medido: ~{measure():.0f} pacotes por segundo")
finally:
    req(op, 1, b"\x01")  # volta para a memória interna
    time.sleep(0.3)
    print(f"memoria interna religada, mouse diz {RATES[req(rr, 2)[0]]} Hz")
