import datetime as dt
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "tests"))

import gerar_site as g  # noqa: E402
from exemplo import AREAS, gravar  # noqa: E402


class TestSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.dados = gravar(tmp / "dados.json")
        cls.saida = tmp / "docs"
        cls.caminhos = g.gerar(cls.dados, cls.saida)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def ler(self, rel):
        return (self.saida / rel).read_text(encoding="utf-8")

    def test_paginas_e_arquivos(self):
        for rel in ["index.html", "juros/index.html", "inflacao/index.html", "calculadora/index.html", "sobre/index.html",
                    "404.html", "sitemap.xml", "robots.txt", "CNAME", "favicon.svg", "assets/estilo.css", "assets/calc.js"]:
            self.assertTrue((self.saida / rel).exists(), rel)
        for slug in AREAS:
            self.assertTrue((self.saida / "inflacao" / slug / "index.html").exists(), slug)
        self.assertTrue((self.saida / "emprego" / "index.html").exists())
        self.assertTrue((self.saida / "atividade" / "index.html").exists())
        self.assertTrue((self.saida / "cambio" / "index.html").exists())
        for slug, _, _ in g.UFS.values():
            self.assertTrue((self.saida / "emprego" / slug / "index.html").exists(), slug)
        self.assertEqual(self.ler("CNAME").strip(), "economiaemnumeros.com.br")

    def test_sem_lixo_no_html(self):
        for p in self.saida.rglob("*.html"):
            t = p.read_text(encoding="utf-8")
            for ruim in ["{{", "}}", "Traceback", "inf%"]:
                self.assertNotIn(ruim, t, f"{ruim!r} em {p.name}")
            for ruim in [r"\bNone\b", r"\bnan\b", r"\bundefined\b"]:
                self.assertIsNone(re.search(ruim, t), f"{ruim} em {p.name}")
            self.assertEqual(t.count("<h1"), 1, p)

    def test_canonical_e_sitemap(self):
        s = self.ler("sitemap.xml")
        self.assertEqual(s.count("<url>"), 5 + 16 + 1 + 27 + 2)
        self.assertNotIn("404", s)
        self.assertIn('<link rel="canonical" href="https://economiaemnumeros.com.br/inflacao/salvador/">', self.ler("inflacao/salvador/index.html"))
        self.assertIn('content="noindex"', self.ler("404.html"))
        self.assertNotIn("noindex", self.ler("index.html"))

    def test_ata_e_terca_e_decisoes(self):
        B = g.Base(json.loads(self.dados.read_text(encoding="utf-8")), json.loads((RAIZ / "data" / "copom_calendario.json").read_text(encoding="utf-8")), dt.date(2026, 11, 13))
        for r in B.reunioes:
            self.assertEqual(r["ata"].weekday(), 1)
            self.assertGreater(r["ata"], r["fim"])
        dec = B.decisoes()
        self.assertEqual(dec[0]["fim"], dt.date(2026, 11, 4))
        self.assertEqual(dec[0]["delta"], -1.0)  # 14,75 -> 13,75 no exemplo
        self.assertEqual(B.proxima()["fim"], dt.date(2026, 12, 9))
        self.assertEqual(g.periodo_reuniao(dt.date(2026, 12, 8), dt.date(2026, 12, 9)), "8 e 9 de dezembro")

    def test_calendario_consistente(self):
        cal = json.loads((RAIZ / "data" / "copom_calendario.json").read_text(encoding="utf-8"))["reunioes"]
        ant = None
        for ini, fim in cal:
            i, f = dt.date.fromisoformat(ini), dt.date.fromisoformat(fim)
            self.assertEqual((f - i).days, 1, ini)
            self.assertEqual(i.weekday(), 1, ini)  # terça
            if ant:
                self.assertGreater(i, ant)
            ant = f
        self.assertEqual(len(cal), 32)

    def test_formatacao(self):
        self.assertEqual(g.nf(1234.567, 2), "1.234,57")
        self.assertEqual(g.pct(4.376, 2), "4,38%")
        self.assertEqual(g.pct(-0.594, 2), "−0,59%")
        self.assertEqual(g.mes_nome("2026-09"), "setembro de 2026")
        self.assertEqual(g.sinal(-0.25), "−0,25")

    def test_calculadora_embute_indices(self):
        t = self.ler("calculadora/index.html")
        m = re.search(r'<script type="application/json" id="dados-ipca">(.*?)</script>', t, re.S)
        dados = json.loads(m.group(1))
        self.assertEqual(dados[0][0], "2000-01")
        self.assertEqual(dados[-1][0], "2026-09")

    def test_familia_no_rodape(self):
        t = self.ler("index.html")
        for nome in ["Óleo em Números", "Comex em Números", "Voo em Números", "você está aqui"]:
            self.assertIn(nome, t)

    def test_numeracao_das_reunioes_e_ata_281(self):
        B = g.Base(json.loads(self.dados.read_text(encoding="utf-8")), json.loads((RAIZ / "data" / "copom_calendario.json").read_text(encoding="utf-8")), dt.date(2026, 11, 13))
        por_fim = {r["fim"]: r["num"] for r in B.reunioes}
        self.assertEqual(por_fim[dt.date(2024, 1, 31)], 260)
        self.assertEqual(por_fim[dt.date(2026, 9, 16)], 281)
        self.assertEqual(por_fim[dt.date(2026, 11, 4)], 282)
        self.assertEqual([r["num"] for r in B.reunioes], list(range(260, 260 + len(B.reunioes))))

    def test_juros_mostra_atas_e_links(self):
        t = self.ler("juros/index.html")
        self.assertIn("Atas do Copom, resumidas", t)
        self.assertIn('id="ata-281"', t)
        self.assertIn("Copom282-not20261104282.pdf", t)   # ata ainda sem resumo: só o link
        self.assertIn("ainda está em preparação", t)
        self.assertIn("Copom281-not20260916281.pdf", t)  # PDF oficial que vem do arquivo de resumos
        self.assertIn("não a substitui", t)
        self.assertIn("282ª", t)

    def test_emprego_pagina_brasil_e_uf(self):
        t = self.ler("emprego/index.html")
        self.assertGreaterEqual(t.count("<svg"), 3)  # logo + gráfico da taxa + gráfico de vagas
        self.assertIn("Desemprego e vagas formais no Brasil", t)
        self.assertIn("abr-mai-jun de 2026", t)
        self.assertIn("Novo Caged", t)
        for slug, _, _ in g.UFS.values():
            self.assertIn(f'href="/emprego/{slug}/"', t)
        u = self.ler("emprego/bahia/index.html")
        self.assertIn("Desemprego na Bahia", u)
        self.assertIn("Desemprego no Rio de Janeiro", self.ler("emprego/rio-de-janeiro/index.html"))
        self.assertEqual(set(g.EM), {sigla for _, _, sigla in g.UFS.values()})
        for _, nome, sigla in g.UFS.values():
            self.assertTrue(g.EM[sigla].endswith(nome), sigla)
        self.assertIn("2º trimestre de 2026", u)
        self.assertIn('href="/emprego/"', u)

    def test_nav_inclui_emprego(self):
        self.assertIn('<a href="/emprego/">Emprego</a>', self.ler("index.html"))
        self.assertIn("Desemprego e vagas formais", self.ler("index.html"))

    def test_cambio_pagina(self):
        t = self.ler("cambio/index.html")
        self.assertIn("Dólar hoje e histórico", t)
        self.assertIn("12/11/2026", t)
        self.assertIn("R$ 5,60", t)                            # projeção do Focus para 2026
        self.assertIn("Vs. atual", t)
        self.assertIn("Sistema PTAX", t)
        self.assertGreaterEqual(t.count("<svg"), 3)           # logo + 2 gráficos
        self.assertEqual(t.count("<tr><td"), 10 + 2)          # 10 últimas cotações + 2 projeções

    def test_cambio_variacoes(self):
        B = g.Base(json.loads(self.dados.read_text(encoding="utf-8")), json.loads((RAIZ / "data" / "copom_calendario.json").read_text(encoding="utf-8")), dt.date(2026, 11, 13))
        c = B.cambio_stats()
        self.assertEqual(c["data"], dt.date(2026, 11, 12))
        self.assertAlmostEqual(c["dia"], (c["ult"] / c["linhas"][1][1] - 1) * 100, places=9)
        self.assertAlmostEqual(c["ano"], (c["ult"] / 5.31 - 1) * 100, places=9)   # fim de dez/2025 no exemplo
        self.assertLessEqual(c["min12"], c["ult"])
        self.assertGreaterEqual(c["max12"], c["ult"])
        self.assertEqual(len(c["linhas"]), 10)

    def test_atividade_pagina(self):
        t = self.ler("atividade/index.html")
        self.assertIn("PIB e IBC-Br", t)
        self.assertIn("2º trimestre de 2026", t)
        self.assertIn("agosto de 2026", t)
        self.assertIn("Boletim Focus", t)
        self.assertGreaterEqual(t.count("<svg"), 3)

    def test_ibc_contas(self):
        B = g.Base(json.loads(self.dados.read_text(encoding="utf-8")), json.loads((RAIZ / "data" / "copom_calendario.json").read_text(encoding="utf-8")), dt.date(2026, 11, 13))
        i = B.ibc_stats()
        sa, nsa = dict(B.ibc["sa"]), dict(B.ibc["nsa"])
        self.assertEqual(i["mes"], "2026-08")
        self.assertAlmostEqual(i["mm"], (sa["2026-08"] / sa["2026-07"] - 1) * 100, places=9)
        self.assertAlmostEqual(i["yoy"], (nsa["2026-08"] / nsa["2025-08"] - 1) * 100, places=9)
        meses = sorted(nsa)
        self.assertAlmostEqual(i["a12"], (sum(nsa[m] for m in meses[-12:]) / sum(nsa[m] for m in meses[-24:-12]) - 1) * 100, places=9)
        self.assertEqual(len(i["linhas"]), 12)

    def test_nav_e_home_com_cartoes(self):
        h = self.ler("index.html")
        for rotulo in ("Atividade", "Câmbio"):
            self.assertIn(f'">{rotulo}</a>', h)
        self.assertIn('href="/cambio/"', h)
        self.assertIn('href="/atividade/"', h)

    def test_textos_de_variacao(self):
        self.assertEqual(g.verbo_var(0.44, 1), "cresceu 0,4%")
        self.assertEqual(g.verbo_var(-0.3, 1), "recuou 0,3%")
        self.assertEqual(g.verbo_var(0.02, 1), "ficou estável")
        self.assertEqual(g.verbo_var(1.234, 2, "subiu", "caiu"), "subiu 1,23%")
        self.assertEqual(g.pct_sinal(None), "–")
        self.assertEqual(g.pct_sinal(-0.25, 2), "−0,25%")

    def test_rotulos(self):
        self.assertEqual(g.rot_tri("202602"), "2º tri/26")
        self.assertEqual(g.rot_tri("202602", True), "2º trimestre de 2026")
        self.assertEqual(g.rot_movel("202606"), "abr-mai-jun de 2026")
        self.assertEqual(g.rot_movel("202602"), "dez-jan-fev de 2026")
        self.assertEqual(g.saldo_txt(121305), "+121.305")
        self.assertEqual(g.saldo_txt(-4200), "−4.200")


class TestSemDadosNovos(unittest.TestCase):
    """O site continua válido se o robô ainda não trouxe emprego/atas (ou se falhou)."""

    def test_sem_emprego_nem_atas(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dados = json.loads(gravar(d / "x.json").read_text(encoding="utf-8"))
            for k in ("desocupacao", "caged", "atas", "cambio", "ibc", "pib"):
                dados.pop(k)
            (d / "dados.json").write_text(json.dumps(dados), encoding="utf-8")
            cam = g.gerar(d / "dados.json", d / "docs", resumos_path=d / "nao_existe.json")
            self.assertEqual(len(cam), 21)
            self.assertFalse((d / "docs" / "emprego").exists())
            for rel in ("index.html", "juros/index.html"):
                t = (d / "docs" / rel).read_text(encoding="utf-8")
                for rota in ("/emprego/", "/cambio/", "/atividade/"):
                    self.assertNotIn(rota, t)
            j = (d / "docs" / "juros" / "index.html").read_text(encoding="utf-8")
            self.assertIn("ainda está em preparação", j)          # a ata mais recente aparece mesmo sem PDF conhecido
            self.assertIn("bcb.gov.br/publicacoes/atascopom", j)   # e aponta para a lista oficial

    def test_emprego_sem_caged(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            dados = json.loads(gravar(d / "x.json").read_text(encoding="utf-8"))
            dados.pop("caged")
            (d / "dados.json").write_text(json.dumps(dados), encoding="utf-8")
            g.gerar(d / "dados.json", d / "docs")
            t = (d / "docs" / "emprego" / "index.html").read_text(encoding="utf-8")
            self.assertNotIn("Novo Caged registrou", t)
            self.assertIn("Menor taxa", t)


class TestSoUmaFonteNova(unittest.TestCase):
    def gerar_sem(self, *chaves):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        d = Path(d.name)
        dados = json.loads(gravar(d / "x.json").read_text(encoding="utf-8"))
        for k in chaves:
            dados.pop(k, None)
        (d / "dados.json").write_text(json.dumps(dados), encoding="utf-8")
        g.gerar(d / "dados.json", d / "docs")
        return d / "docs"

    def test_atividade_so_com_ibc(self):
        docs = self.gerar_sem("pib")
        t = (docs / "atividade" / "index.html").read_text(encoding="utf-8")
        self.assertIn("IBC-Br", t)
        self.assertNotIn("PIB por trimestre", t)
        self.assertGreater((docs / "cambio" / "index.html").stat().st_size, 1000)

    def test_atividade_so_com_pib(self):
        docs = self.gerar_sem("ibc")
        t = (docs / "atividade" / "index.html").read_text(encoding="utf-8")
        self.assertIn("PIB por trimestre", t)
        self.assertNotIn("IBC-Br mês a mês", t)

    def test_sem_pib_nem_ibc_nao_ha_pagina(self):
        docs = self.gerar_sem("pib", "ibc")
        self.assertFalse((docs / "atividade").exists())
        self.assertNotIn("/atividade/", (docs / "index.html").read_text(encoding="utf-8"))

    def test_sem_cambio_nao_ha_pagina(self):
        docs = self.gerar_sem("cambio")
        self.assertFalse((docs / "cambio").exists())
        self.assertNotIn("/cambio/", (docs / "index.html").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
