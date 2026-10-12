# Logitech PRO X 2 Superlight no Linux: polling rate com memória interna

Ferramentas para trocar o polling rate do Logitech PRO X 2 Superlight (sem fio, receptor Lightspeed USB `046d:c54d`) no Debian Linux, mantendo os perfis da memória interna (onboard profiles) ativos. Tudo fala HID++ 2.0 direto com o hidraw do receptor, sem sudo.

## O problema

Com a memória interna ativa, não era possível trocar o polling rate no Linux.

O Solaar não funciona com esse mouse. Ele lê o perfil num layout antigo (DPI em 2 bytes a partir do byte 3, polling só no byte 0), e o PRO X 2 usa o formato de perfil 7.

O OpenLogi também atrapalhava. Ele pegava o mouse com exclusividade (grab) e reenviava os eventos por um mouse virtual. Por isso foi desinstalado (`sudo apt purge openlogi`). Ferramentas desse tipo impedem medir a taxa real no event do mouse.

## Resultado

Os perfis 1 e 2 ficaram em 2000 Hz e 1600 DPI, gravados na memória interna. A configuração vale sem nenhum programa rodando e em outro PC.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `prox2.py` | Ferramenta principal: status, trocar taxa, backup e restauração. Sem sudo. |
| `prox2_backup_perfis.json` | Backup dos setores 0..5 de antes de qualquer alteração (original de fábrica/G Hub). |
| `testar_polling_raw.py` | Conta pacotes crus do receptor por 10 s. Sem sudo. É a melhor forma de medir. |
| `testar_polling.py` | Mede pelo evdev. Precisa de sudo. |
| `testar_host_mode.py` | Diagnóstico: testa a taxa em modo host. |

## Uso rápido

```
python3 prox2.py status
python3 prox2.py rate 2000
python3 prox2.py rate 2000 --perfil 1
python3 prox2.py dpi 1600
python3 prox2.py dpi 1600 --perfil 1
python3 prox2.py backup arquivo.json
python3 prox2.py restaurar arquivo.json [--sim]
```

- `status` mostra o estado atual dos perfis.
- `rate N` grava a taxa em Hz. Por padrão vale para todos os perfis ativos. Com `--perfil N`, só para aquele perfil.
- `dpi N` grava o DPI (X e Y iguais). Por padrão vale para todos os perfis ativos. Com `--perfil N`, só para aquele perfil. Só aceita perfis com um único nível de DPI, porque o índice do nível ativo ainda não foi confirmado. Valores fora das faixas do sensor são recusados, com sugestão dos mais próximos.
- `backup` salva os perfis num arquivo JSON.
- `restaurar` grava de volta os perfis de um arquivo JSON. A opção `--sim` é opcional.

Na primeira gravação, o `prox2.py` cria o backup automático `prox2_backup_perfis.json`. Se o arquivo já existir, ele não é sobrescrito.

Taxas acima de 2000 Hz consomem mais bateria. O firmware (MPM 32.05) suporta 4000 e 8000 Hz, mas essas taxas não foram testadas.

## Como medir

A melhor medição é a de pacotes crus, que não depende de nenhum software no meio:

```
python3 testar_polling_raw.py
```

Ela conta os pacotes do receptor por 10 segundos e não precisa de sudo.

Para medir pelo evdev (precisa de sudo):

```
sudo python3 testar_polling.py [/dev/input/eventN]
```

O padrão é `/dev/input/event7`. Passe outro caminho se o seu mouse estiver em outro event.

Para medir bem, mexa o mouse rápido e sem parar. Pausas puxam a média para baixo. Sites de teste no navegador podem subestimar a taxa.

Medições com o perfil em 2000 Hz: cerca de 1975 pacotes/s na contagem crua e 1979 Hz de máximo num teste online.

### Diagnóstico em modo host

```
python3 testar_host_mode.py [indice]
```

O script desliga a memória interna por alguns segundos, pede a taxa direto ao mouse, mede e religa a memória interna.

## O que foi descoberto

Feature HID++ 0x8100 (onboard profiles) e 0x8061 (extended report rate).

### Layout do perfil

Cada perfil ocupa os setores 1..5, com 255 bytes. Os 2 últimos bytes são o CRC-CCITT (init `0xFFFF`, poly `0x1021`, big-endian).

| Byte | Conteúdo |
|---|---|
| 0 | Taxa realmente usada pelo mouse |
| 1 | Taxa que o mouse informa (`getReportRate` da feature 0x8061) |
| 2 e 3 | Ainda não confirmados |
| 4 em diante | DPI: 5 entradas de 5 bytes |
| 253 e 254 | CRC |

Cada entrada de DPI tem X (2 bytes, little-endian), Y (2 bytes, little-endian) e 1 byte que provavelmente é o lift-off.

Os valores de taxa são índices:

| Índice | Taxa |
|---|---|
| 0 | 125 Hz |
| 1 | 250 Hz |
| 2 | 500 Hz |
| 3 | 1000 Hz |
| 4 | 2000 Hz |
| 5 | 4000 Hz |
| 6 | 8000 Hz |

### A armadilha dos bytes 0 e 1

Gravar só o byte 1 faz o mouse informar 2000 Hz, mas ele continua transmitindo a 1000 Hz. É preciso gravar os bytes 0 e 1 juntos.

Foi assim que isso foi provado:

1. No modo host, a taxa pedida direto deu cerca de 1870 pacotes/s, então o mouse era capaz de 2000 Hz.
2. Com os bytes 0 e 1 gravados no perfil, a medição deu cerca de 1975 pacotes/s.

## Por que o Solaar falha

O Solaar assume o layout antigo de perfil: DPI em 2 bytes a partir do byte 3 e polling só no byte 0. No formato 7 do PRO X 2, o DPI são 5 entradas de 5 bytes a partir do byte 4, e a taxa está nos bytes 0 e 1. O Solaar interpreta os bytes errados e não consegue trocar a taxa com a memória interna ativa.

## Restaurar o original

O `prox2_backup_perfis.json` guarda os setores 0..5 de antes de qualquer alteração, ou seja, o original de fábrica/G Hub. Para voltar a ele:

```
python3 prox2.py restaurar prox2_backup_perfis.json [--sim]
```
