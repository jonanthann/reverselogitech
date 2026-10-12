"""Regras de negócio do Painel de perfis (sem HTTP, sem /dev/hidraw)."""
import datetime
import json
import os
import threading

import acoes
import perfil
from prox2 import BACKUP_PADRAO, com_crc, crc_ok


NOME_FABRICA = "PROFILE_NAME_DEFAULT"  # nome de fábrica, tratado como sem nome
NOMES_BOTOES = ("esquerdo", "direito", "meio", "voltar", "avancar")
CAMADAS = (("normal", perfil.CAMADA_NORMAL), ("gshift", perfil.CAMADA_GSHIFT))
SECS_MACRO = range(acoes.SEC_MACRO_MIN, acoes.SEC_MACRO_MAX + 1)


class ErroPainel(Exception):
    pass


def validar_campos(campos):
    """Devolve uma mensagem de erro em português, ou None se os tipos estão certos."""
    for k, v in campos.items():
        if k == "ativa":
            ok = isinstance(v, bool)
        elif k == "niveis":
            ok = isinstance(v, list) and all(isinstance(n, int) and not isinstance(n, bool) for n in v)
        elif k in ("botoes", "gshift"):
            ok = isinstance(v, list) and all(isinstance(a, dict) for a in v)
        elif k == "nome":
            ok = isinstance(v, str)
        else:
            ok = isinstance(v, int) and not isinstance(v, bool)
        if not ok:
            return f"Valor inválido para {k}."
    return None


class Painel:
    def __init__(self, mouse, pasta_dados, backup=BACKUP_PADRAO):
        self.m = mouse
        self.pasta = pasta_dados
        self.backup = backup
        self.lock = threading.Lock()

    # leitura

    def _macro_setor(self, sec, cache):
        if sec not in cache:
            cache[sec] = self.m.ler_setor(sec, crc=False)
        return cache[sec]

    def _acoes_vaga(self, lista, camada, cache):
        res = []
        for i, a in enumerate(lista):
            a = dict(a)
            if a["tipo"] == "especial":
                a["testado"] = a["codigo"] in acoes.ESPECIAIS_TESTADOS
            elif a["tipo"] == "macro":
                m = acoes.ler_macro(self._macro_setor(a["sec"], cache), a["offset"])
                a["macro_estado"] = m["estado"]
                a["aviso"] = ""
                if m["estado"] != "ok":
                    onde = f"Botão {NOMES_BOTOES[i]}" if camada == "normal" else f"G-Shift, botão {NOMES_BOTOES[i]}"
                    a["aviso"] = (f"{onde}: macro no setor {a['sec']} está "
                                  + ("vazia, o botão não faz nada" if m["estado"] == "vazia"
                                     else "inválida, o botão não faz nada"))
            res.append(a)
        return res

    def _vaga(self, sec, setor, ativa, em_uso, cache=None):
        cache = {} if cache is None else cache
        v = perfil.ler_vaga(setor)
        return {
            "sec": sec,
            "nome": v["nome"] if v["nome"] not in (None, "", NOME_FABRICA) else f"Vaga {sec}",
            "nome_real": v["nome"] if v["nome"] not in (None, "", NOME_FABRICA) else None,
            "ativa": ativa,
            "em_uso": sec == em_uso,
            "crc_ok": v["crc_ok"],
            "polling_hz": v["polling_hz"],
            "dpis": v["dpis"],
            "niveis": v["niveis"],
            "dpi_padrao": v["dpi_padrao"],
            "dpi_shift": v["dpi_shift"],
            "botoes": self._acoes_vaga(v["botoes"], "normal", cache),
            "gshift": self._acoes_vaga(v["gshift"], "gshift", cache),
            "lod": v["lod"],
            "um_nivel": v["um_nivel"],
            "aviso": "" if v["crc_ok"] else "CRC inválido: restaure a vaga para os valores de fábrica antes de editar.",
        }

    def _referencias(self, dire):
        refs = []
        for s, _ in sorted(dire):
            if not 1 <= s <= 5:
                continue
            v = perfil.ler_vaga(self.m.ler_setor(s, crc=False))
            for camada, lista in (("normal", v["botoes"]), ("gshift", v["gshift"])):
                for i, a in enumerate(lista):
                    if a["tipo"] == "macro":
                        refs.append({"vaga": s, "camada": camada, "botao": NOMES_BOTOES[i],
                                     "sec": a["sec"], "offset": a["offset"]})
        return refs

    def _macros(self, refs):
        res = []
        for sec in SECS_MACRO:
            m = acoes.ler_macro(self.m.ler_setor(sec, crc=False))
            usos = [{k: r[k] for k in ("vaga", "camada", "botao", "offset")} for r in refs if r["sec"] == sec]
            res.append({"sec": sec, "estado": m["estado"], "passos": m["passos"], "usada_por": usos})
        return res

    def _vaga_atual(self, sec):
        em_uso = self.m.perfil_ativo()
        ativa = dict(self.m.diretorio()).get(sec)
        return self._vaga(sec, self.m.ler_setor(sec, crc=False), bool(ativa), em_uso)

    def listar(self):
        with self.lock:
            em_uso = self.m.perfil_ativo()
            dire = self.m.diretorio()
            cache = {}
            vagas = [self._vaga(s, self.m.ler_setor(s, crc=False), ativo, em_uso, cache)
                     for s, ativo in sorted(dire) if 1 <= s <= 5]
            aviso = None
            if len(dire) != 5:
                aviso = f"O diretório do mouse tem {len(dire)} entradas (esperado: 5). Confira o backup antes de gravar."
            return {"em_uso": em_uso, "taxas": self.m.taxas_suportadas(), "vagas": vagas,
                    "macros": self._macros(self._referencias(dire)), "aviso_diretorio": aviso}

    # apoio à gravação

    def _checar(self, sec):
        dire = dict(self.m.diretorio())
        if sec not in dire:
            raise ErroPainel(f"Vaga {sec} não existe no mouse.")
        return dire

    def _garantir_backup(self):
        if os.path.exists(self.backup):
            return
        try:
            self._salvar_backup()
        except FileExistsError:
            pass
        except Exception as e:
            raise ErroPainel(f"Backup falhou ({e}), nada foi gravado no mouse.")

    def _salvar_backup(self):
        # formato JSON do prox2; nunca sobrescreve. Lê com CRC (que já relê);
        # só se falhar guarda o setor como está (crc=False)
        bk = {}
        for s in range(0, 16):
            try:
                d = self.m.ler_setor(s) if s < 6 else self.m.ler_setor(s, crc=False)
            except IOError:
                d = self.m.ler_setor(s, crc=False)
            bk[f"{s:#06x}"] = d.hex()
        os.makedirs(os.path.dirname(os.path.abspath(self.backup)), exist_ok=True)
        tmp = self.backup + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(bk, f, indent=1)
            os.link(tmp, self.backup)  # falha se já existir
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _garantir_backup_macros(self):
        # backup antigo só com 0..5: guarda os setores 6..15 à parte, uma única vez
        try:
            with open(self.backup) as f:
                if "0x0006" in json.load(f):
                    return
        except (OSError, ValueError):
            pass
        caminho = os.path.join(self.pasta, "backup_macros.json")
        if os.path.exists(caminho):
            return
        try:
            os.makedirs(self.pasta, exist_ok=True)
            bk = {f"{s:#06x}": self.m.ler_setor(s, crc=False).hex() for s in SECS_MACRO}
            tmp = caminho + ".tmp"
            try:
                with open(tmp, "w") as f:
                    json.dump(bk, f, indent=1)
                os.link(tmp, caminho)  # falha se já existir
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except FileExistsError:
            pass
        except Exception as e:
            raise ErroPainel(f"Backup das macros falhou ({e}), nada foi gravado no mouse.")

    def _voltar_perfil(self, original, em_curso):
        # sem exceção em curso, propaga; com exceção, mantém a original
        try:
            self.m.definir_perfil(original)
        except (TimeoutError, IOError, OSError):
            if not em_curso:
                raise

    def _historico(self, sec, dados):
        pasta = os.path.join(self.pasta, "historico")
        os.makedirs(pasta, exist_ok=True)
        base = f"{datetime.datetime.now():%Y%m%d-%H%M%S}-setor{sec}"
        caminho, n = os.path.join(pasta, base + ".hex"), 1
        while os.path.exists(caminho):
            n += 1
            caminho = os.path.join(pasta, f"{base}-{n}.hex")
        with open(caminho, "w") as f:
            f.write(bytes(dados).hex() + "\n")

    def _gravar_setor(self, sec, antigo, novo):
        self._historico(sec, antigo)
        try:
            self.m.gravar_verificado(sec, novo)
        except (TimeoutError, IOError) as e:
            # macro sem CRC válido seria recusada pelo mouse: volta como setor vazio com CRC
            volta = antigo if sec < 6 or crc_ok(antigo) else acoes.setor_macro_vazio()
            try:
                self.m.gravar_verificado(sec, volta)
            except (TimeoutError, IOError):
                raise ErroPainel(f"Falha ao gravar o setor {sec} ({e}) e o original não pôde ser regravado. "
                                 "Restaure a vaga ou o backup.")
            raise ErroPainel(f"Falha ao gravar o setor {sec} ({e}). O conteúdo original foi regravado.")

    # operações

    def gravar(self, sec, *, niveis=None, dpi_padrao=None, dpi_shift=None, polling_hz=None, lod=None,
               botoes=None, gshift=None, ativa=None, nome=None):
        with self.lock, self.m.transacao(gravando=True):
            dire = self._checar(sec)
            try:
                atual = self.m.ler_setor(sec)
            except IOError:
                atual = self.m.ler_setor(sec, crc=False)
            muda_dados = any(x is not None for x in (niveis, dpi_padrao, dpi_shift, polling_hz, lod, botoes, gshift, nome))
            era_ativa = dire[sec]
            if ativa is False and era_ativa:
                if sec == self.m.perfil_ativo():
                    raise ErroPainel("Esta vaga está em uso no mouse. Use outra vaga antes de desligá-la.")
                if sum(1 for a in dire.values() if a) <= 1:
                    raise ErroPainel("Pelo menos uma vaga precisa ficar ativa.")
            base, forcar = atual, False
            if not crc_ok(atual):
                if not era_ativa and ativa:
                    base, forcar = self.m.ler_setor(self.m.perfil_ativo(), crc=False), True
                elif muda_dados:
                    raise ErroPainel("A vaga está com CRC inválido. Restaure a vaga antes de editar.")
            try:
                nome_novo = "" if forcar and nome is None else nome
                novo = perfil.montar_vaga(base, niveis=niveis, dpi_padrao=dpi_padrao, dpi_shift=dpi_shift,
                                          polling_hz=polling_hz, lod=lod, nome=nome_novo,
                                          botoes=botoes, gshift=gshift)
                self._checar_macros_novas(base, novo)
                dir0 = self.m.ler_setor(0)
                novo0 = dir0
                if ativa is not None and ativa != era_ativa:
                    novo0 = perfil.diretorio_com_ativo(dir0, sec, ativa)
            except ValueError as e:
                raise ErroPainel(str(e))
            if novo == atual and not forcar and novo0 == dir0:
                return self._vaga_atual(sec)
            self._garantir_backup()
            original = self.m.perfil_ativo()
            em_curso = True
            try:
                if novo != atual or forcar:
                    self._gravar_setor(sec, atual, novo)
                if novo0 != dir0:
                    try:
                        self._gravar_setor(0, dir0, novo0)
                    except ErroPainel as e:
                        if novo == atual and not forcar:
                            raise
                        try:
                            self.m.gravar_verificado(sec, atual)
                        except (TimeoutError, IOError):
                            raise ErroPainel(f"{e} O setor {sec} já tinha sido gravado e NÃO pôde ser "
                                             "regravado com o original. Restaure a vaga ou o backup.")
                        raise ErroPainel(f"{e} O setor {sec}, gravado antes, também foi regravado com o original.")
                if dict(self.m.diretorio()).get(sec):
                    self.m.definir_perfil(sec)  # recarrega o perfil gravado
                em_curso = False
            finally:
                self._voltar_perfil(original, em_curso)
            return self._vaga_atual(sec)

    def _checar_macros_novas(self, antigo, novo):
        cache = {}
        for camada, ini in CAMADAS:
            for i in range(perfil.BOTOES_N):
                o = ini + 4 * i
                if novo[o:o + 4] == antigo[o:o + 4]:
                    continue  # já era assim, não bloqueia a edição de outros campos
                a = acoes.decodificar_acao(novo[o:o + 4])
                if a["tipo"] != "macro":
                    continue
                m = acoes.ler_macro(self._macro_setor(a["sec"], cache), a["offset"])
                if m["estado"] != "ok":
                    estado = "vazia" if m["estado"] == "vazia" else "inválida"
                    raise ErroPainel(f"A macro do setor {a['sec']} está {estado}. Grave a macro antes de "
                                     f"ligá-la ao botão {NOMES_BOTOES[i]}.")

    # macros

    @staticmethod
    def _quem_usa(usos):
        return "; ".join(f"vaga {u['vaga']}, {'G-Shift' if u['camada'] == 'gshift' else 'camada normal'}, "
                         f"botão {u['botao']}" for u in usos)

    def gravar_macro(self, sec, passos):
        with self.lock, self.m.transacao(gravando=True):
            try:
                novo = acoes.montar_macro(passos)
            except ValueError as e:
                raise ErroPainel(str(e))
            if sec is not None and sec not in SECS_MACRO:
                raise ErroPainel(f"Setor de macro inválido: use de {SECS_MACRO[0]} a {SECS_MACRO[-1]}.")
            dire = self.m.diretorio()
            refs = self._referencias(dire)
            if sec is None:
                livres = {"vazia": [], "invalida": []}
                for s in SECS_MACRO:
                    estado = acoes.ler_macro(self.m.ler_setor(s, crc=False))["estado"]
                    if estado != "ok" and not any(r["sec"] == s for r in refs):
                        livres[estado].append(s)
                # prefere setor vazio, só usa inválido se não houver vazio
                if livres["vazia"] or livres["invalida"]:
                    sec = (livres["vazia"] or livres["invalida"])[0]
                else:
                    raise ErroPainel("Não há setor de macro livre. Apague uma macro que não use mais.")
            atual = self.m.ler_setor(sec, crc=False)
            if atual == novo:
                return sec
            fora = [r for r in refs if r["sec"] == sec and r["offset"] != 0]
            if fora:
                raise ErroPainel(f"O setor {sec} é usado com deslocamento diferente de zero por "
                                 f"{self._quem_usa(fora)}. Trocar a macro faria esse botão executar do meio de "
                                 "um passo. Troque a ação desse botão antes.")
            self._garantir_backup()
            self._garantir_backup_macros()
            em_uso = self.m.perfil_ativo()
            self._gravar_setor(sec, atual, novo)
            if any(r["sec"] == sec and r["vaga"] == em_uso for r in refs):
                self.m.definir_perfil(em_uso)  # recarrega o perfil que usa a macro
            return sec

    def apagar_macro(self, sec):
        with self.lock, self.m.transacao(gravando=True):
            if sec not in SECS_MACRO:
                raise ErroPainel(f"Setor de macro inválido: use de {SECS_MACRO[0]} a {SECS_MACRO[-1]}.")
            usos = [r for r in self._referencias(self.m.diretorio()) if r["sec"] == sec]
            if usos:
                raise ErroPainel(f"A macro do setor {sec} está em uso por {self._quem_usa(usos)}. "
                                 "Troque a ação desses botões antes de apagar.")
            atual = self.m.ler_setor(sec, crc=False)
            if acoes.ler_macro(atual)["estado"] == "vazia":
                return sec
            self._garantir_backup()
            self._garantir_backup_macros()
            self._gravar_setor(sec, atual, acoes.setor_macro_vazio())
            return sec

    def usar_agora(self, sec):
        with self.lock:
            if not self._checar(sec)[sec]:
                raise ErroPainel("Esta vaga está desligada. Ligue-a antes de usar.")
            self.m.definir_perfil(sec)
            return self._vaga_atual(sec)

    def restaurar(self, sec):
        with self.lock, self.m.transacao(gravando=True):
            dire = self._checar(sec)
            atual = self.m.ler_setor(sec, crc=False)
            novo = com_crc(self.m.ler_setor(perfil.ROM_FABRICA, crc=False))
            self._garantir_backup()
            original = self.m.perfil_ativo()
            em_curso = True
            try:
                self._gravar_setor(sec, atual, novo)
                if dire[sec]:
                    self.m.definir_perfil(sec)
                em_curso = False
            finally:
                self._voltar_perfil(original, em_curso)
            return self._vaga_atual(sec)
