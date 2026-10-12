Versão traduzida para português: [README.pt-BR.md](README.pt-BR.md)

# Reverse engineering the Logitech PRO X 2 Superlight HID++ protocol: onboard polling rate and DPI on Linux

This project reverse engineers the HID++ protocol of the Logitech PRO X 2 Superlight (wireless, Lightspeed USB receiver `046d:c54d`) so you can use its onboard memory (onboard profiles) on Linux, specifically Debian. The tools change the polling rate and DPI without turning off the onboard profiles. Everything talks HID++ 2.0 directly to the receiver's hidraw device.

The receiver's `/dev/hidraw` node is usually root-only. To open it up for your user, install the udev rule from the repository:

```
sudo cp udev/70-prox2-hidraw.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
```

Then unplug and replug the receiver. As a temporary alternative, `sudo chmod a+rw /dev/hidraw6` (the number varies) or running the commands with sudo.

Note: the program's interface (command names, options and output messages) is in Portuguese.

## The problem

With onboard memory active, there was no way to change the polling rate on Linux.

Solaar does not work with this mouse. It reads the profile with an older layout (DPI in 2 bytes starting at byte 3, polling only in byte 0), and the PRO X 2 uses profile format 7.

OpenLogi got in the way too. It grabbed the mouse exclusively and re-sent the events through a virtual mouse, so it was uninstalled (`sudo apt purge openlogi`). Tools like that make it impossible to measure the real rate on the mouse's event device.

## Result

Profiles 1 and 2 are set to 2000 Hz and 1600 DPI, stored in the onboard memory. The setting holds with no program running and on another PC.

## Files

| File | What it does |
|---|---|
| `prox2.py` | Main tool: status, change rate and DPI, backup and restore. With hidraw access opened, it runs without sudo. |
| `prox2_backup_perfis.json` | Backup of sectors 0..5 from before any change (factory/G Hub original). |
| `testar_polling_raw.py` | Counts raw packets from the receiver for 10 s. With hidraw access opened, it runs without sudo. This is the best way to measure. |
| `testar_polling.py` | Measures through evdev. Needs sudo. |
| `testar_host_mode.py` | Diagnostic: tests the rate in host mode. |
| `painel_web.py` | The panel's server. |
| `painel_core.py` | The panel's write rules. |
| `perfil.py` | Reads and builds the profile sectors. |
| `painel/index.html` | The panel's page. |
| `udev/70-prox2-hidraw.rules` | udev rule that opens the receiver's hidraw to your user. |
| `tests/` | Tests, run with `python3 -m unittest discover -s tests`. They do not use the mouse. |

## Quick usage

```
python3 prox2.py status
python3 prox2.py rate 2000
python3 prox2.py rate 2000 --perfil 1
python3 prox2.py rate 2000 --perfil 1 2
python3 prox2.py dpi 1600
python3 prox2.py dpi 1600 --perfil 1
python3 prox2.py backup arquivo.json
python3 prox2.py restaurar arquivo.json [--sim]
```

- `status` shows the current state of the profiles.
- `rate N` writes the rate in Hz. By default it applies to all active profiles. With `--perfil N` (one or more sectors, 1 to 5), only to those profiles.
- `dpi N` writes the DPI (X and Y equal). By default it applies to all active profiles. With `--perfil N` (one or more sectors, 1 to 5), only to those profiles. It only accepts profiles with a single DPI level, because the index of the active level has not been confirmed yet. Values outside the sensor's ranges are rejected, with a suggestion of the closest ones.
- `backup` saves the profiles to a JSON file.
- `restaurar` (restore) writes the profiles from a JSON file back to the mouse. The `--sim` (yes) option is optional. Sectors with an invalid CRC in the file are skipped with a warning, and the rest are restored.

On the first write, `prox2.py` creates the automatic backup `prox2_backup_perfis.json`. If the file already exists, it is not overwritten.

Rates above 2000 Hz use more battery. The firmware (MPM 32.05) supports 4000 and 8000 Hz, but those rates have not been tested.

## Local panel

```
python3 prox2.py painel
```

This opens your browser on a local page. The server listens only on 127.0.0.1, and the URL carries a key. Options: `--porta N` sets the port, and `--sem-navegador` does not open the browser and prints the URL instead. Closing the tab stops the server within 2 minutes, or you can press Ctrl+C. Once it is closed, the mouse keeps using what is stored in its memory, on any PC.

The page shows the 5 slots (profiles) of the onboard memory side by side. Click one to open the editor: DPI, polling rate, LOD (low, medium, high), name (up to 24 characters, stored on the mouse itself) and on/off for the slot ("Vaga ativa" checkbox). The buttons:

- "Gravar no mouse" (write to the mouse): writes and checks by reading back.
- "Usar agora" (use now): switches the profile in use. The choice stays after the mouse is turned off.
- "Restaurar" (restore): asks for confirmation ("Sim, restaurar" or "Cancelar"), then puts the slot back to the factory default, read from the mouse's ROM: 800 to 3200 DPI in 5 levels, 1000 Hz, medium LOD.
- "Usar um DPI só" (use a single DPI): appears on profiles with several DPI levels.

Limits: to edit the DPI of a profile with several levels you have to click "Usar um DPI só", because the index of the active level has not been confirmed yet. You cannot turn off the slot in use or the last active one. Buttons and macros are not supported.

Safety: before the first write, the original backup is saved to `prox2_backup_perfis.json`. A copy of each previous sector goes to `painel_dados/historico/`.

The panel interface is in Portuguese, like the rest of the program.

## How to measure

The best measurement is the raw packet count, which does not depend on any software in between:

```
python3 testar_polling_raw.py
```

It counts the receiver's packets for 10 seconds and, with hidraw access opened, does not need sudo.

To measure through evdev (needs sudo):

```
sudo python3 testar_polling.py [/dev/input/eventN]
```

The default is `/dev/input/event7`. Pass another path if your mouse is on a different event node.

For a good measurement, move the mouse fast and without stopping. Pauses pull the average down. Browser-based test sites can underestimate the rate.

Measurements with the profile at 2000 Hz: about 1975 packets/s in the raw count and a 1979 Hz maximum on an online test.

### Host mode diagnostic

```
python3 testar_host_mode.py [indice]
```

The script turns off the onboard memory for a few seconds, requests the rate directly from the mouse, measures it, and turns the onboard memory back on.

## What was found

HID++ features 0x8100 (onboard profiles) and 0x8061 (extended report rate).

### Profile layout

Each profile takes sectors 1..5, with 255 bytes. The last 2 bytes are the CRC-CCITT (init `0xFFFF`, poly `0x1021`, big-endian).

| Byte | Content |
|---|---|
| 0 | Rate the mouse actually uses |
| 1 | Rate the mouse reports (`getReportRate` of feature 0x8061) |
| 2 and 3 | Not confirmed yet |
| 4 onward | DPI: 5 entries of 5 bytes |
| 160 to 207 | Profile name, UTF-16LE (`ff` = no name) |
| 253 and 254 | CRC |

Each DPI entry has X (2 bytes, little-endian), Y (2 bytes, little-endian) and 1 byte with the LOD (lift-off distance). The LOD of entry k is at byte 8+5k: 1 is low, 2 is medium, 3 is high. This was confirmed on the sensor and in a physical test.

The rate values are indexes:

| Index | Rate |
|---|---|
| 0 | 125 Hz |
| 1 | 250 Hz |
| 2 | 500 Hz |
| 3 | 1000 Hz |
| 4 | 2000 Hz |
| 5 | 4000 Hz |
| 6 | 8000 Hz |

### The byte 0 and 1 trap

Writing only byte 1 makes the mouse report 2000 Hz, but it keeps transmitting at 1000 Hz. You have to write bytes 0 and 1 together.

This is how it was shown:

1. In host mode, the directly requested rate gave about 1870 packets/s, so the mouse was capable of 2000 Hz.
2. With bytes 0 and 1 written to the profile, the measurement gave about 1975 packets/s.

### Directory, factory profile and profile in use

- Sector 0 (the directory) has its own CRC. Byte 2 of each entry turns the slot on or off.
- The mouse refuses to use a slot that is turned off.
- The factory profile is in the ROM, sector `0x0101`. The ROM's CRC does not match, so it has to be recalculated.
- The choice of the profile in use persists after the mouse is turned off.

## Why Solaar fails

Solaar assumes the older profile layout: DPI in 2 bytes starting at byte 3 and polling only in byte 0. In the PRO X 2's format 7, DPI is 5 entries of 5 bytes starting at byte 4, and the rate is in bytes 0 and 1. Solaar reads the wrong bytes and cannot change the rate while onboard memory is active.

## Restoring the original

`prox2_backup_perfis.json` holds sectors 0..5 from before any change, that is, the factory/G Hub original. To go back to it:

```
python3 prox2.py restaurar prox2_backup_perfis.json [--sim]
```

## How it was made

The reverse engineering was done with the help of [Claude Code](https://claude.com/claude-code). It read and compared the onboard memory sectors, queried the mouse's HID++ features, and wrote and reviewed the scripts. Every write was checked on the real mouse by reading the sector back and measuring the packet rate.

## Legal notice

This is an independent project, with no affiliation with, support from or endorsement by Logitech. Logitech, PRO X 2 Superlight, Lightspeed and G HUB are trademarks of Logitech. All rights to them, to the hardware and to the firmware belong to Logitech.

Use at your own risk. The tools write to the mouse's memory. If you need to go back, use the backup and restore commands of `prox2.py`.
