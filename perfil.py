"""Leitura e montagem de setores de perfil onboard (funções puras, sem tocar no mouse)."""
import acoes
from prox2 import RATES, com_crc, crc_ok, dpi_valido, dpis_proximos

ROM_FABRICA = 0x0101
LODS = {1: "baixo", 2: "médio", 3: "alto"}
NOME_INI, NOME_FIM, NOME_MAX = 160, 208, 24
ENTRADAS = 5  # entradas de DPI de 5 bytes a partir do byte 4 (X, Y, LOD)
BOTOES_N = 5  # esquerdo, direito, meio, voltar, avancar
CAMADA_NORMAL, CAMADA_GSHIFT = 48, 112  # início das 5 ações de 4 bytes de cada camada


def _preenchidas(setor):
    r = []
    for k in range(ENTRADAS):
        o = 4 + 5 * k
        x = setor[o] | setor[o + 1] << 8
        if x not in (0, 0xFFFF):
            r.append(k)
    return r


def _acoes(setor, ini):
    return [acoes.decodificar_acao(setor[ini + 4 * i:ini + 4 * i + 4]) for i in range(BOTOES_N)]


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
        "niveis": [setor[4 + 5 * k] | setor[5 + 5 * k] << 8 for k in pre],
        "dpi_padrao": setor[2],
        "dpi_shift": setor[3],
        "botoes": _acoes(setor, CAMADA_NORMAL),
        "gshift": _acoes(setor, CAMADA_GSHIFT),
        "lod": setor[8],
        "um_nivel": len(pre) <= 1,
        "nome": nome,
    }


def _camada(lista, nome, normal):
    if not isinstance(lista, list) or len(lista) != BOTOES_N:
        raise ValueError(f"{nome} precisa ter {BOTOES_N} ações")
    cods = [acoes.codificar_acao(d) for d in lista]
    if normal and acoes.codificar_acao({"tipo": "clique", "botao": "esquerdo"}) not in cods:
        raise ValueError("Algum botão precisa continuar com o clique esquerdo, senão o mouse fica inutilizável")
    return b"".join(cods)


def montar_vaga(setor, *, niveis=None, dpi_padrao=None, dpi_shift=None, polling_hz=None, lod=None,
                nome=None, botoes=None, gshift=None):
    b = bytearray(setor)
    pre = _preenchidas(setor)
    if niveis is not None:
        if (not isinstance(niveis, list) or not 1 <= len(niveis) <= ENTRADAS
                or any(not isinstance(n, int) or isinstance(n, bool) for n in niveis)):
            raise ValueError(f"Informe de 1 a {ENTRADAS} níveis de DPI")
        for dpi in niveis:
            if not dpi_valido(dpi):
                raise ValueError(f"DPI {dpi} inválido. Valores próximos válidos: "
                                 + ", ".join(str(n) for n in dpis_proximos(dpi)))
    n_final = len(niveis) if niveis is not None else len(pre)
    for campo, v in (("padrão", dpi_padrao), ("de shift", dpi_shift)):
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 0 <= v < n_final):
            raise ValueError(f"Nível {campo} inválido: use de 0 a {n_final - 1}")
    if polling_hz is not None and polling_hz not in RATES:
        raise ValueError(f"Polling {polling_hz} Hz inválido. Use um destes: {', '.join(map(str, RATES))}")
    if lod is not None and lod not in LODS:
        raise ValueError(f"LOD {lod} inválido. Use 1 (baixo), 2 (médio) ou 3 (alto)")
    cam_normal = _camada(botoes, "botoes", True) if botoes is not None else None
    cam_gshift = _camada(gshift, "gshift", False) if gshift is not None else None
    raw_nome = nome.encode("utf-16-le") if nome else b""
    if nome is not None and (len(nome) > NOME_MAX or len(raw_nome) > NOME_FIM - NOME_INI):
        raise ValueError(f"Nome longo demais. O máximo é {NOME_MAX} caracteres ({NOME_FIM - NOME_INI} bytes em UTF-16)")
    if niveis is not None:
        atual = [(setor[4 + 5 * k:8 + 5 * k], setor[8 + 5 * k]) for k in pre]
        if [x[0] for x in atual] != [n.to_bytes(2, "little") * 2 for n in niveis]:
            if pre != list(range(len(pre))) or any(x[0][:2] != x[0][2:] for x in atual):
                raise ValueError("Esta vaga tem níveis de DPI com X diferente de Y ou entradas vazias no meio, "
                                 "o painel não edita esses níveis sem perder dados. Restaure a vaga antes.")
            lod0 = atual[0][1] if atual and atual[0][1] in LODS else 2
            b[4:4 + 5 * ENTRADAS] = bytes(5 * ENTRADAS)
            for k, n in enumerate(niveis):
                l = atual[k][1] if k < len(atual) and atual[k][1] in LODS else lod0
                b[4 + 5 * k:9 + 5 * k] = n.to_bytes(2, "little") * 2 + bytes([l])
        if n_final != len(pre):
            if dpi_padrao is None:
                b[2] = min(b[2], n_final - 1)
            if dpi_shift is None:
                b[3] = min(b[3], n_final - 1)
    if dpi_padrao is not None:
        b[2] = dpi_padrao
    if dpi_shift is not None:
        b[3] = dpi_shift
    if cam_normal is not None:
        b[CAMADA_NORMAL:CAMADA_NORMAL + 4 * BOTOES_N] = cam_normal
    if cam_gshift is not None:
        b[CAMADA_GSHIFT:CAMADA_GSHIFT + 4 * BOTOES_N] = cam_gshift
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
