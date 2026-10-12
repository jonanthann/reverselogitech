"""Ações de botão (4 bytes) e macros (setores 6..15). Funções puras, sem tocar no mouse."""
from prox2 import com_crc, crc_ok

BOTOES_CLIQUE = {0x01: "esquerdo", 0x02: "direito", 0x04: "meio", 0x08: "voltar", 0x10: "avancar"}
ESPECIAIS = {0x03: "proximo_dpi", 0x04: "dpi_anterior", 0x05: "ciclo_dpi", 0x06: "dpi_padrao",
             0x07: "shift_dpi", 0x08: "proximo_perfil", 0x09: "perfil_anterior", 0x0A: "ciclo_perfil",
             0x0B: "gshift"}
ESPECIAIS_TESTADOS = ("ciclo_dpi", "shift_dpi")
SEC_MACRO_MIN, SEC_MACRO_MAX = 6, 15
DADOS_MACRO = 253  # bytes úteis do setor de macro (os 2 últimos são o CRC)
TAM_SETOR = 255
DESLIGADO = b"\xff\xff\xff\xff"


def decodificar_acao(b4):
    b = bytes(b4)
    if len(b) != 4:
        raise ValueError("Ação precisa ter 4 bytes")
    if b[0] == 0x80 and b[1] == 0x01 and b[2] == 0 and b[3] in BOTOES_CLIQUE:
        return {"tipo": "clique", "botao": BOTOES_CLIQUE[b[3]]}
    if b[0] == 0x80 and b[1] == 0x02 and 4 <= b[3] <= 231:
        return {"tipo": "tecla", "mod": b[2], "tecla": b[3]}
    if b[0] == 0x80 and b[1] == 0x03:
        return {"tipo": "midia", "codigo": b[2] << 8 | b[3]}
    if b[0] == 0x90 and b[1] in ESPECIAIS and b[2] == 0 and b[3] == 0:
        return {"tipo": "especial", "codigo": ESPECIAIS[b[1]]}
    if b == DESLIGADO:
        return {"tipo": "desligado"}
    if b[0] == 0 and SEC_MACRO_MIN <= b[1] <= SEC_MACRO_MAX and b[2] == 0 and b[3] <= DADOS_MACRO - 1:
        return {"tipo": "macro", "sec": b[1], "offset": b[3]}
    return {"tipo": "bruto", "hex": b.hex()}


def _inteiro(d, campo, lo, hi):
    v = d.get(campo)
    if not isinstance(v, int) or isinstance(v, bool) or not lo <= v <= hi:
        raise ValueError(f"Campo {campo} inválido: use um número de {lo} a {hi}")
    return v


def codificar_acao(d):
    if not isinstance(d, dict):
        raise ValueError("Ação inválida")
    t = d.get("tipo")
    if t == "clique":
        mascara = next((m for m, n in BOTOES_CLIQUE.items() if n == d.get("botao")), None)
        if mascara is None:
            raise ValueError("Botão de clique inválido. Use: " + ", ".join(BOTOES_CLIQUE.values()))
        return bytes([0x80, 0x01, 0x00, mascara])
    if t == "tecla":
        return bytes([0x80, 0x02, _inteiro(d, "mod", 0, 255), _inteiro(d, "tecla", 4, 231)])
    if t == "midia":
        c = _inteiro(d, "codigo", 0, 0xFFFF)
        return bytes([0x80, 0x03, c >> 8, c & 0xFF])
    if t == "especial":
        cod = next((c for c, n in ESPECIAIS.items() if n == d.get("codigo")), None)
        if cod is None:
            raise ValueError("Ação especial inválida. Use: " + ", ".join(ESPECIAIS.values()))
        return bytes([0x90, cod, 0, 0])
    if t == "desligado":
        return DESLIGADO
    if t == "macro":
        return bytes([0x00, _inteiro(d, "sec", SEC_MACRO_MIN, SEC_MACRO_MAX), 0x00,
                      _inteiro(d, "offset", 0, DADOS_MACRO - 1)])
    if t == "bruto":
        h = d.get("hex")
        try:
            b = bytes.fromhex(h) if isinstance(h, str) else b""
        except ValueError:
            b = b""
        if len(b) != 4:
            raise ValueError("Ação bruta precisa de 8 dígitos hexadecimais")
        return b
    raise ValueError("Tipo de ação inválido")


def ler_macro(setor, offset=0):
    """Devolve {"estado": "vazia"|"ok"|"invalida", "passos": [...]}."""
    dados = bytes(setor[:DADOS_MACRO])
    if dados == b"\xff" * DADOS_MACRO or not 0 <= offset < DADOS_MACRO or dados[offset] == 0xFF:
        return {"estado": "vazia", "passos": []}
    invalida = {"estado": "invalida", "passos": []}
    if len(setor) != TAM_SETOR or not crc_ok(setor):
        return invalida
    passos, i = [], offset
    while True:
        if i >= DADOS_MACRO:
            return invalida
        op = dados[i]
        if op == 0xFF:
            break
        if i + 3 > DADOS_MACRO:
            return invalida
        if op in (0x43, 0x44):
            passos.append({"tipo": "aperta" if op == 0x43 else "solta", "mod": dados[i + 1], "tecla": dados[i + 2]})
        elif op == 0x40:
            passos.append({"tipo": "espera", "ms": dados[i + 1] << 8 | dados[i + 2]})
        else:
            return invalida
        i += 3
    return {"estado": "ok", "passos": passos}


def montar_macro(passos):
    if not isinstance(passos, list) or not passos:
        raise ValueError("A macro precisa ter ao menos um passo")
    out, abertas = bytearray(), []
    for p in passos:
        if not isinstance(p, dict):
            raise ValueError("Passo inválido")
        t = p.get("tipo")
        if t in ("aperta", "solta"):
            mod, tecla = _inteiro(p, "mod", 0, 255), _inteiro(p, "tecla", 4, 231)
            out += bytes([0x43 if t == "aperta" else 0x44, mod, tecla])
            if t == "aperta":
                abertas.append((mod, tecla))
            elif (mod, tecla) in abertas:
                abertas.remove((mod, tecla))
        elif t == "espera":
            ms = _inteiro(p, "ms", 1, 65535)
            out += bytes([0x40, ms >> 8, ms & 0xFF])
        else:
            raise ValueError("Tipo de passo inválido. Use aperta, solta ou espera")
    if abertas:
        raise ValueError("Toda tecla apertada precisa ser solta no fim da macro")
    if len(out) + 1 > DADOS_MACRO:
        raise ValueError(f"Macro longa demais: cabem {(DADOS_MACRO - 1) // 3} passos")
    out.append(0xFF)
    out += b"\xff" * (TAM_SETOR - len(out))
    return com_crc(bytes(out))


def setor_macro_vazio():
    return com_crc(b"\xff" * TAM_SETOR)


def _hid(c):
    if "a" <= c <= "z":
        return 0, 4 + ord(c) - ord("a")
    if "A" <= c <= "Z":
        return 0x02, 4 + ord(c) - ord("A")
    if "1" <= c <= "9":
        return 0, 0x1E + ord(c) - ord("1")
    if c == "0":
        return 0, 0x27
    if c == " ":
        return 0, 0x2C
    if c == "\n":
        return 0, 0x28
    if c == "\t":
        return 0, 0x2B
    raise ValueError(f"Caractere {c!r} não suportado. Use letras, números, espaço, Enter e Tab")


def texto_para_passos(txt, espera_ms=30):
    if not isinstance(espera_ms, int) or isinstance(espera_ms, bool) or not 1 <= espera_ms <= 65535:
        raise ValueError("Espera inválida: use de 1 a 65535 ms")
    passos = []
    for c in txt:
        mod, tecla = _hid(c)
        if passos:
            passos.append({"tipo": "espera", "ms": espera_ms})
        passos += [{"tipo": "aperta", "mod": mod, "tecla": tecla},
                   {"tipo": "espera", "ms": espera_ms},
                   {"tipo": "solta", "mod": mod, "tecla": tecla}]
    return passos
