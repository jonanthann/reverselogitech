#!/usr/bin/env python3
"""Conta os pacotes crus que o receptor Lightspeed manda, por interface e por report ID.

Uso: python3 testar_polling_raw.py
Mexa o mouse rápido e sem parar durante os 10 segundos.
"""
import os, select, time
from collections import Counter

fds = {}
for n in sorted(os.listdir("/sys/class/hidraw")):
    if "046D:0000C54D" in open(f"/sys/class/hidraw/{n}/device/uevent").read().upper():
        fds[os.open(f"/dev/{n}", os.O_RDONLY | os.O_NONBLOCK)] = n

print("mexa o mouse agora, medindo por 10 s...")
count = Counter()
first = {}
last = {}
end = time.monotonic() + 10
while time.monotonic() < end:
    r, _, _ = select.select(list(fds), [], [], 0.1)
    for fd in r:
        try:
            d = os.read(fd, 64)
        except BlockingIOError:
            continue
        k = (fds[fd], d[0], len(d))
        t = time.monotonic()
        count[k] += 1
        first.setdefault(k, t)
        last[k] = t

for k, c in count.most_common():
    dur = last[k] - first[k]
    hz = c / dur if dur > 0 else 0
    print(f"{k[0]} report_id={k[1]:#04x} tamanho={k[2]:2d}: {c:6d} pacotes ~{hz:6.0f} por segundo")
