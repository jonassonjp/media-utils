# Gerenciador e Renomeador de Data/Hora (macOS)

Script em Python para corrigir, em lote, as datas de **Criação** e **Modificação** de fotos e vídeos (câmeras Insta360, drones FPV, DSLRs) no sistema de arquivos do macOS. Também mantém o nome do arquivo sincronizado com a data quando ele segue o padrão cronológico das câmeras (`IMG_AAAAMMDD_HHMMSS...`).

Resolve problemas comuns como:

- arquivos mostrando horas a mais ou a menos no Finder (fuso horário);
- câmera com o relógio errado (ex: fotos datadas de 2018 por falta de configuração);
- data de modificação igual ao dia em que os arquivos foram copiados.

> ⚠️ O script altera **apenas as datas do sistema de arquivos e o nome**. Os metadados internos (EXIF das fotos, data dos vídeos) **não são modificados** — apps como Fotos e Lightroom continuam lendo a data gravada pela câmera.

---

## 📋 Pré-requisitos

| Requisito | Para quê | Instalação |
|---|---|---|
| **macOS** | Datas de criação são um recurso do macOS | — |
| **Python 3** | Executar o script | Já vem com as Xcode Command Line Tools |
| **SetFile** | Alterar a data de criação | `xcode-select --install` |
| **exiftool** *(opcional)* | Apenas para o modo 5 | `brew install exiftool` |

O script verifica se o `SetFile` está instalado antes de começar.

---

## 🔧 Como usar

No **Terminal**, passe o caminho da pasta ou do arquivo:

```bash
python3 ajustar_datas.py /caminho/da/pasta_ou_arquivo
```

> 💡 Dica: arraste a pasta do Finder para a janela do Terminal para colar o caminho. Alguns volumes (como cartões Insta360) têm caracteres invisíveis no nome e digitar o caminho à mão resulta em "No such file or directory".

O fluxo é interativo:

1. **Filtro de extensão** (só para pastas): ex. `dng`, `.insp` ou `*.mp4`. Em branco processa todos. Não diferencia maiúsculas (`dng` encontra `.DNG`).
2. **Escolha do modo** (veja abaixo).
3. **Prévia** das alterações: nome atual → nome novo e a data que será aplicada.
4. **Confirmação** (`s/N`). Nada é alterado se você não confirmar.

Pastas são processadas **recursivamente**. Arquivos e pastas ocultos (`.Trashes`, `.Spotlight-V100`, `._*` etc.) são ignorados.

---

## 🚀 Modos de operação

| Modo | O que faz | Indicado para |
|---|---|---|
| **1. Data pelo nome** | Lê `IMG_/VID_/LRV_AAAAMMDD_HHMMSS` do nome e aplica nas datas do arquivo. Não renomeia. | Arquivos com nome correto mas datas erradas no Finder |
| **2. Data manual** | Aplica uma data/hora informada (`DD/MM/AAAA HH:MM:SS`). Só para um arquivo. | Correções pontuais |
| **3. Deslocamento de horas** | Soma ou subtrai horas (`+1`, `-4`). A base pode ser a data de criação atual ou a hora do nome. | Erros de fuso horário |
| **4. Só a data** | Troca dia/mês/ano mantendo a hora original. A hora vem do nome; sem padrão no nome, da mais antiga entre criação e modificação. | Câmera com a data errada mas a hora certa |
| **5. Metadados da câmera** | Lê a data gravada dentro do arquivo (EXIF/vídeo) e aplica uma correção calculada a partir da hora real de um arquivo de referência. | Câmera com o relógio errado |
| **6. Desfazer** | Restaura nomes e datas originais da última execução na pasta. Pode ser repetido para voltar várias execuções. | Desfazer um engano |

Nos modos 2 a 5, se o nome seguir o padrão, ele é **renomeado** para a nova data, preservando o prefixo e o sufixo (ex: `_00_025.insp`). Nomes com hora de 5 dígitos (editados à mão, como `IMG_20261108_09319_001.mp4`) também são corrigidos.

### Modo 5 em detalhe

Útil quando o relógio da câmera estava errado: os nomes e os metadados ficam com uma data incorreta, mas a **diferença** entre o relógio da câmera e a hora real é a mesma para todos os arquivos.

1. O script lê a data gravada pela câmera:
   - **Fotos** (JPG, INSP, DNG): `DateTimeOriginal`, `CreateDate` ou `ModifyDate` — hora local da câmera.
   - **Vídeos** (MP4, INSV): `QuickTime:CreateDate` — gravada em **UTC**.
2. Se o lote tiver fotos **e** vídeos, pergunta o **fuso da câmera** para alinhar os dois. Na Insta360 Ace Pro 2 o valor medido foi **+1h** (padrão ao apertar Enter).
3. Sugere o arquivo mais antigo do lote como **referência** (Enter aceita, ou digite o nome de outro arquivo) e pede a **data/hora real** dele. Se o nome já tiver uma data diferente da câmera, Enter usa a do nome.
4. Calcula a correção (ex: `+2959 dia(s) 08:00:00`) e aplica a todos os arquivos.

**Exemplo:** câmera marcando 02/10/2018 01:32:01 numa foto tirada em 08/11/2026 09:32:01:

```
IMG_20181002_013201_003.dng -> IMG_20261108_093201_003.dng  [08/11/2026 09:32:01]
VID_20181002_020751_015.mp4 -> VID_20261108_110751_015.mp4  [08/11/2026 11:07:51]
```

---

## 🛡️ Segurança

- **Prévia e confirmação** antes de qualquer alteração.
- **Desfazer:** cada execução grava o nome e as datas originais no arquivo oculto `.ajustar_datas_historico.json`, na pasta processada. O modo 6 restaura a última execução (e pode ser repetido). Os caminhos são relativos, então funciona mesmo que o cartão seja montado com outro nome. Não apague esse arquivo se quiser poder desfazer.
- **Ctrl+C** durante as perguntas sai sem alterar nada; durante a execução é ignorado para não deixar arquivos pela metade.
- **Nenhum arquivo é sobrescrito.** Os nomes novos são calculados para o lote inteiro e a renomeação é feita em duas etapas (via nomes temporários), então um arquivo pode assumir o nome antigo de outro sem conflito. Se o nome de destino já pertencer a um arquivo fora do lote, é adicionado um sufixo `_1`, `_2`…
- Após gravar, o script **confere** se a data de modificação foi realmente aplicada e reporta erro caso contrário.

---

## ⚠️ Observações

- **Cartões SD e discos externos (exFAT/FAT32):** o `SetFile` redefine a data de modificação para a hora atual nesses formatos. O script grava a modificação por último para contornar isso. Em FAT32 as datas têm precisão de 2 segundos.
- **Data da pasta:** renomear arquivos altera a data de modificação da **pasta** que os contém. Isso é normal.
- **Data de alteração (ctime):** exibida pelo `ls -lc` e pelo ExifTool como "File Inode Change Date", é sempre a hora da execução — o macOS não permite alterá-la.
- **Modo 3 é cumulativo:** rodar duas vezes aplica o deslocamento duas vezes. Use o modo 6 se isso acontecer.
- **Acerte o relógio da câmera** para evitar o problema nas próximas gravações.
