"""Formulário da vaga -> argumentos de Painel.gravar (sem GTK).

O formulário é um dict: niveis (lista de DPI), padrao, shift (índices), polling_hz, lod, ativa, nome.
"""

MAX_NIVEIS = 5
DPI_MIN, DPI_MAX = 100, 44000
MAX_NOME = 24


def de_vaga(v):
    """Formulário inicial a partir de uma vaga de Painel.listar()."""
    return {"niveis": list(v["niveis"]), "padrao": v["dpi_padrao"], "shift": v["dpi_shift"],
            "polling_hz": v["polling_hz"], "lod": v["lod"] if v["lod"] in (1, 2, 3) else 2,
            "ativa": bool(v["ativa"]), "nome": v["nome_real"] or ""}


def remover_nivel(niveis, padrao, shift, i):
    """Remove o nível i e ajusta os índices Padrão e Shift (como no painel web)."""
    if len(niveis) <= 1:
        return list(niveis), padrao, shift
    novos = niveis[:i] + niveis[i + 1:]

    def ajusta(k):
        return 0 if k == i else k - 1 if k > i else k
    return novos, ajusta(padrao), ajusta(shift)


def adicionar_nivel(niveis):
    """Novo nível copia o último (ou 800). Não passa de 5."""
    if len(niveis) >= MAX_NIVEIS:
        return list(niveis)
    return list(niveis) + [niveis[-1] if niveis else 800]


def alterado(inicial, atual):
    return inicial != atual


def argumentos(inicial, atual):
    """Só o que mudou, nos nomes de Painel.gravar. Levanta ValueError em português se inválido."""
    r = {}
    if atual["niveis"] != inicial["niveis"] or atual["padrao"] != inicial["padrao"] or atual["shift"] != inicial["shift"]:
        n = atual["niveis"]
        if not 1 <= len(n) <= MAX_NIVEIS:
            raise ValueError("Use de 1 a 5 níveis de DPI.")
        if any(not isinstance(x, int) or not DPI_MIN <= x <= DPI_MAX for x in n):
            raise ValueError(f"Cada nível de DPI deve ficar entre {DPI_MIN} e {DPI_MAX}.")
        r.update(niveis=list(n), dpi_padrao=atual["padrao"], dpi_shift=atual["shift"])
    for k in ("polling_hz", "lod", "ativa"):
        if atual[k] != inicial[k]:
            r[k] = atual[k]
    if atual["nome"] != inicial["nome"]:
        if len(atual["nome"]) > MAX_NOME:
            raise ValueError(f"O nome pode ter no máximo {MAX_NOME} caracteres.")
        r["nome"] = atual["nome"]
    return r


NOMES_BOTOES = ("Esquerdo", "Direito", "Meio", "Trás", "Frente")


def limpa_acao(a):
    """Só os campos que o Painel aceita (como `limpa` no painel web)."""
    t = a["tipo"]
    o = {"tipo": t}
    if t == "clique":
        o["botao"] = a["botao"]
    elif t == "tecla":
        o["mod"], o["tecla"] = a["mod"], a["tecla"]
    elif t in ("midia", "especial"):
        o["codigo"] = a["codigo"]
    elif t == "macro":
        o["sec"], o["offset"] = a["sec"], a.get("offset", 0)
    elif t == "bruto":
        o["hex"] = a["hex"]
    return o


def argumentos_botoes(inicial, atual, macros):
    """Argumentos botoes/gshift de Painel.gravar; {} se nada mudou. inicial e atual: [normal, gshift]."""
    ini = [[limpa_acao(a) for a in c] for c in inicial]
    novo = [[limpa_acao(a) for a in c] for c in atual]
    if novo == ini:
        return {}
    prontas = {m["sec"] for m in macros if m["estado"] == "ok"}
    for cam in range(2):
        for k, a in enumerate(novo[cam]):
            if a["tipo"] == "macro" and a["sec"] not in prontas and a != ini[cam][k]:
                raise ValueError(f"O botão {NOMES_BOTOES[k]} usa uma macro que não está pronta.")
    if not any(a["tipo"] == "clique" and a["botao"] == "esquerdo" for a in novo[0]):
        raise ValueError("A camada normal precisa de um botão com clique esquerdo.")
    res = {}
    if novo[0] != ini[0]:
        res["botoes"] = novo[0]
    if novo[1] != ini[1]:
        res["gshift"] = novo[1]
    return res
