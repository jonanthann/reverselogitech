"""Leitura e montagem de setores de perfil onboard (funções puras, sem tocar no mouse)."""
from prox2 import RATES, com_crc, crc_ok, dpi_valido, dpis_proximos

ROM_FABRICA = 0x0101
LODS = {1: "baixo", 2: "médio", 3: "alto"}
NOME_INI, NOME_FIM, NOME_MAX = 160, 208, 24
ENTRADAS = 5  # entradas de DPI de 5 bytes a partir do byte 4 (X, Y, LOD)


def _preenchidas(setor):
    r = []
    for k in range(ENTRADAS):
        o = 4 + 5 * k
        x = setor[o] | setor[o + 1] << 8
        if x not in (0, 0xFFFF):
            r.append(k)
    return r


def ler_vaga(setor):
    pre = _preenchidas(setor)
    bruto = setor[NOME_INI:NOME_FIM]
    if bruto == b"\xff" * len(bruto):
        nome = None
    else:
        fim = next((i for i in range(0, len(bruto) - 1, 2) if bruto[i:i + 2] == b"\x00\x00"), len(bruto))
        nome = bruto[:fim].decode("utf-16-le", errors="replace")
    return {
        "crc_ok": crc_ok(setor),
        "polling_hz": RATES[setor[0]] if setor[0] < len(RATES) else None,
        "polling_info_hz": RATES[setor[1]] if setor[1] < len(RATES) else None,
        "dpis": [setor[4 + 5 * k] | setor[5 + 5 * k] << 8 for k in pre],
        "lod": setor[8],
        "um_nivel": len(pre) <= 1,
        "nome": nome,
    }


def montar_vaga(setor, *, dpi, polling_hz, lod, nome=None, um_dpi_so=False):
    b = bytearray(setor)
    pre = _preenchidas(setor)
    if dpi is not None:
        if not dpi_valido(dpi):
            raise ValueError(f"DPI {dpi} inválido. Valores próximos válidos: "
                             + ", ".join(str(n) for n in dpis_proximos(dpi)))
        if len(pre) > 1 and not um_dpi_so:
            raise ValueError("Este perfil tem vários níveis de DPI. Confirme para manter só um nível.")
    if polling_hz is not None and polling_hz not in RATES:
        raise ValueError(f"Polling {polling_hz} Hz inválido. Use um destes: {', '.join(map(str, RATES))}")
    if lod is not None and lod not in LODS:
        raise ValueError(f"LOD {lod} inválido. Use 1 (baixo), 2 (médio) ou 3 (alto)")
    raw_nome = nome.encode("utf-16-le") if nome else b""
    if nome is not None and (len(nome) > NOME_MAX or len(raw_nome) > NOME_FIM - NOME_INI):
        raise ValueError(f"Nome longo demais. O máximo é {NOME_MAX} caracteres ({NOME_FIM - NOME_INI} bytes em UTF-16)")
    if dpi is not None:
        b[4:6] = b[6:8] = dpi.to_bytes(2, "little")
        if len(pre) > 1:
            b[9:4 + 5 * ENTRADAS] = bytes(4 + 5 * ENTRADAS - 9)
    if polling_hz is not None:
        b[0] = b[1] = RATES.index(polling_hz)
    if lod is not None:
        for k in _preenchidas(bytes(b)) or [0]:
            b[8 + 5 * k] = lod
    if nome is not None:
        if nome == "":
            b[NOME_INI:NOME_FIM] = b"\xff" * (NOME_FIM - NOME_INI)
        else:
            b[NOME_INI:NOME_FIM] = raw_nome + b"\x00" * (NOME_FIM - NOME_INI - len(raw_nome))
    if bytes(b) == setor:
        return setor
    assert len(b) == len(setor)
    return com_crc(bytes(b))


def diretorio_com_ativo(setor0, sec, ativo):
    b = bytearray(setor0)
    for o in range(0, len(b) - 3, 4):
        if b[o] == 0xFF and b[o + 1] == 0xFF:
            break
        if (b[o] << 8 | b[o + 1]) == sec:
            b[o + 2] = 1 if ativo else 0
            return com_crc(bytes(b))
    raise ValueError(f"Setor 0x{sec:04x} não está no diretório")
