#!/usr/bin/env python3
import os
import sys
import re
import json
import shutil
import signal
import subprocess
import fnmatch
from collections import defaultdict
from datetime import datetime, timedelta

LIMITE_PREVIA = 20

# Prefixos usados pelas câmeras Insta360 (foto, vídeo e vídeo de baixa resolução)
PREFIXOS = r"(?:IMG|VID|LRV)"

# Campos de data gravados pela câmera, em ordem de prioridade.
# Fotos (JPG/INSP/DNG) gravam a hora LOCAL da câmera; o DNG da Ace Pro 2 só tem IFD0:ModifyDate.
TAGS_FOTO = ["ExifIFD:DateTimeOriginal", "ExifIFD:CreateDate", "IFD0:ModifyDate"]
# Vídeos (MP4/INSV) gravam em UTC, conforme a especificação QuickTime.
TAG_VIDEO = "QuickTime:CreateDate"
# Fuso da câmera em relação ao UTC: diferença entre a hora das fotos e dos vídeos.
# Medido na Insta360 Ace Pro 2 (fotos = vídeos + 1h).
FUSO_CAMERA_PADRAO = 1

# Nome renomeável: PREFIXO_AAAAMMDD_HHMMSS seguido de "_", "." ou fim do nome.
# Aceita hora com 5 dígitos (nomes editados à mão, ex: IMG_20261108_09319_001.mp4).
PADRAO_NOME_RENOMEAVEL = re.compile(r"^(" + PREFIXOS + r")_\d{8}_\d{5,6}(?=[_.]|$)(.*)$")

def extrair_data_nome(arquivo):
    """Tenta extrair a data do padrão de nome IMG_YYYYMMDD_HHMMSS (ou VID_/LRV_)"""
    padrao = re.compile(PREFIXOS + r"_(\d{8})_(\d{6})")
    match = padrao.search(arquivo)
    if match:
        data_str, hora_str = match.group(1), match.group(2)
        try:
            return datetime.strptime(f"{data_str}{hora_str}", "%Y%m%d%H%M%S")
        except ValueError:
            return None
    return None

def obter_data_criacao_mac(caminho):
    """Obtém a data de criação atual do arquivo (na falta dela, a de modificação)"""
    info = os.stat(caminho)
    return datetime.fromtimestamp(getattr(info, "st_birthtime", info.st_mtime))

def aplicar_datas(caminho, dt):
    """Aplica a data e hora informada como data de Criação e Modificação no macOS"""
    formato_setfile = dt.strftime("%m/%d/%Y %H:%M:%S")

    # 1. Atualiza data de Criação (exclusivo macOS, requer Xcode Command Line Tools)
    subprocess.run(["SetFile", "-d", formato_setfile, caminho], check=True, capture_output=True, text=True)
    # 2. Atualiza data de Modificação POR ÚLTIMO: em volumes exFAT (cartões SD, discos
    #    externos) o SetFile redefine a modificação para a hora atual.
    timestamp = dt.timestamp()
    os.utime(caminho, (timestamp, timestamp))

    # 3. Confere se a data de modificação foi gravada (tolerância de 2s do FAT32)
    if abs(os.path.getmtime(caminho) - dt.timestamp()) > 2:
        raise OSError("a data de modificação não foi gravada pelo sistema de arquivos")

def converter_data_exif(valor):
    """Converte 'AAAA:MM:DD HH:MM:SS[...]' em datetime (None se vazio ou zerado)"""
    try:
        return datetime.strptime(str(valor)[:19], "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None

def ler_metadados(caminhos):
    """
    Lê com o exiftool a data gravada pela câmera em cada arquivo.
    Retorna {caminho: (datetime, eh_video)}; arquivos sem data ficam de fora.
    """
    if not caminhos:
        return {}
    comando = ["exiftool", "-json", "-G1", "-q", "-q", "-charset", "filename=utf8"]
    comando += [f"-{tag}" for tag in TAGS_FOTO + [TAG_VIDEO]]
    comando += ["-@", "-"]  # lista de arquivos pela entrada padrão
    resultado = subprocess.run(comando, input="\n".join(caminhos), capture_output=True, text=True)
    try:
        itens = json.loads(resultado.stdout or "[]")
    except json.JSONDecodeError:
        print(f"Erro ao ler a saída do exiftool: {resultado.stderr.strip()}")
        return {}

    metadados = {}
    for item in itens:
        caminho = item.get("SourceFile")
        for tag in TAGS_FOTO:
            dt = converter_data_exif(item.get(tag, ""))
            if dt:
                metadados[caminho] = (dt, False)
                break
        else:
            dt = converter_data_exif(item.get(TAG_VIDEO, ""))
            if dt:
                metadados[caminho] = (dt, True)
    return metadados

def hora_camera(info, fuso_camera):
    """Hora no relógio da câmera: vídeos (UTC) recebem o fuso para ficarem iguais às fotos"""
    dt, eh_video = info
    return dt + timedelta(hours=fuso_camera) if eh_video else dt

def formatar_correcao(delta):
    sinal = "-" if delta < timedelta(0) else "+"
    total = abs(int(delta.total_seconds()))
    dias, resto = divmod(total, 86400)
    horas, resto = divmod(resto, 3600)
    minutos, segundos = divmod(resto, 60)
    return f"{sinal}{dias} dia(s) {horas:02d}:{minutos:02d}:{segundos:02d}"

def calcular_data(caminho, modo, parametros):
    """Calcula a nova data do arquivo conforme o modo. Retorna None se não for possível."""
    nome_arquivo = os.path.basename(caminho)

    if modo == '1':
        return extrair_data_nome(nome_arquivo)
    if modo == '2':
        return parametros['valor_manual']
    if modo == '3':
        return obter_data_criacao_mac(caminho) + timedelta(hours=parametros['deslocamento_horas'])
    if modo == '5':
        info = parametros['metadados'].get(caminho)
        if not info:
            return None
        return hora_camera(info, parametros['fuso_camera']) + parametros['correcao']
    if modo == '4':
        data_fixa_dma = parametros['data_fixa_dma']
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
    """
    Se o nome seguir o padrão, retorna o novo nome com a data/hora atualizada (ou None).
    Hora com 5 dígitos é substituída pela hora correta com 6 dígitos.
    """
    match = PADRAO_NOME_RENOMEAVEL.match(nome_antigo)
    if not match:
        return None
    novo_nome = f"{match.group(1)}_{nova_dt.strftime('%Y%m%d_%H%M%S')}{match.group(2)}"
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

def montar_plano(arquivos, modo, parametros):
    plano = []
    for caminho in arquivos:
        nome = os.path.basename(caminho)
        try:
            dt = calcular_data(caminho, modo, parametros)
        except (OSError, ValueError) as e:
            print(f"✗ Ignorado: não foi possível calcular a data de '{nome}': {e}")
            continue
        if not dt:
            if modo == '5':
                print(f"✗ Ignorado: Data não encontrada nos metadados de '{nome}'")
            else:
                print(f"✗ Ignorado: Padrão de data não encontrado no nome de '{nome}'")
            continue
        plano.append({'caminho': caminho, 'dt': dt, 'nome_desejado': nome_desejado_por_data(nome, dt),
                      'fora_do_padrao': not PADRAO_NOME_RENOMEAVEL.match(nome)})
    resolver_nomes_finais(plano)
    return plano

def exibir_previa(plano, caminho_alvo, modo):
    print("\n" + "=" * 60)
    print("  PRÉVIA DAS ALTERAÇÕES")
    print("=" * 60)
    for item in plano[:LIMITE_PREVIA]:
        nome = os.path.relpath(item['caminho'], caminho_alvo) if os.path.isdir(caminho_alvo) \
            else os.path.basename(item['caminho'])
        data = item['dt'].strftime('%d/%m/%Y %H:%M:%S')
        if item['nome_final']:
            print(f"  {nome} -> {item['nome_final']}  [{data}]")
        elif item['fora_do_padrao'] and modo != '1':
            print(f"  {nome}  [{data}]  (nome fora do padrão: não será renomeado)")
        else:
            print(f"  {nome}  [{data}]")
    if len(plano) > LIMITE_PREVIA:
        print(f"  ... e mais {len(plano) - LIMITE_PREVIA} arquivo(s)")
    renomeacoes = sum(1 for i in plano if i['nome_final'])
    print("-" * 60)
    print(f"Arquivos com data alterada: {len(plano)} | Arquivos renomeados: {renomeacoes}")
    fora_do_padrao = sum(1 for i in plano if i['fora_do_padrao'])
    if fora_do_padrao and modo != '1':
        print(f"⚠ {fora_do_padrao} arquivo(s) com nome fora do padrão PREFIXO_AAAAMMDD_HHMMSS: "
              "a data será ajustada, mas o nome não será alterado.")
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

def configurar_modo_metadados(arquivos):
    """
    Modo 5: lê as datas gravadas pela câmera e calcula a correção do relógio a partir
    da data/hora REAL de um arquivo de referência (o mais antigo do lote).
    """
    if not shutil.which("exiftool"):
        print("Erro: o comando 'exiftool' não foi encontrado. Instale com:")
        print("  brew install exiftool")
        sys.exit(1)

    print(f"\nLendo metadados de {len(arquivos)} arquivo(s)...")
    metadados = ler_metadados(arquivos)
    if not metadados:
        print("Nenhum arquivo com data nos metadados. Saindo.")
        sys.exit(1)

    qtd_videos = sum(1 for _, eh_video in metadados.values() if eh_video)
    qtd_fotos = len(metadados) - qtd_videos
    print(f"Datas encontradas: {qtd_fotos} foto(s), {qtd_videos} vídeo(s).")

    fuso_camera = 0
    if qtd_videos and qtd_fotos:
        print("\nVídeos gravam a hora em UTC e fotos na hora local da câmera.")
        print(f"Na Insta360 Ace Pro 2 a diferença medida foi de {FUSO_CAMERA_PADRAO:+d}h.")
        while True:
            fuso_input = input(f"Fuso da câmera em horas (Enter = {FUSO_CAMERA_PADRAO:+d}): ").strip()
            if not fuso_input:
                fuso_camera = FUSO_CAMERA_PADRAO
                break
            try:
                fuso_camera = int(fuso_input)
                break
            except ValueError:
                print("Valor inválido! Digite um número inteiro (Ex: +1, -3).")

    referencia = min(metadados, key=lambda c: hora_camera(metadados[c], fuso_camera))
    dt_ref_camera = hora_camera(metadados[referencia], fuso_camera)
    dt_ref_nome = extrair_data_nome(os.path.basename(referencia))

    print("\nArquivo de referência (o mais antigo do lote):")
    print(f"  {os.path.basename(referencia)}")
    print(f"  Hora no relógio da câmera: {dt_ref_camera.strftime('%d/%m/%Y %H:%M:%S')}")
    dica = ""
    if dt_ref_nome and dt_ref_nome != dt_ref_camera:
        dica = f" ou Enter para usar a do nome ({dt_ref_nome.strftime('%d/%m/%Y %H:%M:%S')})"
    while True:
        data_input = input(f"Digite a data/hora REAL deste arquivo (DD/MM/AAAA HH:MM:SS){dica}: ").strip()
        if not data_input and dica:
            dt_ref_real = dt_ref_nome
            break
        try:
            dt_ref_real = datetime.strptime(data_input, "%d/%m/%Y %H:%M:%S")
            break
        except ValueError:
            print("Formato inválido! Tente novamente.")

    correcao = dt_ref_real - dt_ref_camera
    print(f"Correção do relógio aplicada a todos os arquivos: {formatar_correcao(correcao)}")
    return {'metadados': metadados, 'fuso_camera': fuso_camera, 'correcao': correcao}

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

    # Usa o caminho exato; só remove espaços/quebras das pontas se o exato não existir
    # (nomes de pasta podem terminar com espaço)
    caminho_alvo = sys.argv[1]
    if not os.path.exists(caminho_alvo) and os.path.exists(caminho_alvo.strip()):
        caminho_alvo = caminho_alvo.strip()

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
    print("5. Usar a data dos METADADOS da câmera + correção do relógio (requer exiftool)")
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
    parametros = {}

    arquivos = listar_arquivos(caminho_alvo, mascara)

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
                deslocamento_horas = int(desloc_input)  # int() já aceita "+1" e "-3"
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
    elif opcao == '5':
        parametros.update(configurar_modo_metadados(arquivos))
    else:
        print("Opção inválida. Saindo.")
        sys.exit(1)

    parametros.update(valor_manual=valor_manual, deslocamento_horas=deslocamento_horas,
                      data_fixa_dma=data_fixa_dma)
    total_arquivos = len(arquivos)
    plano = montar_plano(arquivos, opcao, parametros)

    sucessos = 0
    if not plano:
        print("\nNenhum arquivo a alterar.")
    else:
        exibir_previa(plano, caminho_alvo, opcao)
        confirmacao = input("Confirmar as alterações? (s/N): ").strip().lower()
        if confirmacao in ('s', 'sim'):
            print()
            # Ctrl+C no meio da renomeação deixaria arquivos com nome temporário
            sigint_anterior = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                sucessos = executar_plano(plano)
            finally:
                signal.signal(signal.SIGINT, sigint_anterior)
        else:
            print("\nOperação cancelada. Nenhum arquivo foi alterado.")

    print("\n" + "=" * 40)
    print("           PROCESSO CONCLUÍDO")
    print("=" * 40)
    print(f"Total de arquivos processados no filtro: {total_arquivos}")
    print(f"Arquivos atualizados com sucesso: {sucessos}")
    print("=" * 40)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\n\nOperação interrompida. Nenhum arquivo foi alterado.")
        sys.exit(130)
