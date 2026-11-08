#!/usr/bin/env python3
import os
import sys
import re
import shutil
import subprocess
import fnmatch
from collections import defaultdict
from datetime import datetime, timedelta

LIMITE_PREVIA = 20

def extrair_data_nome(arquivo):
    """Tenta extrair a data do padrão de nome IMG_YYYYMMDD_HHMMSS"""
    padrao = re.compile(r"IMG_(\d{8})_(\d{6})")
    match = padrao.search(arquivo)
    if match:
        data_str, hora_str = match.group(1), match.group(2)
        try:
            return datetime.strptime(f"{data_str}{hora_str}", "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None

def obter_data_criacao_mac(caminho):
    """Obtém a data de criação atual do arquivo no Mac via stat (Hora do Sistema)"""
    try:
        resultado = subprocess.run(["stat", "-f", "%B", caminho], capture_output=True, text=True, check=True)
        timestamp = int(resultado.stdout.strip())
        return datetime.fromtimestamp(timestamp)
    except Exception:
        return datetime.fromtimestamp(os.path.getmtime(caminho))

def aplicar_datas(caminho, dt):
    """Aplica a data e hora informada como data de Criação e Modificação no macOS"""
    formato_touch = dt.strftime("%Y%m%d%H%M.%S")
    formato_setfile = dt.strftime("%m/%d/%Y %H:%M:%S")

    # 1. Atualiza data de Criação (exclusivo macOS, requer Xcode Command Line Tools)
    subprocess.run(["SetFile", "-d", formato_setfile, caminho], check=True, capture_output=True, text=True)
    # 2. Atualiza data de Modificação POR ÚLTIMO: em volumes exFAT (cartões SD, discos
    #    externos) o SetFile redefine a modificação para a hora atual.
    subprocess.run(["touch", "-t", formato_touch, caminho], check=True, capture_output=True, text=True)

    # 3. Confere se a data de modificação foi gravada (tolerância de 2s do FAT32)
    if abs(os.path.getmtime(caminho) - dt.timestamp()) > 2:
        raise OSError("a data de modificação não foi gravada pelo sistema de arquivos")

def calcular_data(caminho, modo, valor_manual=None, deslocamento_horas=None, data_fixa_dma=None):
    """Calcula a nova data do arquivo conforme o modo. Retorna None se não for possível."""
    nome_arquivo = os.path.basename(caminho)

    if modo == '1':
        return extrair_data_nome(nome_arquivo)
    if modo == '2':
        return valor_manual
    if modo == '3':
        return obter_data_criacao_mac(caminho) + timedelta(hours=deslocamento_horas)
    if modo == '4':
        # Preserva a HORA original do arquivo, trocando apenas o dia/mês/ano.
        # Prioridade: hora gravada no NOME (IMG_YYYYMMDD_HHMMSS), que é a da captura.
        # Sem padrão no nome: usa a mais antiga entre criação e modificação, pois
        # cópias sem preservar metadados atualizam essas datas para a hora da cópia.
        dt_origem = extrair_data_nome(nome_arquivo)
        if not dt_origem:
            dt_criacao = obter_data_criacao_mac(caminho)
            dt_modificacao = datetime.fromtimestamp(os.path.getmtime(caminho))
            dt_origem = min(dt_criacao, dt_modificacao)
        return dt_origem.replace(year=data_fixa_dma.year, month=data_fixa_dma.month,
                                 day=data_fixa_dma.day)
    return None

def nome_desejado_por_data(nome_antigo, nova_dt):
    """Se o nome seguir o padrão, retorna o novo nome com a data/hora atualizada (ou None)"""
    match = re.match(r"^IMG_\d{8}_\d{6}(.*)$", nome_antigo)
    if not match:
        return None
    novo_nome = f"{nova_dt.strftime('IMG_%Y%m%d_%H%M%S')}{match.group(1)}"
    return novo_nome if novo_nome != nome_antigo else None

def adicionar_sufixo(nome, contador):
    nome_base, extensao = os.path.splitext(nome)
    return f"{nome_base}_{contador}{extensao}"

def resolver_nomes_finais(itens):
    """
    Define o nome final de cada arquivo a ser renomeado, considerando o lote todo.
    Os nomes atuais dos arquivos que serão renomeados ficam livres, então um arquivo
    pode assumir o nome antigo de outro do mesmo lote sem receber sufixo "_1".
    Comparação sem diferenciar maiúsculas (padrão do APFS no macOS).
    """
    por_diretorio = defaultdict(list)
    for item in itens:
        item['nome_final'] = None
        if item['nome_desejado']:
            por_diretorio[os.path.dirname(item['caminho'])].append(item)

    for diretorio, itens_dir in por_diretorio.items():
        saindo = {os.path.basename(i['caminho']).lower() for i in itens_dir}
        ocupados = {n.lower() for n in os.listdir(diretorio)} - saindo
        for item in itens_dir:
            candidato = item['nome_desejado']
            contador = 1
            while candidato.lower() in ocupados:
                candidato = adicionar_sufixo(item['nome_desejado'], contador)
                contador += 1
            ocupados.add(candidato.lower())
            item['nome_final'] = candidato

def renomear_sem_sobrescrever(origem, destino):
    """Renomeia garantindo que nenhum arquivo existente seja sobrescrito"""
    diretorio = os.path.dirname(destino)
    nome = os.path.basename(destino)
    candidato = destino
    contador = 1
    while os.path.exists(candidato):
        candidato = os.path.join(diretorio, adicionar_sufixo(nome, contador))
        contador += 1
    os.rename(origem, candidato)
    return candidato

def renomear_em_duas_fases(itens):
    """
    Fase 1: move cada arquivo para um nome temporário único.
    Fase 2: move do temporário para o nome final.
    Assim nenhum arquivo do lote colide com o nome antigo de outro.
    Retorna a lista de itens renomeados com sucesso.
    """
    temporarios = []
    for indice, item in enumerate(itens):
        diretorio = os.path.dirname(item['caminho'])
        temporario = os.path.join(diretorio, f".ajustar_datas_tmp_{os.getpid()}_{indice}")
        try:
            os.rename(item['caminho'], temporario)
            temporarios.append((item, temporario))
        except OSError as e:
            print(f"✗ Erro ao renomear {os.path.basename(item['caminho'])}: {e}")

    renomeados = []
    for item, temporario in temporarios:
        diretorio = os.path.dirname(item['caminho'])
        try:
            destino = renomear_sem_sobrescrever(temporario, os.path.join(diretorio, item['nome_final']))
            item['nome_final'] = os.path.basename(destino)
            renomeados.append(item)
        except OSError as e:
            # Tenta devolver o nome original para não deixar o arquivo com nome temporário
            try:
                renomear_sem_sobrescrever(temporario, item['caminho'])
            except OSError:
                print(f"  ATENÇÃO: arquivo ficou com nome temporário: {temporario}")
            print(f"✗ Erro ao renomear {os.path.basename(item['caminho'])}: {e}")
    return renomeados

def montar_plano(arquivos, modo, valor_manual, deslocamento_horas, data_fixa_dma):
    plano = []
    for caminho in arquivos:
        nome = os.path.basename(caminho)
        try:
            dt = calcular_data(caminho, modo, valor_manual, deslocamento_horas, data_fixa_dma)
        except (OSError, ValueError) as e:
            print(f"✗ Ignorado: não foi possível calcular a data de '{nome}': {e}")
            continue
        if not dt:
            print(f"✗ Ignorado: Padrão de data não encontrado no nome de '{nome}'")
            continue
        plano.append({'caminho': caminho, 'dt': dt, 'nome_desejado': nome_desejado_por_data(nome, dt)})
    resolver_nomes_finais(plano)
    return plano

def exibir_previa(plano, caminho_alvo):
    print("\n" + "=" * 60)
    print("  PRÉVIA DAS ALTERAÇÕES")
    print("=" * 60)
    for item in plano[:LIMITE_PREVIA]:
        nome = os.path.relpath(item['caminho'], caminho_alvo) if os.path.isdir(caminho_alvo) \
            else os.path.basename(item['caminho'])
        data = item['dt'].strftime('%d/%m/%Y %H:%M:%S')
        if item['nome_final']:
            print(f"  {nome} -> {item['nome_final']}  [{data}]")
        else:
            print(f"  {nome}  [{data}]")
    if len(plano) > LIMITE_PREVIA:
        print(f"  ... e mais {len(plano) - LIMITE_PREVIA} arquivo(s)")
    renomeacoes = sum(1 for i in plano if i['nome_final'])
    print("-" * 60)
    print(f"Arquivos com data alterada: {len(plano)} | Arquivos renomeados: {renomeacoes}")
    print("=" * 60)

def executar_plano(plano):
    # 1. Aplica as datas
    com_data_ok = []
    for item in plano:
        try:
            aplicar_datas(item['caminho'], item['dt'])
            com_data_ok.append(item)
        except subprocess.CalledProcessError as e:
            detalhe = (e.stderr or '').strip() or e
            print(f"✗ Erro ao processar {os.path.basename(item['caminho'])}: {detalhe}")
        except OSError as e:
            print(f"✗ Erro ao processar {os.path.basename(item['caminho'])}: {e}")

    # Se algum arquivo falhou, ele mantém o nome atual: recalcula os nomes finais
    if len(com_data_ok) != len(plano):
        resolver_nomes_finais(com_data_ok)

    # 2. Renomeia em duas fases
    a_renomear = [i for i in com_data_ok if i['nome_final']]
    renomeados = renomear_em_duas_fases(a_renomear)

    for item in com_data_ok:
        nome_antigo = os.path.basename(item['caminho'])
        if item in renomeados:
            print(f"✓ Corrigido e Renomeado: {nome_antigo} -> {item['nome_final']}")
        elif item not in a_renomear:
            print(f"✓ Corrigido: {nome_antigo} -> {item['dt'].strftime('%d/%m/%Y %H:%M:%S')}")
        else:
            print(f"⚠ Data corrigida, mas não renomeado: {nome_antigo}")

    return len(com_data_ok)

def listar_arquivos(caminho_alvo, mascara):
    if not os.path.isdir(caminho_alvo):
        return [caminho_alvo]

    mascara_minuscula = mascara.lower()
    arquivos_encontrados = []
    for raiz, dirs, arquivos in os.walk(caminho_alvo):
        # Não entra em pastas ocultas (.Trashes, .Spotlight-V100, .fseventsd...)
        dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
        for arquivo in sorted(arquivos):
            # Ignora os ocultos do Mac e aplica a máscara sem diferenciar maiúsculas
            if not arquivo.startswith('.') and fnmatch.fnmatch(arquivo.lower(), mascara_minuscula):
                arquivos_encontrados.append(os.path.join(raiz, arquivo))
    return arquivos_encontrados

def main():
    if len(sys.argv) < 2:
        print("Erro: Você precisa passar o caminho de um arquivo ou diretório como parâmetro.")
        print("\nComo usar no Terminal:")
        print("  python3 ajustar_datas.py /caminho/da/pasta_ou_arquivo")
        sys.exit(1)

    if not shutil.which("SetFile"):
        print("Erro: o comando 'SetFile' não foi encontrado.")
        print("Ele faz parte das Xcode Command Line Tools. Instale com:")
        print("  xcode-select --install")
        sys.exit(1)

    caminho_alvo = sys.argv[1].strip()

    if not os.path.exists(caminho_alvo):
        print(f"Erro: O caminho fornecido não existe: '{caminho_alvo}'")
        sys.exit(1)

    eh_diretorio = os.path.isdir(caminho_alvo)

    # Filtro por máscara/extensão
    mascara = "*"
    if eh_diretorio:
        print("=" * 60)
        print("  FILTRO DE ARQUIVOS")
        print("=" * 60)
        filtro_input = input("Deseja filtrar por extensão? (Ex: *.dng, *.insp ou deixe em branco para TODOS): ").strip()
        if filtro_input:
            # Caso o usuário digite apenas 'dng', transformamos em '*.dng'
            if not filtro_input.startswith('*'):
                if filtro_input.startswith('.'):
                    mascara = f"*{filtro_input}"
                else:
                    mascara = f"*.{filtro_input}"
            else:
                mascara = filtro_input
        print(f"Filtro ativo: {mascara} (sem diferenciar maiúsculas)\n")

    print("=" * 60)
    print("  GERENCIADOR E RENOMEADOR DE DATA/HORA (macOS)")
    print("=" * 60)
    print(f"Alvo selecionado: {caminho_alvo}")
    print("-" * 60)
    print("Escolha o modo de operação:")
    print("1. Extrair data/hora automaticamente do NOME do arquivo")
    if not eh_diretorio:
        print("2. Informar uma data e hora MANUALMENTE (atualiza sistema e nome)")
    else:
        print("2. [Indisponível para pastas] Informar uma data e hora MANUALMENTE")
    print("3. Aplicar um DESLOCAMENTO de horas (Ex: +1, -4)")
    print("4. Alterar apenas a DATA (Manter a HORA original do arquivo)")
    print("-" * 60)
    print("0. Sair (Não fazer nada)")
    print("=" * 60)

    opcao = input("Digite a opção desejada: ").strip()

    if opcao == '0':
        print("\nOperação cancelada pelo usuário. Saindo...")
        sys.exit(0)

    valor_manual = None
    deslocamento_horas = None
    data_fixa_dma = None

    if opcao == '1':
        print("\nModo: Extração automática pelo nome do arquivo.\n")
    elif opcao == '2':
        if eh_diretorio:
            print("Erro: A opção manual total só pode ser usada para um único arquivo.")
            sys.exit(1)
        while True:
            data_input = input("Digite a data/hora (Formato: DD/MM/AAAA HH:MM:SS): ").strip()
            try:
                valor_manual = datetime.strptime(data_input, "%d/%m/%Y %H:%M:%S")
                break
            except ValueError:
                print("Formato inválido! Tente novamente.")
    elif opcao == '3':
        while True:
            desloc_input = input("Digite o deslocamento de horas (Ex: +1, -3): ").strip()
            try:
                if  desloc_input.startswith('+'):
                    deslocamento_horas = int(desloc_input[1:])
                else:
                    deslocamento_horas = int(desloc_input)
                break
            except ValueError:
                print("Valor inválido! Digite um número inteiro.")
    elif opcao == '4':
        while True:
            data_input = input("Digite a nova data desejada (Formato: DD/MM/AAAA): ").strip()
            try:
                data_fixa_dma = datetime.strptime(data_input, "%d/%m/%Y")
                break
            except ValueError:
                print("Formato inválido! Use barras e 4 dígitos para o ano (Ex: 08/06/2026).")
    else:
        print("Opção inválida. Saindo.")
        sys.exit(1)

    arquivos = listar_arquivos(caminho_alvo, mascara)
    total_arquivos = len(arquivos)
    plano = montar_plano(arquivos, opcao, valor_manual, deslocamento_horas, data_fixa_dma)

    sucessos = 0
    if not plano:
        print("\nNenhum arquivo a alterar.")
    else:
        exibir_previa(plano, caminho_alvo)
        confirmacao = input("Confirmar as alterações? (s/N): ").strip().lower()
        if confirmacao in ('s', 'sim'):
            print()
            sucessos = executar_plano(plano)
        else:
            print("\nOperação cancelada. Nenhum arquivo foi alterado.")

    print("\n" + "=" * 40)
    print("           PROCESSO CONCLUÍDO")
    print("=" * 40)
    print(f"Total de arquivos processados no filtro: {total_arquivos}")
    print(f"Arquivos atualizados com sucesso: {sucessos}")
    print("=" * 40)

if __name__ == "__main__":
    main()
