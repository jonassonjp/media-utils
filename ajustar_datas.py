#!/usr/bin/env python3
import os
import sys
import re
import subprocess
import fnmatch
from datetime import datetime, timedelta

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
    
    # 1. Atualiza data de Modificação
    subprocess.run(["touch", "-t", formato_touch, caminho], check=True)
    # 2. Atualiza data de Criação (exclusivo macOS)
    subprocess.run(["setfile", "-d", formato_setfile, caminho], check=True)

def renomear_arquivo_por_data(caminho_completo, nova_dt):
    """Se o arquivo seguir o padrão, altera o nome dele para refletir a nova data/hora"""
    diretorio = os.path.dirname(caminho_completo)
    nome_antigo = os.path.basename(caminho_completo)
    
    padrao = re.compile(r"^IMG_\d{8}_\d{6}(.*)$")
    match = padrao.match(nome_antigo)
    
    if match:
        resto_do_nome = match.group(1)
        novo_prefixo = nova_dt.strftime("IMG_%Y%m%d_%H%M%S")
        novo_nome = f"{novo_prefixo}{resto_do_nome}"
        caminho_novo = os.path.join(diretorio, novo_nome)
        
        if nome_antigo != novo_nome:
            contador = 1
            while os.path.exists(caminho_novo):
                nome_base, extensao = os.path.splitext(novo_nome)
                caminho_novo = os.path.join(diretorio, f"{nome_base}_{contador}{extensao}")
                contador += 1
                
            os.rename(caminho_completo, caminho_novo)
            return os.path.basename(caminho_novo)
            
    return nome_antigo

def processar_arquivo(caminho, modo, valor_manual=None, deslocamento_horas=None, data_fixa_dma=None):
    nome_arquivo = os.path.basename(caminho)
    
    if modo == '1':
        dt = extrair_data_nome(nome_arquivo)
        if not dt:
            print(f"✗ Ignorado: Padrão de data não encontrado no nome de '{nome_arquivo}'")
            return False
    elif modo == '2':
        dt = valor_manual
    elif modo == '3':
        dt_atual = obter_data_criacao_mac(caminho)
        dt = dt_atual + timedelta(hours=deslocamento_horas)
    elif modo == '4':
        dt_sistema = obter_data_criacao_mac(caminho)
        dt = datetime(data_fixa_dma.year, data_fixa_dma.month, data_fixa_dma.day, 
                      dt_sistema.hour, dt_sistema.minute, dt_sistema.second)
    else:
        return False

    try:
        aplicar_datas(caminho, dt)
        nome_final = renomear_arquivo_por_data(caminho, dt)
        
        if nome_arquivo != nome_final:
            print(f"✓ Corrigido e Renomeado: {nome_arquivo} -> {nome_final}")
        else:
            print(f"✓ Corrigido: {nome_arquivo} -> {dt.strftime('%d/%m/%Y %H:%M:%S')}")
            
        return True
    except Exception as e:
        print(f"✗ Erro ao processar {nome_arquivo}: {e}")
        return False

def main():
    if len(sys.argv) < 2:
        print("Erro: Você precisa passar o caminho de um arquivo ou diretório como parâmetro.")
        print("\nComo usar no Terminal:")
        print("  python3 ajustar_datas.py /caminho/da/pasta_ou_arquivo")
        sys.exit(1)

    caminho_alvo = sys.argv[1].strip()

    if not os.path.exists(caminho_alvo):
        print(f"Erro: O caminho fornecido não existe: '{caminho_alvo}'")
        sys.exit(1)

    eh_diretorio = os.path.isdir(caminho_alvo)

    # Nova funcionalidade: Filtro por máscara/extensão
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
        print(f"Filtro ativo: {mascara}\n")

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
    print("4. Alterar apenas a DATA (Manter a HORA do sistema do Mac)")
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

    sucessos = 0
    total_arquivos = 0

    if eh_diretorio:
        for raiz, dirs, arquivos in os.walk(caminho_alvo):
            # Ignora os ocultos do Mac
            arquivos_validos = [a for a in arquivos if not a.startswith('.')]
            
            # Aplica o filtro da máscara (ex: *.dng)
            arquivos_filtrados = fnmatch.filter(arquivos_validos, mascara)
            
            for arquivo in arquivos_filtrados:
                total_arquivos += 1
                caminho_completo = os.path.join(raiz, arquivo)
                if processar_arquivo(caminho_completo, opcao, valor_manual, deslocamento_horas, data_fixa_dma):
                    sucessos += 1
    else:
        # Para arquivo único, verifica se ele passa na máscara caso o usuário tenha definido uma
        nome_arquivo_unico = os.path.basename(caminho_alvo)
        if fnmatch.fnmatch(nome_arquivo_unico, mascara):
            total_arquivos = 1
            if processar_arquivo(caminho_alvo, opcao, valor_manual, deslocamento_horas, data_fixa_dma):
                sucessos += 1
        else:
            print(f"O arquivo selecionado não corresponde ao filtro '{mascara}'.")

    print("\n" + "=" * 40)
    print("           PROCESSO CONCLUÍDO")
    print("=" * 40)
    print(f"Total de arquivos processados no filtro: {total_arquivos}")
    print(f"Arquivos atualizados com sucesso: {sucessos}")
    print("=" * 40)

if __name__ == "__main__":
    main()