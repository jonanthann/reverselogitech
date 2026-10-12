Versão traduzida para português: [README.pt-BR.md](README.pt-BR.md)

# Reverse engineering the Logitech PRO X 2 Superlight HID++ protocol: onboard polling rate and DPI on Linux

This project reverse engineers the HID++ protocol of the Logitech PRO X 2 Superlight (wireless, Lightspeed USB receiver `046d:c54d`) so you can use its onboard memory (onboard profiles) on Linux, specifically Debian. The tools change the polling rate and DPI without turning off the onboard profiles. Everything talks HID++ 2.0 directly to the receiver's hidraw device.

The receiver's `/dev/hidraw` node is usually root-only. To open it up for your user, install the udev rule from the repository:

```
sudo cp udev/60-prox2.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
```

Then unplug and replug the receiver. If you copied the old `70-prox2-hidraw.rules` to `/etc/udev/rules.d/`, delete it. As a temporary alternative, `sudo chmod a+rw /dev/hidraw6` (the number varies) or running the commands with sudo.

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
| `tests/dados/prox2_backup_perfis.json` | Example fixture: backup of sectors 0..5 from before any change (factory/G Hub original). Your own backup lives in `~/.local/share/myproX2/`. |
| `myprox2.py`, `app/` | The myproX2 GNOME app. |
| `caminhos.py` | Data and config folders (XDG). |
| `debian/` | Packaging of the `.deb`. |
| `LICENSE` | MIT license. |
| `testar_polling_raw.py` | Counts raw packets from the receiver for 10 s. With hidraw access opened, it runs without sudo. This is the best way to measure. |
| `testar_polling.py` | Measures through evdev. Needs sudo. |
| `testar_host_mode.py` | Diagnostic: tests the rate in host mode. |
| `painel_web.py` | The panel's server. |
| `painel_core.py` | The panel's write rules. |
| `acoes.py` | Button actions (4 bytes) and macros. |
| `perfil.py` | Reads and builds the profile sectors. |
| `painel/index.html` | The panel's page. |
| `udev/60-prox2.rules` | udev rule that opens the receiver's hidraw to your user. |
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
- `dpi N` writes the DPI (X and Y equal). By default it applies to all active profiles. With `--perfil N` (one or more sectors, 1 to 5), only to those profiles. It only accepts profiles with a single DPI level (use the panel for several levels). Values outside the sensor's ranges are rejected, with a suggestion of the closest ones.
- `backup` saves sectors 0..15 (profiles and macros) to a JSON file.
- `restaurar` (restore) writes the profiles from a JSON file back to the mouse. The `--sim` (yes) option is optional. Sectors with an invalid CRC in the file are skipped with a warning, and the rest are restored.

On the first write, `prox2.py` creates the automatic backup `prox2_backup_perfis.json` in the data folder (see "Where data is kept"). If the file already exists, it is not overwritten.

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

DPI: 1 to 5 levels, from 100 to 44000. Mark which level is the default (the one the mouse uses at power on) and which is the shift level (the one used by the "DPI shift" action).

Buttons: the 5 buttons (left, right, middle, back, forward) can be remapped on the normal layer and on the G-Shift layer (which only matters with a button set to G-Shift). Each button accepts click, key (with modifiers), media, special, macro or off. Some button on the normal layer must keep the left click. Special actions tested on the mouse: cycle DPI and DPI shift. The others (next/previous DPI, default DPI, next/previous/cycle profile, G-Shift) come from libratbag and are untested.

Macros: they live in sectors 6..15, are listed in their own section (create, edit, delete), and each step is key down, key up or wait (ms). Every key pressed must be released by the end. Steps can be generated from text (letters, digits, space, Enter and Tab). You cannot delete a macro that a button uses.

Limits: you cannot turn off the slot in use or the last active one.

Safety: before the first write, the original backup is saved to `~/.local/share/myproX2/prox2_backup_perfis.json`. If the old backup only has sectors 0..5, macro sectors 6..15 go once to `~/.local/share/myproX2/painel_dados/backup_macros.json`. A copy of each previous sector goes to `~/.local/share/myproX2/painel_dados/historico/`.

The panel interface is in Portuguese, like the rest of the program.

## Where data is kept

Writable data lives in `~/.local/share/myproX2/` (or `$XDG_DATA_HOME/myproX2`): the backup `prox2_backup_perfis.json` and the `painel_dados/` folder. On the first run from the repository, the old ones from the repository root are copied there (the originals stay in place). This copy does not happen when the code is installed from the `.deb`.

## myproX2 app (GNOME)

A native GNOME app (GTK 4 and libadwaita) built on the same code as `prox2.py`. It needs `python3-gi`, `gir1.2-gtk-4.0` and `gir1.2-adw-1`. For the tray icon on GNOME, install `gnome-shell-extension-appindicator`.

- Shows the mouse battery, with an icon in the top bar (tray) and notifications.
- Window with the slots (profiles) and DPI.
- "Botões" tab: the 5 buttons on 2 layers, normal and G-Shift.
- "Macros" tab.
- "Iniciar com a sessão" (start with the session) in the menu.

```
python3 myprox2.py
python3 myprox2.py --background
python3 myprox2.py --falso
python3 myprox2.py instalar-local
python3 myprox2.py desinstalar-local
```

- Without options, it opens the window.
- `--background` starts without a window, only the tray icon.
- `--falso` uses a simulated mouse in memory. It does not touch the real mouse, so it is safe for trying the interface.
- `--simular-bateria N` and `--simular-carga` simulate the battery level and charging.
- `instalar-local` adds the app to the menu for your user (`.desktop` and icon) pointing at this repository. `desinstalar-local` removes them. `instalar-local` refuses to run when the app came from the `.deb`.

## `.deb` package

The `debian/` folder builds the `prox2` package, which installs the commands `prox2` and `myprox2`, the udev rule and the menu entry.

Build dependencies:

```
sudo apt install build-essential debhelper dh-python lintian
```

Build (the `.deb` is created in the parent folder):

```
dpkg-buildpackage -us -uc -b
```

Before installing, run `python3 myprox2.py desinstalar-local` and delete the old manual udev rule (`/etc/udev/rules.d/70-prox2-hidraw.rules`). Then:

```
sudo apt install ./prox2_0.1.0_all.deb
```

Runtime dependencies: `python3`, `python3-gi`, `gir1.2-gtk-4.0` and `gir1.2-adw-1` (recommended: `gnome-shell-extension-appindicator`). To remove: `sudo apt purge prox2`. Your data in `~/.local/share/myproX2/` stays.

## myproX2 user guide

A step-by-step guide to using the app day to day. Installation is in "`.deb` package" and the data format in "What was found". The app interface is in Portuguese, so the names in quotes below are the labels you will see on screen.

### Getting started

1. Install the `.deb` (see "`.deb` package") and replug the receiver so the udev rule takes effect.
2. Turn the mouse on and open **myproX2** from the applications menu. Or run `myprox2` in a terminal.
3. To see the icon in the GNOME top bar, install `gnome-shell-extension-appindicator` and enable the extension. Without it the app works, just without the icon.

Closing the window does not quit the app: it keeps running in the top bar, reading the battery. To open it again, click the icon or use "Abrir myproX2" in its menu. To quit for good, see "Closing the app".

### Tray icon and battery

The icon shows the mouse charge. Hover over it to see the percentage and the state (discharging, charging, fully charged). If the mouse is disconnected, the text shows the time of the last reading. The icon menu has the battery line, "Abrir myproX2" (open) and "Sair" (quit).

The app sends a notification when:

- the battery drops below 20% ("Bateria baixa");
- it drops below 10% ("Bateria crítica", high urgency);
- the mouse finishes charging ("Bateria carregada").

Each warning appears once per discharge. When you plug the mouse in to charge, the low-battery warnings are reset.

### Vagas tab: DPI and profile

The window has three tabs at the bottom: Vagas (slots), Botões (buttons) and Macros. The top shows the battery and the state (Conectado or Desconectado). With the mouse disconnected, the window does not allow editing.

1. On the **Vagas** tab, click the card of the slot (profile) you want to edit. Each card shows the name, the DPI levels, the rate in Hz and whether the slot is in use, active or off.
2. Under "Níveis de DPI", change the value of each level (100 to 44000). "Adicionar nível" adds one more (up to 5) and "Remover" removes a level. Check **Padrão** on the level the mouse uses at power on, and **Shift** on the one used by the "DPI shift" action.
3. Set the polling rate, the LOD and the name (up to 24 characters, stored on the mouse). The "Vaga ativa" switch turns the slot on or off.
4. Click **Gravar no mouse**. When it works, you see "Gravado e verificado" (written and verified): the app writes the sector and reads it back to check.

The other slot buttons:

- **Usar agora** switches the profile in use. The choice stays after the mouse is turned off. A slot that is off cannot be used.
- **Restaurar** asks first, then puts the slot back to the factory default (there is a backup to undo it).

If you changed something and try to select another slot or use one, the app asks "Descartar alterações?". Choose "Descartar" to give up the changes or "Cancelar" to go back and write them. If the mouse reconnects with pending changes, they are discarded, with a notice.

You cannot turn off the slot in use or the last active one.

### Botões tab

Shows the 5 buttons (left, right, middle, back and forward) of the selected slot, in two layers: **Camada normal** and **G-Shift**. G-Shift only matters when some button is set to the special action "G-Shift".

For each button, pick the type:

- **Clique** (click): left, right, middle, back or forward.
- **Tecla** (key): click the field, press the key you want (it shows "Pressione...") and check the modifiers if needed. Keys the mouse does not support show "Tecla não suportada".
- **Mídia** (media): play/pause, next track, previous track, volume up and down, mute.
- **Especial** (special): next DPI, previous DPI, cycle DPI, default DPI, DPI shift, next profile, previous profile, cycle profile and G-Shift. Only "Ciclar DPI" and "DPI shift" were tested on the mouse; the others show "(não testado)".
- **Macro**: pick a ready macro or create one with "Nova macro...".
- **Desligado** (off): the button does nothing.

The normal layer must keep at least one button with the left click. If it does not, the app refuses to write and says so. After changing buttons, click **Gravar no mouse** on this tab.

### Macros tab

Lists the mouse's macros (up to 10), with the state (Vazia, Pronta or Inválida) and which buttons use each one.

1. Click **Nova macro**, or **Editar** on an existing one.
2. In **Passos** (steps) mode, add "aperta" (key down), "solta" (key up) or "espera" (wait, in ms) and choose the key for each step. You can move steps up and down and remove them. Every key pressed must be released by the end.
3. In **Texto** (text) mode, type the text and the wait between keys. Only letters, digits and space, no accents.
4. Click **Salvar macro**. You see "Gravado e verificado". Then assign the macro to a button on the Botões tab.
5. **Apagar** (delete) empties the sector, after asking for confirmation. It stays blocked while any button uses the macro: change that button's action and write it first.

### Start with the session

In the window menu (the icon at the corner), check **Iniciar com a sessão**. The app then opens by itself at login, without a window, only the tray icon. Uncheck it to turn this off.

### Backup and restore

On the first write, the app saves the mouse's original state to `~/.local/share/myproX2/prox2_backup_perfis.json`. That file is not overwritten. A copy of each replaced sector goes to `~/.local/share/myproX2/painel_dados/historico/`.

To go back to the original, with the app closed:

```
prox2 restaurar ~/.local/share/myproX2/prox2_backup_perfis.json
```

To save the current state: `prox2 backup my_backup.json`. See "Restoring the original" for details.

### Try it without touching the mouse

```
myprox2 --falso
```

Opens the app with a simulated mouse in memory (battery at 80%). Nothing is written to the real mouse, and the data disappears when you close it. It is good for getting to know the interface. With `--simular-bateria N` and `--simular-carga` you can see the battery notifications.

### Troubleshooting

**Mouse not found or no permission.** The window shows "Desconectado" or "Mouse desconectado". Check that the mouse is on and the receiver is in the USB port. If it is a permission problem, install the udev rule (the `.deb` already includes it) and replug the receiver. See the top of this README.

**"Outro programa (CLI, painel ou app) está gravando no mouse".** Only one program writes at a time, using a lock at `$XDG_RUNTIME_DIR/myprox2.lock`. Wait a few seconds and try again. If it persists, close the web panel or the `prox2` command that is running. Programs that grab the mouse exclusively (like OpenLogi) also get in the way.

**The icon does not show in the top bar.** Install and enable `gnome-shell-extension-appindicator`, then log out and back in. The app works without the icon, but then you can only open it from the applications menu.

**Closing the app.** Closing the window only hides it. To quit:

- "Sair" in the window menu or in the icon menu;
- `Ctrl+C` in the terminal where it was started;
- `pkill -f myprox2`, if nothing else works.

The app ignores `Ctrl+Z`: it does not get suspended, so it cannot hold the mouse while unable to be closed. If an older version got stuck because of `Ctrl+Z`, find the PID with `pgrep -f myprox2` and run `kill -CONT <pid>; kill <pid>`.

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

Each profile takes sectors 1..5, with 255 bytes. Macros live in sectors 6..15. The last 2 bytes are the CRC-CCITT (init `0xFFFF`, poly `0x1021`, big-endian).

| Byte | Content |
|---|---|
| 0 | Rate the mouse actually uses |
| 1 | Rate the mouse reports (`getReportRate` of feature 0x8061) |
| 2 | Default DPI level (index 0 to 4) |
| 3 | Shift DPI level (index 0 to 4) |
| 4 onward | DPI: 5 entries of 5 bytes |
| 48 to 67 | Actions of the 5 buttons on the normal layer, 4 bytes each (48+4i) |
| 112 to 131 | Actions of the 5 buttons on the G-Shift layer (112+4i) |
| 160 to 207 | Profile name, UTF-16LE (`ff` = no name) |
| 253 and 254 | CRC |

Each DPI entry has X (2 bytes, little-endian), Y (2 bytes, little-endian) and 1 byte with the LOD (lift-off distance). The LOD of entry k is at byte 8+5k: 1 is low, 2 is medium, 3 is high. This was confirmed on the sensor and in a physical test.

Button action format (4 bytes):

| Bytes | Action |
|---|---|
| `80 01 00 <mask>` | Click: 01 left, 02 right, 04 middle, 08 back, 10 forward |
| `80 02 <mod> <key>` | HID key with modifiers |
| `80 03 <hi> <lo>` | Media (16-bit code) |
| `90 <code> 00 00` | Special: 03 next DPI, 04 previous DPI, 05 cycle DPI, 06 default DPI, 07 shift DPI, 08 next profile, 09 previous profile, 0a cycle profile, 0b G-Shift |
| `00 <sector> 00 <offset>` | Macro in sector 6..15, from the offset |
| `ff ff ff ff` | Off |

Only 05 and 07 were tested. The other codes come from libratbag.

### Macros

Each macro lives in a sector from 6 to 15, with 253 usable bytes and the CRC in the last 2. Items are 3 bytes: `43 <mod> <key>` key down, `44 <mod> <key>` key up, `40 <ms hi> <ms lo>` wait (milliseconds, big-endian) and `ff` marks the end. Items can cross 16-byte blocks (tested). A macro sector requires a CRC: writing without one gives HID++ error 0x4. An empty macro sector is all `ff` with a CRC.

When the mouse changes DPI level, it announces it with the HID++ event `11 01 0d 10 <level>`.

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

Solaar assumes the older profile layout: DPI in 2 bytes starting at byte 3 and polling only in byte 0. libratbag does not support profile format 7 either. In the PRO X 2's format 7, DPI is 5 entries of 5 bytes starting at byte 4, and the rate is in bytes 0 and 1. Solaar reads the wrong bytes and cannot change the rate while onboard memory is active.

## Restoring the original

`~/.local/share/myproX2/prox2_backup_perfis.json` holds the sectors from before any change, that is, the factory/G Hub original. New backups (`prox2.py backup`) cover sectors 0..15, macros included. On restore, empty macros go back as `ff` with a CRC, and macros with a bad CRC in the file are skipped, with a warning that they were not restored (use "Restaurar" in the panel to put those slots back to the default). To go back to the original:

```
python3 prox2.py restaurar ~/.local/share/myproX2/prox2_backup_perfis.json [--sim]
```

## How it was made

The reverse engineering was done with the help of [Claude Code](https://claude.com/claude-code). It read and compared the onboard memory sectors, queried the mouse's HID++ features, and wrote and reviewed the scripts. Every write was checked on the real mouse by reading the sector back and measuring the packet rate.

## License

MIT, see [LICENSE](LICENSE).

## Legal notice

This is an independent project, with no affiliation with, support from or endorsement by Logitech. Logitech, PRO X 2 Superlight, Lightspeed and G HUB are trademarks of Logitech. All rights to them, to the hardware and to the firmware belong to Logitech.

Use at your own risk. The tools write to the mouse's memory. If you need to go back, use the backup and restore commands of `prox2.py`.
