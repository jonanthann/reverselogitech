#!/usr/bin/env python3
"""Valida no mouse hipóteses de bytes do perfil (formato 7) tiradas do G HUB.

Sem argumentos: só leitura do perfil ativo (ou --perfil N).
--set BYTE=VALOR: faz backup, grava, confere, espera Enter e restaura (salvo --sem-restaurar).
--restaurar ARQUIVO: grava um backup .bin de volta.
Bytes graváveis: 0 e 1 (taxa, 0..6), 34 (angle snapping, 0/1), 37 (bunny hop, 0..255).
"""
import argparse, os, sys, time

from prox2 import RATES, ErroMouse, Mouse, com_crc, crc_ok

TAM = 255
PASTA_BACKUP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "backups")
LEITURA = [0, 1, *range(29, 38), 44, 45, 46, 47]
LIMITES = {0: 6, 1: 6, 34: 1, 37: 0xFF}


def valor_set(texto):
    """Converte 'BYTE=VALOR' em (indice, valor), validando os limites."""
    try:
        b, v = texto.split("=", 1)
        b, v = int(b, 0), int(v, 0)
    except ValueError:
        raise argparse.ArgumentTypeError(f"formato inválido '{texto}', use BYTE=VALOR")
    if b not in LIMITES:
        raise argparse.ArgumentTypeError(f"byte {b} não permitido (use {', '.join(map(str, LIMITES))})")
    if not 0 <= v <= LIMITES[b]:
        raise argparse.ArgumentTypeError(f"valor {v} fora de 0..{LIMITES[b]} para o byte {b}")
    return b, v


def montar_setor(original, alteracoes):
    """Aplica {byte: valor} ao setor e recalcula o CRC."""
    if len(original) != TAM:
        raise ValueError(f"setor com {len(original)} bytes, esperado {TAM}")
    b = bytearray(original)
    for i, v in alteracoes.items():
        b[i] = v
    return com_crc(bytes(b))


def interpretar(setor, i):
    v = setor[i]
    if i in (0, 1):
        return f"{RATES[v]} Hz" if v < len(RATES) else "fora da faixa"
    if i == 34:
        return {0: "angle snapping desligado", 1: "angle snapping ligado"}.get(v, "valor inesperado")
    if i == 37:
        return "bunny hop desligado" if v in (0, 0xFF) else f"{v * 10} ms"
    if i in (44, 46):
        n = setor[i] | setor[i + 1] << 8
        return "FFFF (zero/desligado)" if n == 0xFFFF else f"LE={n}, BE={setor[i] << 8 | setor[i + 1]}"
    return ""


def mostrar(setor):
    for i in LEITURA:
        print(f"byte {i:3d}: 0x{setor[i]:02X} ({setor[i]:3d})  {interpretar(setor, i)}")
    print("CRC do setor:", "ok" if crc_ok(setor) else "INVÁLIDO")


def salvar_backup_bin(sec, setor, pasta=None):
    pasta = pasta or PASTA_BACKUP
    os.makedirs(pasta, exist_ok=True)
    caminho = os.path.join(pasta, f"perfil_{sec}_{time.strftime('%Y%m%d_%H%M%S')}.bin")
    with open(caminho, "xb") as f:
        f.write(setor)
    return caminho


def conferir(m, sec, esperado):
    if m.ler_setor(sec, crc=False) != esperado:
        raise ErroMouse(f"setor {sec} lido de volta difere do gravado")


def aviso_restaurar(sec, caminho):
    print(f"Para restaurar rode: python3 testar_bytes.py --perfil {sec} --restaurar {caminho}")


def restaurar_original(m, sec, original, caminho):
    """Regrava o original e confere. Em falha, avisa e sai com código 1."""
    try:
        m.gravar_verificado(sec, original)
        conferir(m, sec, original)
    except (TimeoutError, IOError) as e:
        print(f"Falha ao restaurar ({e}): o perfil {sec} ficou alterado.")
        aviso_restaurar(sec, caminho)
        sys.exit(1)
    print(f"Perfil {sec}: original restaurado e conferido.")


def cmd_set(m, sec, alteracoes, restaurar):
    original = m.ler_setor(sec)
    novo = montar_setor(original, alteracoes)
    if novo == original:
        print("Os valores já são os atuais, nada a gravar.")
        return
    caminho = salvar_backup_bin(sec, original)
    print("Backup salvo em", caminho)
    with m.transacao(gravando=True):
        try:
            m.gravar_verificado(sec, novo)
            conferir(m, sec, novo)
        except (TimeoutError, IOError) as e:
            print(f"Falha ao gravar ({e}). Tentando regravar o original.")
            restaurar_original(m, sec, original, caminho)
            sys.exit(1)
        print(f"Perfil {sec}: gravado e conferido.")
        mostrar(novo)
        if not restaurar:
            print("Mantido como está (--sem-restaurar).")
            aviso_restaurar(sec, caminho)
            return
        try:
            input("Teste o mouse e aperte Enter para restaurar o original... ")
        finally:
            restaurar_original(m, sec, original, caminho)


def cmd_restaurar(m, arquivo, perfil):
    with open(arquivo, "rb") as f:
        dados = f.read()
    if len(dados) != TAM or not crc_ok(dados):
        sys.exit("Arquivo de backup inválido (tamanho ou CRC). Nada foi gravado.")
    try:
        sec = int(os.path.basename(arquivo).split("_")[1])
    except (IndexError, ValueError):
        sys.exit("Nome do arquivo fora do padrão perfil_N_<data>.bin. Nada foi gravado.")
    if not 1 <= sec <= 5:
        sys.exit("Perfil do backup fora de 1..5. Nada foi gravado.")
    if perfil != sec:
        sys.exit(f"O backup é do perfil {sec}, mas --perfil é {perfil}. Nada foi gravado.")
    with m.transacao(gravando=True):
        m.gravar_verificado(sec, dados)
        conferir(m, sec, dados)
    print(f"Perfil {sec}: backup restaurado e conferido.")


def main():
    p = argparse.ArgumentParser(description="Valida bytes do perfil do PRO X 2 Superlight")
    p.add_argument("--perfil", type=int, choices=range(1, 6), help="setor 1..5 (padrão: perfil ativo)")
    p.add_argument("--set", dest="sets", action="append", type=valor_set, metavar="BYTE=VALOR",
                   help="byte a gravar (0, 1, 34 ou 37); pode repetir")
    p.add_argument("--sem-restaurar", action="store_true", help="mantém o valor gravado")
    p.add_argument("--restaurar", metavar="ARQUIVO", help="grava um backup .bin de volta (exige --perfil)")
    a = p.parse_args()
    if a.restaurar and a.sets:
        p.error("--restaurar não combina com --set")
    if a.restaurar and not a.perfil:
        p.error("--restaurar exige --perfil explícito")
    m = Mouse()
    try:
        if a.restaurar:
            return cmd_restaurar(m, a.restaurar, a.perfil)
        sec = a.perfil or m.perfil_ativo()
        if not 1 <= sec <= 5:
            sys.exit(f"Perfil ativo {sec} fora de 1..5. Nada foi feito.")
        if a.sets:
            return cmd_set(m, sec, dict(a.sets), not a.sem_restaurar)
        print(f"Perfil {sec} (somente leitura)")
        mostrar(m.ler_setor(sec))
    finally:
        m.fechar()


if __name__ == "__main__":
    main()
