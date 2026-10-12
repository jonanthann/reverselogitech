"""Teclas: código evdev (keycode X11 menos 8) -> HID usage e nomes para a tela. Funções puras, sem GTK."""

# evdev -> HID usage (posição física da tecla, como KeyboardEvent.code no painel web)
_EVDEV_HID = {}
for _i in range(26):
    _EVDEV_HID[[30, 48, 46, 32, 18, 33, 34, 35, 23, 36, 37, 38, 50, 49, 24, 25, 16, 19, 31, 20, 22, 47, 17, 45, 21, 44][_i]] = 4 + _i
for _i in range(1, 10):
    _EVDEV_HID[1 + _i] = 29 + _i
_EVDEV_HID[11] = 39
for _i in range(1, 11):
    _EVDEV_HID[58 + _i] = 57 + _i
_EVDEV_HID[87], _EVDEV_HID[88] = 68, 69
for _i in range(13, 25):
    _EVDEV_HID[170 + _i] = 91 + _i
_EVDEV_HID.update({28: 40, 1: 41, 14: 42, 15: 43, 57: 44, 12: 45, 13: 46, 26: 47, 27: 48, 43: 49, 39: 51,
                   40: 52, 41: 53, 51: 54, 52: 55, 53: 56, 110: 73, 102: 74, 104: 75, 111: 76, 107: 77,
                   109: 78, 106: 79, 105: 80, 108: 81, 103: 82})

# modificadores evdev -> bit do byte de modificadores (Ctrl 1, Shift 2, Alt 4, Super 8)
_EVDEV_MOD = {29: 1, 97: 1, 42: 2, 54: 2, 56: 4, 100: 4, 125: 8, 126: 8}
MODS = ((1, "Ctrl"), (2, "Shift"), (4, "Alt"), (8, "Super"))

_NOMES = {44: "Espaço", 40: "Enter", 41: "Esc", 42: "Backspace", 43: "Tab", 73: "Insert", 74: "Home",
          75: "Page Up", 76: "Delete", 77: "End", 78: "Page Down", 79: "Seta direita", 80: "Seta esquerda",
          81: "Seta baixo", 82: "Seta cima", 45: "-", 46: "=", 47: "[", 48: "]", 49: "\\", 51: ";", 52: "'",
          53: "`", 54: ",", 55: ".", 56: "/"}
for _i in range(26):
    _NOMES[4 + _i] = chr(65 + _i)
for _i in range(1, 10):
    _NOMES[29 + _i] = str(_i)
_NOMES[39] = "0"
for _i in range(1, 13):
    _NOMES[57 + _i] = f"F{_i}"
for _i in range(13, 25):
    _NOMES[91 + _i] = f"F{_i}"


def evdev_para_hid(codigo):
    """HID usage da tecla evdev, ou None se não for suportada."""
    return _EVDEV_HID.get(codigo)


def mod_de_evdev(codigo):
    """Bit de modificador da tecla evdev (0 se não for modificador)."""
    return _EVDEV_MOD.get(codigo, 0)


def nome_tecla(uso):
    return _NOMES.get(uso) or f"HID {uso}"


def nome_mod(mod):
    return "+".join(n for bit, n in MODS if mod & bit)


def rotulo_tecla(mod, uso):
    return (nome_mod(mod) + "+" if mod else "") + nome_tecla(uso)
