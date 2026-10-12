"""Regras de negócio do Painel de perfis (sem HTTP, sem /dev/hidraw)."""
import datetime
import json
import os
import threading

import perfil
from prox2 import BACKUP_PADRAO, com_crc, crc_ok


NOME_FABRICA = "PROFILE_NAME_DEFAULT"  # nome de fábrica, tratado como sem nome


class ErroPainel(Exception):
    pass


class Painel:
    def __init__(self, mouse, pasta_dados, backup=BACKUP_PADRAO):
        self.m = mouse
        self.pasta = pasta_dados
        self.backup = backup
        self.lock = threading.Lock()

    # leitura

    def _vaga(self, sec, setor, ativa, em_uso):
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
            "lod": v["lod"],
            "um_nivel": v["um_nivel"],
            "aviso": "" if v["crc_ok"] else "CRC inválido: restaure a vaga para os valores de fábrica antes de editar.",
        }

    def _vaga_atual(self, sec):
        em_uso = self.m.perfil_ativo()
        ativa = dict(self.m.diretorio()).get(sec)
        return self._vaga(sec, self.m.ler_setor(sec, crc=False), bool(ativa), em_uso)

    def listar(self):
        with self.lock:
            em_uso = self.m.perfil_ativo()
            dire = self.m.diretorio()
            vagas = [self._vaga(s, self.m.ler_setor(s, crc=False), ativo, em_uso)
                     for s, ativo in sorted(dire) if 1 <= s <= 5]
            aviso = None
            if len(dire) != 5:
                aviso = f"O diretório do mouse tem {len(dire)} entradas (esperado: 5). Confira o backup antes de gravar."
            return {"em_uso": em_uso, "taxas": self.m.taxas_suportadas(), "vagas": vagas,
                    "aviso_diretorio": aviso}

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
        # guarda os setores como estão (crc=False), no formato JSON do prox2; nunca sobrescreve
        bk = {f"{s:#06x}": self.m.ler_setor(s, crc=False).hex() for s in range(0, 6)}
        tmp = self.backup + ".tmp"
        try:
            with open(tmp, "w") as f:
                json.dump(bk, f, indent=1)
            os.link(tmp, self.backup)  # falha se já existir
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

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
            try:
                self.m.gravar_verificado(sec, antigo)
            except (TimeoutError, IOError):
                raise ErroPainel(f"Falha ao gravar o setor {sec} ({e}) e o original não pôde ser regravado. "
                                 "Restaure a vaga ou o backup.")
            raise ErroPainel(f"Falha ao gravar o setor {sec} ({e}). O conteúdo original foi regravado.")

    # operações

    def gravar(self, sec, *, dpi=None, polling_hz=None, lod=None, um_dpi_so=False, ativa=None, nome=None):
        with self.lock:
            dire = self._checar(sec)
            try:
                atual = self.m.ler_setor(sec)
            except IOError:
                atual = self.m.ler_setor(sec, crc=False)
            muda_dados = any(x is not None for x in (dpi, polling_hz, lod, nome))
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
                novo = perfil.montar_vaga(base, dpi=dpi, polling_hz=polling_hz, lod=lod,
                                          nome=nome_novo, um_dpi_so=um_dpi_so)
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

    def usar_agora(self, sec):
        with self.lock:
            if not self._checar(sec)[sec]:
                raise ErroPainel("Esta vaga está desligada. Ligue-a antes de usar.")
            self.m.definir_perfil(sec)
            return self._vaga_atual(sec)

    def restaurar(self, sec):
        with self.lock:
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
