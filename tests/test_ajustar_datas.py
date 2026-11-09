"""
Testes do ajustar_datas.py.

Executar na raiz do repositório:
    python3 -m unittest discover -s tests -v
"""
import io
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import zlib
from contextlib import redirect_stdout
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import ajustar_datas as ad  # noqa: E402

TEM_SETFILE = shutil.which("SetFile") is not None
TEM_EXIFTOOL = shutil.which("exiftool") is not None
TEM_SIPS = shutil.which("sips") is not None


def dt(texto):
    return datetime.strptime(texto, "%d/%m/%Y %H:%M:%S")


def executar_main(*argv):
    """Executa o main com argumentos, sem entrada interativa, e devolve a saída"""
    saida = io.StringIO()
    with redirect_stdout(saida):
        ad.main(list(argv))
    return saida.getvalue()


def datas_do_arquivo(caminho):
    info = os.stat(caminho)
    return (datetime.fromtimestamp(int(info.st_birthtime)), datetime.fromtimestamp(int(info.st_mtime)))


def definir_datas(caminho, criacao, modificacao):
    subprocess.run(["SetFile", "-d", criacao.strftime("%m/%d/%Y %H:%M:%S"), caminho], check=True)
    os.utime(caminho, (modificacao.timestamp(), modificacao.timestamp()))


class TesteNomes(unittest.TestCase):
    def test_extrair_data_nome_prefixos(self):
        for nome in ("IMG_20240115_103045_00_001.insp", "VID_20240115_103045.mp4",
                     "LRV_20240115_103045_01_002.lrv", "copia_IMG_20240115_103045.jpg"):
            self.assertEqual(ad.extrair_data_nome(nome), dt("15/01/2024 10:30:45"), nome)

    def test_extrair_data_nome_invalido(self):
        self.assertIsNone(ad.extrair_data_nome("foto.jpg"))
        self.assertIsNone(ad.extrair_data_nome("IMG_20241315_103045.jpg"))  # mês 13
        self.assertIsNone(ad.extrair_data_nome("IMG_20261108_09319_001.mp4"))  # hora com 5 dígitos

    def test_nome_desejado_preserva_sufixo(self):
        self.assertEqual(ad.nome_desejado_por_data("IMG_20240115_103045_00_025.insp", dt("16/01/2024 08:00:00")),
                         "IMG_20240116_080000_00_025.insp")

    def test_nome_desejado_sem_mudanca(self):
        self.assertIsNone(ad.nome_desejado_por_data("IMG_20240115_103045.jpg", dt("15/01/2024 10:30:45")))

    def test_nome_desejado_hora_5_digitos(self):
        self.assertEqual(ad.nome_desejado_por_data("IMG_20261108_09319_001.mp4", dt("08/11/2026 09:31:19")),
                         "IMG_20261108_093119_001.mp4")

    def test_nome_desejado_prefixo_vid_so_em_video(self):
        data = dt("08/11/2026 09:31:19")
        self.assertEqual(ad.nome_desejado_por_data("IMG_20261108_093119_001.mp4", data, True),
                         "VID_20261108_093119_001.mp4")
        self.assertIsNone(ad.nome_desejado_por_data("IMG_20261108_093119_001.jpg", data, True))

    def test_nome_fora_do_padrao(self):
        self.assertIsNone(ad.nome_desejado_por_data("foto.jpg", dt("15/01/2024 10:30:45")))
        self.assertIsNone(ad.nome_desejado_por_data("IMG_20240115_1030455.jpg", dt("15/01/2024 10:30:45")))

    def test_normalizar_mascara(self):
        self.assertEqual(ad.normalizar_mascara(""), "*")
        self.assertEqual(ad.normalizar_mascara("dng"), "*.dng")
        self.assertEqual(ad.normalizar_mascara(".dng"), "*.dng")
        self.assertEqual(ad.normalizar_mascara("*.DNG"), "*.DNG")

    def test_formatar_correcao(self):
        self.assertEqual(ad.formatar_correcao(timedelta(days=2959, hours=8)), "+2959 dia(s) 08:00:00")
        self.assertEqual(ad.formatar_correcao(timedelta(hours=-3, seconds=-5)), "-0 dia(s) 03:00:05")


class TesteArquivos(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.pasta)

    def criar(self, *nomes):
        caminhos = []
        for nome in nomes:
            caminho = os.path.join(self.pasta, nome)
            os.makedirs(os.path.dirname(caminho), exist_ok=True)
            with open(caminho, "w") as f:
                f.write(nome)  # conteúdo = nome original, para rastrear renomeações
            caminhos.append(caminho)
        return caminhos

    def conteudo(self, nome):
        with open(os.path.join(self.pasta, nome)) as f:
            return f.read()

    def test_listar_arquivos_filtro_e_ocultos(self):
        self.criar("a.DNG", "b.jpg", ".oculto.dng", ".Trashes/c.dng", "sub/d.dng")
        nomes = [os.path.relpath(c, self.pasta) for c in ad.listar_arquivos(self.pasta, "*.dng")]
        self.assertEqual(nomes, ["a.DNG", "sub/d.dng"])

    def test_resolver_nomes_cascata_sem_sufixo(self):
        a, b = self.criar("IMG_20240115_100000_001.jpg", "IMG_20240115_110000_002.jpg")
        itens = [{'caminho': a, 'nome_desejado': "IMG_20240115_110000_002.jpg"},
                 {'caminho': b, 'nome_desejado': "IMG_20240115_120000_002.jpg"}]
        ad.resolver_nomes_finais(itens)
        self.assertEqual([i['nome_final'] for i in itens],
                         ["IMG_20240115_110000_002.jpg", "IMG_20240115_120000_002.jpg"])

    def test_resolver_nomes_colisao_com_arquivo_fora_do_lote(self):
        a, _ = self.criar("IMG_20240115_100000.jpg", "img_20240115_110000.JPG")
        itens = [{'caminho': a, 'nome_desejado': "IMG_20240115_110000.jpg"}]
        ad.resolver_nomes_finais(itens)  # colisão sem diferenciar maiúsculas
        self.assertEqual(itens[0]['nome_final'], "IMG_20240115_110000_1.jpg")

    def test_renomear_em_duas_fases_troca_nomes(self):
        a, b = self.criar("X.jpg", "Y.jpg")
        itens = [{'caminho': a, 'nome_final': "Y.jpg"}, {'caminho': b, 'nome_final': "X.jpg"}]
        renomeados = ad.renomear_em_duas_fases(itens)
        self.assertEqual(len(renomeados), 2)
        self.assertEqual(self.conteudo("Y.jpg"), "X.jpg")
        self.assertEqual(self.conteudo("X.jpg"), "Y.jpg")
        self.assertEqual(sorted(os.listdir(self.pasta)), ["X.jpg", "Y.jpg"])

    def test_calcular_data_modos(self):
        (caminho,) = self.criar("IMG_20240115_103045_001.jpg")
        nome_base = {'base_nome': True, 'deslocamento_horas': -3}
        self.assertEqual(ad.calcular_data(caminho, '1', {}), dt("15/01/2024 10:30:45"))
        self.assertEqual(ad.calcular_data(caminho, '3', nome_base), dt("15/01/2024 07:30:45"))
        self.assertEqual(ad.calcular_data(caminho, '4', {'data_fixa_dma': dt("20/03/2024 00:00:00")}),
                         dt("20/03/2024 10:30:45"))
        meta = {'metadados': {caminho: (dt("02/10/2018 00:30:45"), True)}, 'fuso_camera': 1,
                'correcao': timedelta(days=2959, hours=8)}
        self.assertEqual(ad.calcular_data(caminho, '5', meta), dt("08/11/2026 09:30:45"))

    def test_historico_ida_e_volta(self):
        (caminho,) = self.criar("IMG_20240115_103045.jpg")
        item = {'caminho': caminho, 'nome_final': "IMG_20240115_113045.jpg", 'renomeado': True,
                'original': {'criacao': 1.0, 'modificacao': 2.0}, 'metadados_original': {"IFD0:ModifyDate": None}}
        with redirect_stdout(io.StringIO()):
            ad.registrar_execucao(self.pasta, '3', [item])
        execucoes = ad.carregar_historico(self.pasta)
        self.assertEqual(execucoes[0]['arquivos'][0],
                         {'arquivo': "IMG_20240115_103045.jpg", 'nome_novo': "IMG_20240115_113045.jpg",
                          'criacao': 1.0, 'modificacao': 2.0, 'metadados': {"IFD0:ModifyDate": None}})
        ad.salvar_historico(self.pasta, [])
        self.assertFalse(os.path.exists(os.path.join(self.pasta, ad.ARQUIVO_HISTORICO)))


class TesteFuso(unittest.TestCase):
    # Dados reais do cartão Insta360 Ace Pro 2: fotos em hora local, vídeos em UTC (+1h)
    METADADOS = {
        "IMG_20181002_013119_001.mp4": (dt("02/10/2018 00:31:19"), True),
        "IMG_20181002_013202_003.jpg": (dt("02/10/2018 01:32:02"), False),
        "IMG_20181002_013205_004.dng": (dt("02/10/2018 01:32:05"), False),
        "IMG_20181002_013403_005.mp4": (dt("02/10/2018 00:34:03"), True),
        "IMG_20181002_013446_006.dng": (dt("02/10/2018 01:34:46"), False),
        "IMG_20181002_021559_011.jpg": (dt("02/10/2018 02:15:59"), False),
        "IMG_20181002_021603_012.mp4": (dt("02/10/2018 01:16:03"), True),
        "IMG_20181002_021706_013.dng": (dt("02/10/2018 02:17:06"), False),
    }

    def test_detecta_fuso(self):
        self.assertEqual(ad.detectar_fuso_camera(self.METADADOS), 1)

    def test_sem_videos(self):
        fotos = {k: v for k, v in self.METADADOS.items() if not v[1]}
        self.assertIsNone(ad.detectar_fuso_camera(fotos))

    def test_ambiguo(self):
        # Fotos e vídeos com horas muito distantes: vários fusos servem
        ambiguo = {"IMG_1_001.jpg": (dt("01/01/2020 01:00:00"), False),
                   "IMG_1_002.mp4": (dt("01/01/2020 20:00:00"), True)}
        self.assertIsNone(ad.detectar_fuso_camera(ambiguo))


class TesteValoresInternos(unittest.TestCase):
    def setUp(self):
        self.tz_anterior = os.environ.get("TZ")
        os.environ["TZ"] = "America/Sao_Paulo"
        time.tzset()

    def tearDown(self):
        if self.tz_anterior is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.tz_anterior
        time.tzset()

    def test_foto_hora_local(self):
        valores = ad.novos_valores_internos("a.jpg", dt("08/11/2026 09:32:02"), {})
        self.assertEqual(set(valores.values()), {"2026:11:08 09:32:02"})
        self.assertEqual(set(valores), set(ad.TAGS_FOTO))

    def test_video_utc_e_campo_com_fuso(self):
        originais = {"QuickTime:CreateDate": "2018:10:02 00:34:03",
                     "Keys:CreationDate": "2018:10:02 01:34:03+01:00"}
        valores = ad.novos_valores_internos("a.mp4", dt("08/11/2026 09:34:03"), originais)
        self.assertEqual(valores["QuickTime:CreateDate"], "2026:11:08 12:34:03")
        self.assertEqual(valores["Keys:CreationDate"], "2026:11:08 09:34:03-03:00")


class TesteArgumentos(unittest.TestCase):
    def test_deslocamento_negativo_e_flags(self):
        args = ad.criar_parser().parse_args(["pasta", "--modo", "3", "--deslocamento", "-3", "--sem-vid"])
        self.assertEqual(args.deslocamento, -3)
        self.assertIs(args.prefixo_vid, False)
        self.assertIsNone(args.metadados)


@unittest.skipUnless(TEM_SETFILE, "requer SetFile (xcode-select --install)")
class TesteIntegracao(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.pasta)

    def test_deslocamento_e_desfazer(self):
        nomes = ["IMG_20240115_100000_001.jpg", "IMG_20240115_110000_002.jpg", "foto.jpg"]
        criacao, modificacao = dt("15/01/2024 09:00:00"), dt("01/02/2024 12:34:56")
        for nome in nomes:
            caminho = os.path.join(self.pasta, nome)
            open(caminho, "w").close()
            definir_datas(caminho, criacao, modificacao)

        executar_main(self.pasta, "--modo", "3", "--base", "nome", "--deslocamento", "+1",
                      "--filtro", "*", "--sem-metadados", "--sim")
        self.assertEqual(sorted(n for n in os.listdir(self.pasta) if not n.startswith(".")),
                         ["IMG_20240115_110000_001.jpg", "IMG_20240115_120000_002.jpg", "foto.jpg"])
        self.assertEqual(datas_do_arquivo(os.path.join(self.pasta, "IMG_20240115_120000_002.jpg")),
                         (dt("15/01/2024 12:00:00"),) * 2)

        executar_main(self.pasta, "--modo", "6", "--sim")
        self.assertEqual(sorted(os.listdir(self.pasta)), sorted(nomes))  # histórico removido
        for nome in nomes:
            self.assertEqual(datas_do_arquivo(os.path.join(self.pasta, nome)), (criacao, modificacao))

    def test_dry_run_nao_altera(self):
        caminho = os.path.join(self.pasta, "IMG_20240115_100000.jpg")
        open(caminho, "w").close()
        antes = datas_do_arquivo(caminho)
        saida = executar_main(self.pasta, "--modo", "3", "--deslocamento", "5", "--base", "nome",
                              "--filtro", "*", "--sem-metadados", "--dry-run")
        self.assertIn("--dry-run", saida)
        self.assertEqual(os.listdir(self.pasta), ["IMG_20240115_100000.jpg"])
        self.assertEqual(datas_do_arquivo(caminho), antes)


def criar_jpeg(caminho):
    """Gera um JPEG mínimo: PNG 1x1 escrito à mão e convertido pelo sips"""
    def bloco(tipo, dados):
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados))
    png = (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + bloco(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + bloco(b"IEND", b""))
    origem = caminho + ".png"
    with open(origem, "wb") as f:
        f.write(png)
    subprocess.run(["sips", "-s", "format", "jpeg", origem, "--out", caminho], check=True, capture_output=True)
    os.remove(origem)


@unittest.skipUnless(TEM_SETFILE and TEM_EXIFTOOL and TEM_SIPS, "requer SetFile, exiftool e sips")
class TesteMetadadosInternos(unittest.TestCase):
    def setUp(self):
        self.pasta = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.pasta)

    def exif(self, caminho):
        return ad.ler_tags_internas([caminho]).get(caminho, {})

    def test_modo5_grava_exif_e_desfaz(self):
        caminho = os.path.join(self.pasta, "IMG_20181002_013202_003.jpg")
        criar_jpeg(caminho)
        subprocess.run(["exiftool", "-q", "-overwrite_original", "-DateTimeOriginal=2018:10:02 01:32:02",
                        caminho], check=True)
        self.assertEqual(self.exif(caminho), {"ExifIFD:DateTimeOriginal": "2018:10:02 01:32:02"})

        executar_main(self.pasta, "--modo", "5", "--filtro", "*", "--hora-real", "08/11/2026 09:32:02",
                      "--metadados", "--sim")
        novo = os.path.join(self.pasta, "IMG_20261108_093202_003.jpg")
        self.assertTrue(os.path.exists(novo))
        self.assertEqual(set(self.exif(novo).values()), {"2026:11:08 09:32:02"})
        self.assertEqual(datas_do_arquivo(novo), (dt("08/11/2026 09:32:02"),) * 2)

        executar_main(self.pasta, "--modo", "6", "--sim")
        # Volta ao valor original; os campos criados pelo script são removidos
        self.assertEqual(self.exif(caminho), {"ExifIFD:DateTimeOriginal": "2018:10:02 01:32:02"})


if __name__ == "__main__":
    unittest.main()
