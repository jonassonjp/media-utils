readme_content = r'''# Gerenciador e Renomeador de Data/Hora (macOS)

Este script em Python foi desenvolvido para corrigir e automatizar a alteração em lote das datas de **Criação** e **Modificação** de arquivos (como fotos de câmeras Insta360, drones FPV ou DSLRs) no sistema de arquivos do macOS. Além disso, ele é capaz de sincronizar o nome físico do arquivo caso este siga o padrão cronológico de capturas.

O utilitário resolve problemas comuns de fuso horário (ex: arquivos mostrando 3 ou 4 horas a menos no Finder) de forma seletiva e interativa.

---

## 🚀 Funcionalidades

1. **Extração Automática pelo Nome:** Lê o padrão `IMG_YYYYMMDD_HHMMSS` do nome do arquivo e aplica essa data exata nos atributos internos do sistema do Mac.
2. **Entrada Manual:** Permite definir uma data e hora fixa específica (exclusivo para arquivos individuais).
3. **Deslocamento de Fuso Horário:** Soma ou subtrai horas (ex: `+1`, `-4`) tomando como base o horário atual exibido pelo Mac.
4. **Alteração Apenas de Data (Mantendo Hora):** Altera o Dia/Mês/Ano para uma pasta inteira, mas preserva os minutos e segundos originais de cada arquivo baseando-se no relógio do sistema.
5. **Filtro por Máscaras:** Permite isolar e processar apenas extensões específicas dentro de um diretório misto (ex: processar apenas arquivos `*.dng` ou `*.insp`).
6. **Renomeação Dinâmica:** Sempre que uma data é alterada (modos 2, 3 ou 4), o script atualiza o texto do nome do arquivo (mantendo sufixos e sequenciais como `_00_025.insp`) para manter tudo em perfeita sincronia.

---

## 📋 Pré-requisitos

* **Sistema Operacional:** macOS (utiliza ferramentas nativas como `setfile` e `touch`).
* **Python 3** instalado.

---

## 🔧 Como Utilizar

Abra o seu **Terminal** e execute o script passando o caminho da pasta ou do arquivo que deseja modificar como parâmetro:

```bash
python3 ajustar_datas.py /caminho/da/sua/pasta_ou_arquivo