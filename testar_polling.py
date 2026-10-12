#!/usr/bin/env python3
"""Mede o polling rate real do mouse lendo os eventos do kernel.

Uso: sudo python3 testar_polling.py [/dev/input/eventN]
Mexa o mouse rápido e sem parar, em círculos. Ctrl+C para sair.
"""
import os, struct, sys

dev = sys.argv[1] if len(sys.argv) > 1 else "/dev/input/event7"
EV = struct.Struct("llHHi")  # timeval (sec, usec), type, code, value
fd = os.open(dev, os.O_RDONLY)
print(f"lendo {dev}: mexa o mouse continuamente")

last = None
gaps = []
try:
    while True:
        sec, usec, typ, code, val = EV.unpack(os.read(fd, EV.size))
        if typ != 0:  # só EV_SYN marca o fim de cada relatório
            continue
        t = sec + usec / 1e6
        if last is not None:
            gap = t - last
            if gap < 0.02:  # ignora pausas do movimento
                gaps.append(gap)
        last = t
        if len(gaps) >= 500:
            gaps.sort()
            med = gaps[len(gaps) // 2]
            print(f"mediana {1 / med:7.0f} Hz | melhor {1 / gaps[len(gaps) // 20]:7.0f} Hz")
            gaps.clear()
except KeyboardInterrupt:
    pass
