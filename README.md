Versão traduzida para português: [README.pt-BR.md](README.pt-BR.md)

# Reverse engineering the Logitech PRO X 2 Superlight HID++ protocol: onboard polling rate and DPI on Linux

This project reverse engineers the HID++ protocol of the Logitech PRO X 2 Superlight (wireless, Lightspeed USB receiver `046d:c54d`) so you can use its onboard memory (onboard profiles) on Linux, specifically Debian. The tools change the polling rate and DPI without turning off the onboard profiles. Everything talks HID++ 2.0 directly to the receiver's hidraw device.

The receiver's `/dev/hidraw` node is usually root-only. Open it up (e.g. `sudo chmod a+rw /dev/hidraw6`, the number varies) or run the commands with sudo.

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

## Quick usage

```
python3 prox2.py status
python3 prox2.py rate 2000
python3 prox2.py rate 2000 --perfil 1
python3 prox2.py dpi 1600
python3 prox2.py dpi 1600 --perfil 1
python3 prox2.py backup arquivo.json
python3 prox2.py restaurar arquivo.json [--sim]
```

- `status` shows the current state of the profiles.
- `rate N` writes the rate in Hz. By default it applies to all active profiles. With `--perfil N`, only to that profile.
- `dpi N` writes the DPI (X and Y equal). By default it applies to all active profiles. With `--perfil N`, only to that profile. It only accepts profiles with a single DPI level, because the index of the active level has not been confirmed yet. Values outside the sensor's ranges are rejected, with a suggestion of the closest ones.
- `backup` saves the profiles to a JSON file.
- `restaurar` (restore) writes the profiles from a JSON file back to the mouse. The `--sim` (yes) option is optional.

On the first write, `prox2.py` creates the automatic backup `prox2_backup_perfis.json`. If the file already exists, it is not overwritten.

Rates above 2000 Hz use more battery. The firmware (MPM 32.05) supports 4000 and 8000 Hz, but those rates have not been tested.

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
| 253 and 254 | CRC |

Each DPI entry has X (2 bytes, little-endian), Y (2 bytes, little-endian) and 1 byte that is probably the lift-off distance.

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
