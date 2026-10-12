"""Decodificação da bateria (HID++ feature 0x1004, Unified Battery). Código puro, sem I/O."""

NIVEIS = ((8, "cheio"), (4, "bom"), (2, "baixo"), (1, "critico"))
ESTADOS = ("descarregando", "carregando", "carregando_devagar", "completa", "erro")
ENERGIA = ("nenhuma", "com_fio", "sem_fio")


def decodificar_caps(dados):
    """Resposta de getCapabilities: byte 0 = máscara de níveis, byte 1 = flags."""
    return {"niveis": dados[0], "soc": bool(dados[1] & 0x02), "recarregavel": bool(dados[1] & 0x01)}


def _nivel(v):
    for bit, nome in NIVEIS:
        if v & bit:
            return nome
    return "critico"


def decodificar_status(dados, caps=None):
    """dados = soc, nível, carga, energia externa (resposta de getStatus ou do evento)."""
    soc = dados[0] if caps is None or caps["soc"] else None
    carga = dados[2]
    estado = ESTADOS[carga] if carga < len(ESTADOS) else "erro"
    ext = dados[3]
    return {
        "soc": soc,
        "nivel": _nivel(dados[1]),
        "carregando": carga in (1, 2),
        "estado_carga": estado,
        "energia_externa": ENERGIA[ext] if ext < len(ENERGIA) else "nenhuma",
    }


def decodificar_evento(pacote, caps=None):
    """Pacote longo 11 idx fidx 00 <soc> <nivel> <carga> <ext>. Devolve None se não for evento de bateria."""
    if len(pacote) < 8 or pacote[0] != 0x11 or pacote[3] != 0x00:
        return None
    return decodificar_status(pacote[4:8], caps)


def nome_icone(info):
    if info is None:
        return "battery-missing-symbolic"
    if info["estado_carga"] == "completa":
        return "battery-level-100-charged-symbolic"
    if info["soc"] is not None:
        n = min(info["soc"], 100) // 10 * 10
    else:
        n = {"critico": 10, "baixo": 20, "bom": 60, "cheio": 100}[info["nivel"]]
    return f"battery-level-{n}" + ("-charging" if info["carregando"] else "") + "-symbolic"


class Alertas:
    """Decide quando avisar. Cada aviso sai uma vez por descarga."""

    def __init__(self, aviso=20, critico=10):
        self.aviso, self.critico = aviso, critico
        self._baixa = self._critica = self._carregada = False
        self._ext = False

    def _valor(self, info):
        if info["soc"] is not None:
            return info["soc"]
        return {"critico": self.critico - 1, "baixo": self.aviso - 1}.get(info["nivel"], 100)

    def atualizar(self, info):
        if info is None:
            return []
        out = []
        v = self._valor(info)
        if info["carregando"]:
            self._baixa = self._critica = False
        else:
            if v > self.aviso + 5:
                self._baixa = False
            if v > self.critico + 5:
                self._critica = False
            if v < self.critico and not self._critica:
                self._critica = self._baixa = True
                out.append("critica")
            elif v < self.aviso and not self._baixa:
                self._baixa = True
                out.append("baixa")
        completa = info["estado_carga"] == "completa" or (info["carregando"] and info["soc"] == 100)
        if completa and not self._carregada:
            self._carregada = True
            out.append("carregada")
        if info["energia_externa"] == "nenhuma":
            self._carregada = False
        return out
