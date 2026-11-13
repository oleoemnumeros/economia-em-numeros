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
        self.assertEqual(s.count("<url>"), 5 + 16)
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


if __name__ == "__main__":
    unittest.main()
