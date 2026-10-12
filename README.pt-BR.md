[English](README.md) | Português

# Engenharia reversa do HID++ do Logitech PRO X 2 Superlight: polling rate e DPI na memória interna, no Linux

Engenharia reversa do protocolo HID++ do Logitech PRO X 2 Superlight (sem fio, receptor Lightspeed USB `046d:c54d`), para facilitar o uso da memória interna (onboard profiles) no Linux, especificamente no Debian. As ferramentas trocam o polling rate e o DPI sem desativar os perfis da memória interna. Tudo fala HID++ 2.0 direto com o hidraw do receptor.

O `/dev/hidraw` do receptor costuma vir só para root. Para liberar o acesso ao seu usuário, instale a regra udev do repositório:

```
sudo cp udev/60-prox2.rules /etc/udev/rules.d/
sudo udevadm control --reload && sudo udevadm trigger
```

Depois, reconecte o receptor. Se você copiou a antiga `70-prox2-hidraw.rules` para `/etc/udev/rules.d/`, apague-a. Como alternativa temporária, `sudo chmod a+rw /dev/hidraw6` (o número varia) ou rodar os comandos com sudo.

## O problema

Com a memória interna ativa, não era possível trocar o polling rate no Linux.

O Solaar não funciona com esse mouse. Ele lê o perfil num layout antigo (DPI em 2 bytes a partir do byte 3, polling só no byte 0), e o PRO X 2 usa o formato de perfil 7.

O OpenLogi também atrapalhava. Ele pegava o mouse com exclusividade (grab) e reenviava os eventos por um mouse virtual. Por isso foi desinstalado (`sudo apt purge openlogi`). Ferramentas desse tipo impedem medir a taxa real no event do mouse.

## Resultado

Os perfis 1 e 2 ficaram em 2000 Hz e 1600 DPI, gravados na memória interna. A configuração vale sem nenhum programa rodando e em outro PC.

## Arquivos

| Arquivo | Para que serve |
|---|---|
| `prox2.py` | Ferramenta principal: status, trocar taxa e DPI, backup e restauração. Com o hidraw liberado, roda sem sudo. |
| `tests/dados/prox2_backup_perfis.json` | Exemplo para testes: backup dos setores 0..5 de antes de qualquer alteração (original de fábrica/G Hub). O seu backup fica em `~/.local/share/myproX2/`. |
| `myprox2.py`, `app/` | App GNOME myproX2. |
| `caminhos.py` | Pastas de dados e configuração (XDG). |
| `debian/` | Empacotamento do `.deb`. |
| `LICENSE` | Licença MIT. |
| `testar_polling_raw.py` | Conta pacotes crus do receptor por 10 s. Com o hidraw liberado, roda sem sudo. É a melhor forma de medir. |
| `testar_polling.py` | Mede pelo evdev. Precisa de sudo. |
| `testar_host_mode.py` | Diagnóstico: testa a taxa em modo host. |
| `painel_web.py` | Servidor do painel. |
| `painel_core.py` | Regras de gravação do painel. |
| `acoes.py` | Ações de botão (4 bytes) e macros. |
| `perfil.py` | Leitura e montagem dos setores de perfil. |
| `painel/index.html` | Página do painel. |
| `udev/60-prox2.rules` | Regra udev que libera o hidraw do receptor para o seu usuário. |
| `tests/` | Testes, rodam com `python3 -m unittest discover -s tests`. Não usam o mouse. |

## Uso rápido

```
python3 prox2.py status
python3 prox2.py rate 2000
python3 prox2.py rate 2000 --perfil 1
python3 prox2.py rate 2000 --perfil 1 2
python3 prox2.py dpi 1600
python3 prox2.py dpi 1600 --perfil 1
python3 prox2.py backup arquivo.json
python3 prox2.py restaurar arquivo.json [--sim]
```

- `status` mostra o estado atual dos perfis.
- `rate N` grava a taxa em Hz. Por padrão vale para todos os perfis ativos. Com `--perfil N` (um ou mais setores, de 1 a 5), só para esses perfis.
- `dpi N` grava o DPI (X e Y iguais). Por padrão vale para todos os perfis ativos. Com `--perfil N` (um ou mais setores, de 1 a 5), só para esses perfis. Só aceita perfis com um único nível de DPI (para vários níveis, use o painel). Valores fora das faixas do sensor são recusados, com sugestão dos mais próximos.
- `backup` salva os setores 0..15 (perfis e macros) num arquivo JSON.
- `restaurar` grava de volta os perfis de um arquivo JSON. A opção `--sim` é opcional. Setores do arquivo com CRC inválido são pulados com aviso, e os demais são restaurados.

Na primeira gravação, o `prox2.py` cria o backup automático `prox2_backup_perfis.json` na pasta de dados (veja "Onde ficam os dados"). Se o arquivo já existir, ele não é sobrescrito.

Taxas acima de 2000 Hz consomem mais bateria. O firmware (MPM 32.05) suporta 4000 e 8000 Hz, mas essas taxas não foram testadas.

## Painel local

```
python3 prox2.py painel
```

Abre o navegador numa página local. O servidor escuta só em 127.0.0.1, e a URL leva uma chave. Opções: `--porta N` define a porta, e `--sem-navegador` não abre o navegador e imprime a URL. Fechar a aba encerra o servidor em até 2 minutos, ou use Ctrl+C. Depois de fechado, o mouse continua usando o que está gravado na memória, em qualquer PC.

A página mostra as 5 vagas (perfis) da memória interna lado a lado. Clique numa para abrir o editor: DPI, polling rate, LOD (baixo, médio, alto), nome (até 24 caracteres, gravado no próprio mouse) e ligar/desligar a vaga (caixa "Vaga ativa"). Os botões:

- "Gravar no mouse": grava e confere relendo.
- "Usar agora": troca o perfil em uso. A escolha continua depois de desligar o mouse.
- "Restaurar": pede confirmação ("Sim, restaurar" ou "Cancelar") e então volta a vaga ao padrão de fábrica, lido da ROM do mouse: 800 a 3200 DPI em 5 níveis, 1000 Hz, LOD médio.

DPI: de 1 a 5 níveis, de 100 a 44000. Marque qual é o nível padrão (o que o mouse usa ao ligar) e qual é o do shift (o que vale com a ação "DPI shift").

Botões: os 5 botões (esquerdo, direito, meio, voltar, avançar) podem ser remapeados na camada normal e na camada G-Shift (que só vale com um botão configurado como G-Shift). Cada botão aceita clique, tecla (com modificadores), mídia, especial, macro ou desligado. Algum botão da camada normal precisa continuar com o clique esquerdo. Ações especiais testadas no mouse: ciclar DPI e DPI shift. As demais (próximo/anterior DPI, DPI padrão, próximo/anterior/ciclar perfil, G-Shift) vêm do libratbag e não foram testadas.

Macros: ficam nos setores 6..15, são listadas numa seção própria (criar, editar, apagar) e cada passo é apertar tecla, soltar tecla ou esperar (ms). Toda tecla apertada precisa ser solta no fim. Dá para gerar os passos a partir de um texto (letras, números, espaço, Enter e Tab). Não dá para apagar uma macro que um botão usa.

Limites: não dá para desligar a vaga em uso nem a última ativa.

Segurança: antes da primeira gravação, o backup original vai para `~/.local/share/myproX2/prox2_backup_perfis.json`. Se o backup antigo tiver só os setores 0..5, os setores de macro 6..15 vão uma vez para `~/.local/share/myproX2/painel_dados/backup_macros.json`. Uma cópia de cada setor anterior vai para `~/.local/share/myproX2/painel_dados/historico/`.

A interface do painel é em português, como o resto do programa.

## Onde ficam os dados

Os dados graváveis ficam em `~/.local/share/myproX2/` (ou `$XDG_DATA_HOME/myproX2`): o backup `prox2_backup_perfis.json` e a pasta `painel_dados/`. Na primeira execução pelo repositório, os antigos da raiz do repositório são copiados para lá (os originais ficam onde estão). Essa cópia não acontece quando o código está instalado pelo `.deb`.

## App myproX2 (GNOME)

App nativo do GNOME (GTK 4 e libadwaita) sobre o mesmo código do `prox2.py`. Precisa de `python3-gi`, `gir1.2-gtk-4.0` e `gir1.2-adw-1`. Para o ícone na barra no GNOME, instale `gnome-shell-extension-appindicator`.

- Mostra a bateria do mouse, com ícone na barra superior (bandeja) e notificações.
- Janela com as vagas (perfis) e o DPI.
- Aba "Botões": os 5 botões em 2 camadas, normal e G-Shift.
- Aba "Macros".
- "Iniciar com a sessão" no menu.

```
python3 myprox2.py
python3 myprox2.py --background
python3 myprox2.py --falso
python3 myprox2.py instalar-local
python3 myprox2.py desinstalar-local
```

- Sem opções, abre a janela.
- `--background` inicia sem janela, só o ícone na barra.
- `--falso` usa um mouse simulado em memória. Não toca no mouse real, então é seguro para testar a interface.
- `--simular-bateria N` e `--simular-carga` simulam o nível de bateria e a carga.
- `instalar-local` coloca o app no menu do seu usuário (`.desktop` e ícone) apontando para este repositório. `desinstalar-local` remove. O `instalar-local` se recusa a rodar quando o app veio do `.deb`.

## Pacote `.deb`

A pasta `debian/` gera o pacote `prox2`, que instala os comandos `prox2` e `myprox2`, a regra udev e a entrada no menu.

Dependências de build:

```
sudo apt install build-essential debhelper dh-python lintian
```

Compilar (o `.deb` sai na pasta pai):

```
dpkg-buildpackage -us -uc -b
```

Antes de instalar, rode `python3 myprox2.py desinstalar-local` e apague a regra udev manual antiga (`/etc/udev/rules.d/70-prox2-hidraw.rules`). Depois:

```
sudo apt install ./prox2_0.1.0_all.deb
```

Dependências de execução: `python3`, `python3-gi`, `gir1.2-gtk-4.0` e `gir1.2-adw-1` (recomendado: `gnome-shell-extension-appindicator`). Para remover: `sudo apt purge prox2`. Seus dados em `~/.local/share/myproX2/` ficam.

## Manual de uso do myproX2

Passo a passo para usar o app no dia a dia. A instalação está em "Pacote `.deb`" e o formato dos dados em "O que foi descoberto".

### Primeiros passos

1. Instale o `.deb` (veja "Pacote `.deb`") e reconecte o receptor, para a regra udev valer.
2. Ligue o mouse e abra o **myproX2** pelo menu de aplicativos. Ou rode `myprox2` no terminal.
3. Para ver o ícone na barra superior do GNOME, instale `gnome-shell-extension-appindicator` e ative a extensão. Sem ela o app funciona, só que sem o ícone.

Fechar a janela não encerra o app: ele continua na barra, lendo a bateria. Para abrir de novo, clique no ícone ou use "Abrir myproX2" no menu dele. Para encerrar de vez, veja "Fechar o app".

### Ícone na barra e bateria

O ícone mostra a carga do mouse. Passe o ponteiro por cima para ver a porcentagem e o estado (descarregando, carregando, carga completa). Se o mouse estiver desconectado, o texto mostra a hora da última leitura. O menu do ícone tem a bateria, "Abrir myproX2" e "Sair".

O app avisa por notificação quando:

- a bateria cai abaixo de 20% ("Bateria baixa");
- cai abaixo de 10% ("Bateria crítica", com urgência alta);
- o mouse termina de carregar ("Bateria carregada").

Cada aviso aparece uma vez por descarga. Ao colocar o mouse para carregar, os avisos de bateria baixa são zerados.

### Aba Vagas: DPI e perfil

A janela tem três abas embaixo: Vagas, Botões e Macros. No topo ficam a bateria e o estado (Conectado ou Desconectado). Com o mouse desconectado, a janela não deixa editar nada.

1. Na aba **Vagas**, clique no cartão da vaga (perfil) que quer editar. Cada cartão mostra o nome, os níveis de DPI, a taxa em Hz e se a vaga está em uso, ativa ou desligada.
2. Em "Níveis de DPI", mude o valor de cada nível (de 100 a 44000). "Adicionar nível" cria mais um (até 5) e "Remover" tira o nível. Marque **Padrão** no nível que o mouse usa ao ligar e **Shift** no que vale com a ação "DPI shift".
3. Ajuste o polling, o LOD e o nome (até 24 caracteres, gravado no mouse). A chave "Vaga ativa" liga ou desliga a vaga.
4. Clique em **Gravar no mouse**. Quando der certo, aparece "Gravado e verificado": o app grava e relê o setor para conferir.

Os outros botões da vaga:

- **Usar agora** troca o perfil em uso. A escolha continua depois de desligar o mouse. Uma vaga desligada não pode ser usada.
- **Restaurar** pergunta antes e volta a vaga ao padrão de fábrica (há backup para desfazer).

Se você mudou algo e tenta trocar de vaga ou usar outra, o app pergunta "Descartar alterações?". Escolha "Descartar" para abrir mão das mudanças ou "Cancelar" para voltar e gravar. Se o mouse for reconectado com mudanças pendentes, elas são descartadas, com um aviso.

Não dá para desligar a vaga em uso nem a última vaga ativa.

### Aba Botões

Mostra os 5 botões (esquerdo, direito, meio, trás e frente) da vaga selecionada, em duas camadas: **Camada normal** e **G-Shift**. A G-Shift só vale quando algum botão está com a ação especial "G-Shift".

Para cada botão, escolha o tipo:

- **Clique**: esquerdo, direito, meio, trás ou frente.
- **Tecla**: clique no campo, aperte a tecla desejada (aparece "Pressione...") e marque os modificadores, se precisar. Teclas que o mouse não suporta mostram "Tecla não suportada".
- **Mídia**: play/pausa, próxima faixa, faixa anterior, volume + e -, mudo.
- **Especial**: próximo DPI, DPI anterior, ciclar DPI, DPI padrão, DPI shift, próximo perfil, perfil anterior, ciclar perfil e G-Shift. Só "Ciclar DPI" e "DPI shift" foram testados no mouse; os outros aparecem com "(não testado)".
- **Macro**: escolha uma macro pronta ou crie uma em "Nova macro...".
- **Desligado**: o botão não faz nada.

A camada normal precisa ter ao menos um botão com clique esquerdo. Se não tiver, o app recusa a gravação e avisa. Depois de mexer, clique em **Gravar no mouse** nesta aba.

### Aba Macros

Lista as macros do mouse (até 10), com o estado (Vazia, Pronta ou Inválida) e quais botões usam cada uma.

1. Clique em **Nova macro**, ou em **Editar** numa existente.
2. No modo **Passos**, adicione "aperta", "solta" ou "espera" (em ms) e escolha a tecla de cada passo. Dá para subir, descer e remover passos. Toda tecla apertada precisa ser solta até o fim.
3. No modo **Texto**, digite o texto e a espera entre as teclas. Só letras, números e espaço, sem acentos.
4. Clique em **Salvar macro**. Aparece "Gravado e verificado". Depois, atribua a macro a um botão na aba Botões.
5. **Apagar** esvazia o setor, depois de pedir confirmação. O botão fica bloqueado enquanto algum botão usar a macro: troque a ação do botão e grave antes.

### Iniciar com a sessão

No menu da janela (ícone de três linhas, no canto), marque **Iniciar com a sessão**. O app passa a abrir sozinho no login, sem janela, só com o ícone na barra. Desmarque para desligar.

### Backup e restauração

Na primeira gravação, o app guarda o estado original do mouse em `~/.local/share/myproX2/prox2_backup_perfis.json`. Esse arquivo não é sobrescrito. Uma cópia de cada setor trocado vai para `~/.local/share/myproX2/painel_dados/historico/`.

Para voltar ao original, com o app fechado:

```
prox2 restaurar ~/.local/share/myproX2/prox2_backup_perfis.json
```

Para guardar o estado atual: `prox2 backup meu_backup.json`. Veja "Restaurar o original" para os detalhes.

### Testar sem mexer no mouse

```
myprox2 --falso
```

Abre o app com um mouse simulado em memória (bateria em 80%). Nada é gravado no mouse real e os dados somem ao fechar. Serve para conhecer a interface. Com `--simular-bateria N` e `--simular-carga` dá para ver as notificações de bateria.

### Solução de problemas

**Mouse não encontrado ou sem permissão.** A janela mostra "Desconectado" ou "Mouse desconectado". Confira se o mouse está ligado e o receptor no USB. Se o problema for permissão, instale a regra udev (pelo `.deb` ela já vem) e reconecte o receptor. Veja o começo deste README.

**"Outro programa (CLI, painel ou app) está gravando no mouse".** Só um programa grava por vez, usando uma trava em `$XDG_RUNTIME_DIR/myprox2.lock`. Espere alguns segundos e tente de novo. Se continuar, feche o painel web ou o `prox2` que estiver rodando. Programas que pegam o mouse com exclusividade (como o OpenLogi) também atrapalham.

**O ícone não aparece na barra.** Instale e ative `gnome-shell-extension-appindicator`, depois saia e entre de novo na sessão. O app funciona sem o ícone, mas aí só dá para abri-lo pelo menu de aplicativos.

**Fechar o app.** Fechar a janela só a esconde. Para encerrar:

- "Sair" no menu da janela ou no menu do ícone;
- `Ctrl+C` no terminal onde ele foi aberto;
- `pkill -f myprox2`, se não houver outra opção.

O app ignora `Ctrl+Z`: ele não fica suspenso, para não segurar o mouse sem poder ser fechado. Se uma versão antiga ficou presa por causa do `Ctrl+Z`, descubra o PID com `pgrep -f myprox2` e rode `kill -CONT <pid>; kill <pid>`.

## Como medir

A melhor medição é a de pacotes crus, que não depende de nenhum software no meio:

```
python3 testar_polling_raw.py
```

Ela conta os pacotes do receptor por 10 segundos e, com o hidraw liberado, não precisa de sudo.

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

Cada perfil ocupa os setores 1..5, com 255 bytes. Macros ficam nos setores 6..15. Os 2 últimos bytes são o CRC-CCITT (init `0xFFFF`, poly `0x1021`, big-endian).

| Byte | Conteúdo |
|---|---|
| 0 | Taxa realmente usada pelo mouse |
| 1 | Taxa que o mouse informa (`getReportRate` da feature 0x8061) |
| 2 | Nível de DPI padrão (índice de 0 a 4) |
| 3 | Nível de DPI do shift (índice de 0 a 4) |
| 4 em diante | DPI: 5 entradas de 5 bytes |
| 48 a 67 | Ações dos 5 botões na camada normal, 4 bytes cada (48+4i) |
| 112 a 131 | Ações dos 5 botões na camada G-Shift (112+4i) |
| 160 a 207 | Nome do perfil, UTF-16LE (`ff` = sem nome) |
| 253 e 254 | CRC |

Cada entrada de DPI tem X (2 bytes, little-endian), Y (2 bytes, little-endian) e 1 byte com o LOD (lift-off). O LOD da entrada k fica no byte 8+5k: 1 é baixo, 2 é médio, 3 é alto. Foi confirmado no sensor e num teste físico.

Formato das ações de botão (4 bytes):

| Bytes | Ação |
|---|---|
| `80 01 00 <máscara>` | Clique: 01 esquerdo, 02 direito, 04 meio, 08 voltar, 10 avançar |
| `80 02 <mod> <tecla>` | Tecla HID com modificadores |
| `80 03 <hi> <lo>` | Mídia (código de 16 bits) |
| `90 <código> 00 00` | Especial: 03 próximo DPI, 04 DPI anterior, 05 ciclo DPI, 06 DPI padrão, 07 shift DPI, 08 próximo perfil, 09 perfil anterior, 0a ciclo perfil, 0b G-Shift |
| `00 <setor> 00 <offset>` | Macro no setor 6..15, a partir do offset |
| `ff ff ff ff` | Desligado |

Só 05 e 07 foram testados. Os outros códigos vêm do libratbag.

### Macros

Cada macro fica num setor de 6 a 15, com 253 bytes úteis e CRC nos 2 últimos. Itens de 3 bytes: `43 <mod> <tecla>` aperta, `44 <mod> <tecla>` solta, `40 <ms hi> <ms lo>` espera (milissegundos, big-endian) e `ff` marca o fim. Os itens podem cruzar blocos de 16 bytes (testado). O setor de macro exige CRC: gravar sem CRC dá erro HID++ 0x4. Setor de macro vazio é todo `ff` com CRC.

Quando o mouse troca o nível de DPI, ele avisa com o evento HID++ `11 01 0d 10 <nível>`.

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

### Diretório, perfil de fábrica e perfil em uso

- O setor 0 (o diretório) tem CRC próprio. O byte 2 de cada entrada liga ou desliga a vaga.
- O mouse recusa usar uma vaga desligada.
- O perfil de fábrica está na ROM, no setor `0x0101`. O CRC da ROM não bate, então é preciso recalcular.
- A escolha do perfil em uso persiste ao desligar o mouse.

## Por que o Solaar falha

O Solaar assume o layout antigo de perfil: DPI em 2 bytes a partir do byte 3 e polling só no byte 0. O libratbag também não suporta o formato de perfil 7. No formato 7 do PRO X 2, o DPI são 5 entradas de 5 bytes a partir do byte 4, e a taxa está nos bytes 0 e 1. O Solaar interpreta os bytes errados e não consegue trocar a taxa com a memória interna ativa.

## Restaurar o original

O `~/.local/share/myproX2/prox2_backup_perfis.json` guarda os setores de antes de qualquer alteração, ou seja, o original de fábrica/G Hub. Backups novos (`prox2.py backup`) cobrem os setores 0..15, incluindo as macros. Na restauração, macros vazias voltam como `ff` com CRC, e macros com CRC ruim no arquivo são puladas, com aviso de que não foram restauradas (use "Restaurar" no painel para voltar essas vagas ao padrão). Para voltar ao original:

```
python3 prox2.py restaurar ~/.local/share/myproX2/prox2_backup_perfis.json [--sim]
```

## Como foi feito

A engenharia reversa foi feita com a ajuda do [Claude Code](https://claude.com/claude-code). Ele leu e comparou os setores da memória interna, consultou as features HID++ do mouse e escreveu e revisou os scripts. Cada gravação foi conferida no mouse real, relendo o setor e medindo a taxa de pacotes.

## Licença

MIT, veja [LICENSE](LICENSE).

## Aviso legal

Projeto independente, sem afiliação, apoio ou endosso da Logitech. Logitech, PRO X 2 Superlight, Lightspeed e G HUB são marcas da Logitech. Todos os direitos sobre elas, sobre o hardware e sobre o firmware pertencem à Logitech.

Use por sua conta e risco. As ferramentas gravam na memória do mouse. Se precisar voltar atrás, use o backup e a restauração do `prox2.py`.
