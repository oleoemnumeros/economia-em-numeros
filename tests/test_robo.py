import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import atualizar as r  # noqa: E402


class TestJanelas(unittest.TestCase):
    def test_nenhuma_janela_passa_de_10_anos(self):
        js = r.janelas(dt.date(2016, 1, 1), dt.date(2026, 11, 13))
        self.assertGreaterEqual(len(js), 2)
        self.assertEqual(js[0][0], dt.date(2016, 1, 1))
        self.assertEqual(js[-1][1], dt.date(2026, 11, 13))
        for a, b in js:
            self.assertLess((b - a).days, 3650)
        for (_, b1), (a2, _) in zip(js, js[1:]):
            self.assertEqual(a2 - b1, dt.timedelta(days=1))  # sem buracos nem sobreposição

    def test_janela_curta_e_uma_so(self):
        self.assertEqual(r.janelas(dt.date(2026, 1, 1), dt.date(2026, 11, 13)), [(dt.date(2026, 1, 1), dt.date(2026, 11, 13))])


class TestConsulta(unittest.TestCase):
    def test_espaco_vira_percent20_e_nao_mais(self):
        u = r.consulta("https://x/y", {"$filter": "Indicador eq 'Câmbio' and Data ge '2026-10-20'", "$top": "5"})
        self.assertNotIn("+", u)
        self.assertNotIn(" ", u)
        self.assertIn("$filter=Indicador%20eq%20'C%C3%A2mbio'%20and%20Data%20ge%20'2026-10-20'", u)
        self.assertTrue(u.endswith("&$top=5"))


class FakeResp:
    def __init__(self, dados):
        self._d = dados

    def json(self):
        return self._d


CAB_4099 = {"NC": "Nível Territorial (Código)", "NN": "Nível Territorial", "MC": "Unidade de Medida (Código)", "MN": "Unidade de Medida", "V": "Valor",
            "D1C": "Brasil e Unidade da Federação (Código)", "D1N": "Brasil e Unidade da Federação", "D2C": "Variável (Código)", "D2N": "Variável",
            "D3C": "Trimestre (Código)", "D3N": "Trimestre"}


def linha(cod, nome, per, v):
    return {"NC": "1", "NN": "Brasil", "MC": "2", "MN": "%", "V": v, "D1C": cod, "D1N": nome, "D2C": "4099", "D2N": "Taxa", "D3C": per, "D3N": f"{per[4:]}º trimestre {per[:4]}"}


class TestAtas(unittest.TestCase):
    def test_ata_e_a_primeira_terca_depois(self):
        self.assertEqual(r.ata_depois(dt.date(2026, 11, 4)), dt.date(2026, 11, 10))  # quarta -> terça seguinte
        self.assertEqual(r.ata_depois(dt.date(2026, 9, 16)), dt.date(2026, 9, 22))
        self.assertEqual(r.ata_depois(dt.date(2026, 1, 27)), dt.date(2026, 2, 3))    # reunião numa terça: ata na terça da semana seguinte

    def test_numero_e_endereco_do_pdf(self):
        visitados = []

        def falso(url):
            visitados.append(url)
            return url.endswith("Copom281-not20260916281.pdf")

        with mock.patch.object(r, "arquivo_pdf_existe", falso), mock.patch.object(r, "HOJE", dt.date(2026, 11, 13)), \
                mock.patch.object(r, "DADOS", Path("/nao/existe.json")), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            out = r.atas()
        self.assertEqual(out, {"281": {"pdf": "https://www.bcb.gov.br/content/copom/atascopom/Copom281-not20260916281.pdf"}})
        self.assertIn("https://www.bcb.gov.br/content/copom/atascopom/Copom282-not20261104282.pdf", visitados)  # confere o endereço da 282ª
        self.assertFalse(any("Copom283" in u for u in visitados))  # reunião de dezembro ainda não tem ata

    def test_nao_verificavel_nao_vira_link(self):
        with mock.patch.object(r, "arquivo_pdf_existe", lambda u: None), mock.patch.object(r, "HOJE", dt.date(2026, 11, 13)), \
                mock.patch.object(r, "DADOS", Path("/nao/existe.json")), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            self.assertEqual(r.atas(), {})
            self.assertTrue(any("não deu para verificar" in a for a in dbg["avisos"]))


class TestEmprego(unittest.TestCase):
    def test_parser_acha_colunas_de_periodo_e_territorio(self):
        resp = [CAB_4099, linha("1", "Brasil", "202602", "5.8"), linha("29", "Bahia", "202602", "8.1")]
        with mock.patch.object(r, "get", lambda *a, **k: FakeResp(resp)):
            cab, dados, k_per, k_ter, k_nome = r.sidra_linhas("x")
        self.assertEqual((k_per, k_ter, k_nome), ("D3C", "D1C", "D1N"))
        self.assertEqual(len(dados), 2)

    def test_desocupacao_monta_series(self):
        cods = ["1"] + [c for c in ("11", "12", "13", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26", "27", "28", "29", "31", "32", "33", "35", "41", "42", "43", "50", "51", "52", "53")]
        uf = [CAB_4099] + [linha(c, f"T{c}", per, "6.5") for c in cods for per in ("202601", "202602")]
        movel = [{**CAB_4099, "D3C": "Trimestre Móvel (Código)"}] + [
            {**linha("1", "Brasil", f"2025{m:02d}", "6.1"), "D3C": f"2025{m:02d}"} for m in range(1, 13)] + [
            {**linha("1", "Brasil", f"2026{m:02d}", "5.9"), "D3C": f"2026{m:02d}"} for m in range(1, 7)]
        chamadas = []

        def falso(url, *a, **k):
            chamadas.append(url)
            return FakeResp(uf if "/t/4099/" in url else movel)

        with mock.patch.object(r, "get", falso), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            d = r.desocupacao()
        self.assertEqual(len(chamadas), 2)
        self.assertEqual(d["trimestral"]["29"]["serie"][-1][:1], ["202602"])
        self.assertEqual(d["trimestral"]["1"]["serie"][-1][2], 6.5)
        self.assertEqual([x[0] for x in d["movel"]][:2], ["202501", "202502"])
        self.assertEqual(d["movel"][-1][2], 5.9)

    def test_desocupacao_recusa_resposta_incompleta(self):
        pobre = [CAB_4099, linha("1", "Brasil", "202602", "5.8")]
        with mock.patch.object(r, "get", lambda *a, **k: FakeResp(pobre)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.desocupacao()

    def test_caged_saldo_e_a_variacao_do_estoque(self):
        estoque, v, y, m = [(dt.date(2019, 12, 1), 40_000_000.0)], 40_000_000.0, 2020, 1
        while (y, m) <= (2026, 9):
            v += 50_000 if (y, m) == (2020, 1) else 100_000
            estoque.append((dt.date(y, m, 1), v))
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        with mock.patch.object(r, "sgs", lambda *a: estoque), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            out = r.caged()["saldo"]
        self.assertEqual(out[0], ["2020-01", 50000])        # dez/2019 serve só de base
        self.assertEqual(out[-1], ["2026-09", 100000])
        self.assertEqual(len(out), 12 * 6 + 9)

    def test_caged_confere_o_valor_conhecido_de_setembro_de_2026(self):
        estoque = [(dt.date(2025, m, 1), 47_000_000.0 + 10_000 * m) for m in range(1, 13)] + [
            (dt.date(2026, 7, 1), 48_077_210.0), (dt.date(2026, 8, 1), 48_238_272.0), (dt.date(2026, 9, 1), 48_359_577.0)]
        with mock.patch.object(r, "sgs", lambda *a: sorted(estoque)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            self.assertEqual(dict(r.caged()["saldo"])["2026-09"], 121305)

    def test_caged_recusa_serie_que_nao_e_estoque(self):
        ja_saldo = [(dt.date(2025, m, 1), 100_000.0 + m) for m in range(1, 13)] + [(dt.date(2026, m, 1), 90_000.0) for m in range(1, 5)]
        with mock.patch.object(r, "sgs", lambda *a: sorted(ja_saldo)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.caged()
        salto = [(dt.date(2025, m, 1), 48_000_000.0) for m in range(1, 13)] + [(dt.date(2026, 1, 1), 52_000_000.0)]
        with mock.patch.object(r, "sgs", lambda *a: sorted(salto)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.caged()


def dias_uteis(ini: dt.date, fim: dt.date):
    d = ini
    while d <= fim:
        if d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


class TestAtividadeECambio(unittest.TestCase):
    def test_cambio_recorta_diario_e_calcula_mensal(self):
        serie = [(d, 5.0 + (i % 7) / 10) for i, d in enumerate(dias_uteis(dt.date(2016, 1, 4), dt.date(2026, 11, 12)))]
        with mock.patch.object(r, "sgs", lambda *a: serie), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            out = r.cambio()
        self.assertEqual(out["diario"][-1][0], "2026-11-12")
        self.assertGreaterEqual(dt.date.fromisoformat(out["diario"][0][0]), dt.date(2025, 10, 8))
        self.assertLess(len(out["diario"]), 300)
        self.assertEqual(out["mensal"][0][0], "2016-01")
        m = out["mensal"][-1]
        self.assertEqual(m[0], "2026-11")
        self.assertEqual(m[2], serie[-1][1])  # fim do mês = última cotação disponível

    def test_cambio_recusa_serie_estranha(self):
        ruim = [(d, 0.5) for d in dias_uteis(dt.date(2016, 1, 4), dt.date(2026, 11, 12))]
        with mock.patch.object(r, "sgs", lambda *a: ruim), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.cambio()
        curta = [(d, 5.0) for d in dias_uteis(dt.date(2026, 1, 4), dt.date(2026, 11, 12))]
        with mock.patch.object(r, "sgs", lambda *a: curta), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.cambio()

    def test_ibc_duas_series_e_trava(self):
        meses = [(dt.date(2022 + (m // 12), m % 12 + 1, 1), 140.0 + m / 10) for m in range(48)]
        with mock.patch.object(r, "sgs", lambda cod, ini: meses), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            out = r.ibcbr()
        self.assertEqual(set(out), {"sa", "nsa"})
        self.assertEqual(out["sa"][0][0], "2022-01")
        self.assertEqual(out["sa"][-1][0], "2025-12")
        variacao = [(d, 1.2) for d, _ in meses]  # variação em %, não índice
        with mock.patch.object(r, "sgs", lambda cod, ini: variacao), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.ibcbr()

    def test_fiscal_quatro_series_e_trava(self):
        faixa = {13762: 78.0, 4513: 62.0, 5793: 0.6, 5727: 7.5}
        meses = [(dt.date(2015 + (k // 12), k % 12 + 1, 1), k) for k in range(138)]
        with mock.patch.object(r, "sgs", lambda cod, ini: [(d, faixa[cod] + k / 100) for d, k in meses]), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.fiscal()
        self.assertEqual(set(out), {"dbgg", "dlsp", "primario", "nominal"})
        self.assertEqual(out["dbgg"][0][0], "2015-01")
        self.assertEqual(len([a for a in dbg["avisos"] if a.startswith("Fiscal")]), 4)
        # dívida em R$ bilhões (e não em % do PIB) deve ser recusada
        with mock.patch.object(r, "sgs", lambda cod, ini: [(d, 6_000_000.0 + k) for d, k in meses]), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.fiscal()
        # série curta demais também
        with mock.patch.object(r, "sgs", lambda cod, ini: [(d, faixa[cod]) for d, _ in meses[:10]]), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.fiscal()

    def _linhas_pib(self, vars_=("6561", "6563", "6564")):
        cab = {"NC": "Nível Territorial (Código)", "NN": "Nível Territorial", "MC": "Unidade de Medida (Código)", "MN": "Unidade de Medida", "V": "Valor",
               "D1C": "Brasil (Código)", "D1N": "Brasil", "D2C": "Variável (Código)", "D2N": "Variável", "D3C": "Trimestre (Código)", "D3N": "Trimestre",
               "D4C": "Setores e subsetores (Código)", "D4N": "Setores e subsetores"}
        tris = [f"{a}0{q}" for a in (2023, 2024, 2025, 2026) for q in (1, 2, 3, 4)][:16]
        return [cab] + [{"NC": "1", "V": f"{0.1 * i + 1:.1f}", "D1C": "1", "D2C": v, "D3C": t, "D4C": "90707"} for i, t in enumerate(tris) for v in vars_]

    def test_pib_monta_trimestres(self):
        with mock.patch.object(r, "get", lambda *a, **k: FakeResp(self._linhas_pib())), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            out = r.pib()["trimestral"]
        self.assertEqual(len(out), 16)
        self.assertEqual(out[0]["t"], "202301")
        self.assertEqual(out[-1]["t"], "202604")
        self.assertEqual(set(out[0]), {"t", "yoy", "a4", "qoq"})

    def test_pib_recusa_variaveis_inesperadas(self):
        with mock.patch.object(r, "get", lambda *a, **k: FakeResp(self._linhas_pib(("1", "2")))), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.pib()


    # ---- crédito ----
    def test_credito_seis_series_e_relacoes(self):
        meses = [(dt.date(2023 + (i // 12), i % 12 + 1, 1), i) for i in range(48)]
        faixa = {21084: 5.0, 21112: 7.5, 20716: 50.0, 20740: 60.0, 29037: 48.0, 29034: 28.0}
        with mock.patch.object(r, "sgs", lambda cod, ini: [(d, faixa[cod] + k * 0.01) for d, k in meses]), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.credito()
        self.assertEqual(set(out), {c[0] for c in r.CREDITO})
        self.assertEqual(len([a for a in dbg["avisos"] if a.startswith("Crédito")]), 6)
        # códigos trocados (livre abaixo do total) devem ser recusados
        troca = {**faixa, 21112: 4.0}
        with mock.patch.object(r, "sgs", lambda cod, ini: [(d, troca[cod]) for d, _ in meses]), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.credito()
        # valor fora da faixa (ex.: saldo em R$ milhões no lugar de %)
        with mock.patch.object(r, "sgs", lambda cod, ini: [(d, 900_000.0) for d, _ in meses]), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.credito()

    # ---- IBGE mensal (PIM-PF e PMC) ----
    @staticmethod
    def _cab(classe):
        return {"NC": "Nível Territorial (Código)", "NN": "Nível Territorial", "MC": "Unidade de Medida (Código)", "MN": "Unidade de Medida", "V": "Valor",
                "D1C": "Brasil (Código)", "D1N": "Brasil", "D2C": "Variável (Código)", "D2N": "Variável", "D3C": "Mês (Código)", "D3N": "Mês",
                "D4C": f"{classe} (Código)", "D4N": classe}

    def _sidra(self, prefixo, classe, categorias, com_variacoes=True, n=62, valor=lambda cod, i: None):
        """Resposta no formato real do SIDRA: variáveis 'PIMPF - ...'/'PMC - ...', uma coluna de classificação e '..' onde não há dado.
        As variações oficiais são coerentes com os índices (como no IBGE); a 'acumulada no ano' vale 9,9 de propósito."""
        pers = [f"{2021 + (i + 7) // 12}{(i + 7) % 12 + 1:02d}" for i in range(n)]
        idx = lambda i: 100 + 0.1 * i + ((i % 12) - 6) * 0.3
        sa = lambda i: 101 + 0.1 * i + (i % 3) * 0.2
        mm = lambda i: round((sa(i) / sa(i - 1) - 1) * 100, 5) if i >= 1 else None
        yoy = lambda i: round((idx(i) / idx(i - 12) - 1) * 100, 5) if i >= 12 else None
        a12 = lambda i: round((sum(idx(i - k) for k in range(12)) / sum(idx(i - k) for k in range(12, 24)) - 1) * 100, 5) if i >= 23 else None
        vars_ = [("12606", "Número-índice (2022=100)", "Número-índice", idx),
                 ("12607", "Número-índice com ajuste sazonal (2022=100)", "Número-índice", sa)]
        if com_variacoes:
            vars_ += [("11601", "Variação mês/mês imediatamente anterior, com ajuste sazonal", "%", mm),
                      ("11602", "Variação mês/mesmo mês do ano anterior", "%", yoy),
                      ("11603", "Variação acumulada no ano (em relação ao mesmo período do ano anterior)", "%", lambda i: 9.9),
                      ("11604", "Variação acumulada em 12 meses", "%", a12)]
        linhas = [self._cab(classe)]
        for cat in categorias:
            for i, per in enumerate(pers):
                for cod, nome, un, f in vars_:
                    v = valor(cod, i)
                    if v is None:
                        x = f(i)
                        v = ".." if x is None else f"{x:.5f}"
                    linhas.append({"NC": "1", "MN": un, "V": v, "D1C": "1", "D1N": "Brasil", "D2C": cod, "D2N": f"{prefixo} - {nome}",
                                   "D3C": per, "D3N": per, "D4C": "9", "D4N": cat})
        return linhas

    def _pim(self, **kw):
        return self._sidra("PIMPF", "Seções e atividades industriais (CNAE 2.0)", ("1 Indústria geral", "2 Indústrias extrativas"), **kw)

    def _pmc(self, **kw):
        return self._sidra("PMC", "Tipos de índice", ("Índice de receita nominal de vendas no comércio varejista", "Índice de volume de vendas no comércio varejista"), **kw)

    def _get_ibge(self, **tabelas):
        """tabelas: {'8888': linhas, ...}; tabela sem resposta falha como o IBGE fora do ar."""
        urls = []

        def get(url, *a, **k):
            urls.append(url)
            for t, linhas in tabelas.items():
                if f"/t/{t}/" in url:
                    return FakeResp(linhas)
            raise RuntimeError(f"{url} falhou")
        get.urls = urls
        return get

    def test_industria_le_variacoes_do_ibge_so_da_industria_geral(self):
        g = self._get_ibge(**{"8888": self._pim()})
        with mock.patch.object(r, "get", g), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.producao_industrial()
        self.assertEqual(set(out), {"sa", "idx", "mm", "yoy", "a12"})
        self.assertEqual(len(out["sa"]), 62)
        self.assertEqual(out["sa"][0][0], "2021-08")
        idx = lambda i: 100 + 0.1 * i + ((i % 12) - 6) * 0.3
        self.assertAlmostEqual(out["yoy"][-1][1], (idx(61) / idx(49) - 1) * 100, places=3)   # mês/mesmo mês, não o acumulado no ano (9,9)
        self.assertNotEqual(out["yoy"][-1][1], 9.9)
        self.assertLess(abs(out["a12"][-1][1]), 5)
        self.assertEqual(len(out["yoy"]), 50)
        self.assertRegex(out["sa"][-1][0], r"^\d{4}-\d{2}$")
        self.assertEqual(len(g.urls), 1)
        self.assertIn("/t/8888/n1/all/v/all/p/last%2062/c544/all", g.urls[0])   # sem classificação o SIDRA devolve só '..'
        self.assertTrue(any("calculadas aqui: nenhuma" in a for a in dbg["avisos"]))
        ignoradas = " ".join(a for a in dbg["avisos"] if a.startswith("Indústria: linhas ignoradas"))
        self.assertIn("acumulada no ano", ignoradas)       # acumulado no ano fica de fora

    def test_calcula_variacoes_quando_o_ibge_nao_devolve(self):
        with mock.patch.object(r, "get", self._get_ibge(**{"8888": self._pim(com_variacoes=False)})), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.producao_industrial()
        sa = lambda i: 101 + 0.1 * i + (i % 3) * 0.2
        idx = lambda i: 100 + 0.1 * i + ((i % 12) - 6) * 0.3
        self.assertAlmostEqual(out["mm"][-1][1], (sa(61) / sa(60) - 1) * 100, places=1)
        self.assertAlmostEqual(out["yoy"][-1][1], (idx(61) / idx(49) - 1) * 100, places=1)
        self.assertGreater(len(out["a12"]), 30)
        self.assertTrue(any("calculadas aqui: ['mm', 'yoy', 'a12']" in a for a in dbg["avisos"]))

    def test_varejo_usa_so_volume_e_busca_o_ampliado_na_8881(self):
        g = self._get_ibge(**{"8880": self._pmc(), "8881": self._pmc()})
        with mock.patch.object(r, "get", g), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            out = r.varejo()
        self.assertEqual(set(out), {"restrito", "ampliado"})
        self.assertEqual(len(out["restrito"]["sa"]), 62)
        self.assertEqual(len(out["ampliado"]["sa"]), 62)
        self.assertTrue(all("/c11046/all" in u for u in g.urls))
        self.assertEqual(len(g.urls), 2)

    def test_varejo_ignora_receita_nominal(self):
        linhas = self._pmc(valor=lambda cod, i: None)
        for x in linhas[1:]:
            if "receita" in x["D4N"]:
                x["V"] = "9999.0"             # se a receita entrasse, o índice sairia fora da faixa e o robô recusaria
        with mock.patch.object(r, "get", self._get_ibge(**{"8880": linhas})), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            out = r.varejo()
        self.assertEqual(set(out), {"restrito"})
        self.assertLess(max(v for _, v in out["restrito"]["sa"]), 120)

    def test_varejo_sem_ampliado_segue_so_com_restrito(self):
        with mock.patch.object(r, "get", self._get_ibge(**{"8880": self._pmc()})), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.varejo()
        self.assertEqual(set(out), {"restrito"})
        self.assertTrue(any("Varejo ampliado indisponível" in a for a in dbg["avisos"]))

    def test_ibge_recusa_atividade_ausente_celulas_vazias_e_indice_absurdo(self):
        linhas = self._sidra("PIMPF", "Seções e atividades industriais (CNAE 2.0)", ("2 Indústrias extrativas",))
        with mock.patch.object(r, "get", self._get_ibge(**{"8888": linhas})), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.producao_industrial()
        vazio = self._pim(valor=lambda cod, i: "..")      # o que o SIDRA devolveu no primeiro teste real
        with mock.patch.object(r, "get", self._get_ibge(**{"8888": vazio})), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaisesRegex(RuntimeError, "nenhuma linha numérica"):
                r.producao_industrial()
        absurdo = self._pim(valor=lambda cod, i: "9000.00" if cod in ("12606", "12607") else None)
        with mock.patch.object(r, "get", self._get_ibge(**{"8888": absurdo})), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.producao_industrial()

    def test_recusa_variacao_oficial_que_nao_confere_com_o_indice(self):
        """Foi o erro do primeiro dia: 'acumulada no ano' lida como 'mês/mesmo mês' (0,4 em vez de -2,5)."""
        linhas = self._pim()
        for x in linhas[1:]:
            if x["D2C"] == "11602":
                x["V"] = "9.90000"            # se o IBGE mudar o nome e a coluna errada entrar, o conferidor barra
        with mock.patch.object(r, "get", self._get_ibge(**{"8888": linhas})), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaisesRegex(RuntimeError, "não confere"):
                r.producao_industrial()

    def test_desloca_periodo_e_tipo_de_medida(self):
        self.assertEqual(r._desloca("202601", -1), "202512")
        self.assertEqual(r._desloca("202612", 1), "202701")
        self.assertEqual(r._desloca("202603", -12), "202503")
        self.assertEqual(r.medida_ibge("PIMPF - Número-índice com ajuste sazonal (2022=100) | 1 Indústria geral", "Número-índice"), "sa")
        self.assertEqual(r.medida_ibge("PIMPF - Número-índice (2022=100)", "Número-índice"), "idx")
        self.assertEqual(r.medida_ibge("PIMPF - Variação acumulada no ano", "%"), None)
        self.assertEqual(r.medida_ibge("PIMPF - Variação acumulada no ano (em relação ao mesmo período do ano anterior)", "%"), None)
        self.assertEqual(r.medida_ibge("PMC - Variação da média móvel trimestral, com ajuste sazonal", "%"), None)
        self.assertEqual(r.medida_ibge("PIMPF - Variação mês/mesmo mês do ano anterior", "%"), "yoy")
        self.assertEqual(r.medida_ibge("PMC - Variação mês/mês imediatamente anterior, com ajuste sazonal", "%"), "mm")
        self.assertEqual(r.medida_ibge("PMC - Variação acumulada em 12 meses", "%"), "a12")


class TestSetorExterno(unittest.TestCase):
    def _sgs(self, ca_mensal=lambda k: -3000.0 - k, ca_pib=lambda k: -2.5, idp=lambda k: 5000.0 + k, reservas=lambda k: 350000.0 + k):
        """Séries sintéticas: 120 meses mensais (2016-2025 e 2026 até outubro) e 4.000 dias úteis de reservas até hoje."""
        meses = [(dt.date(2016 + k // 12, k % 12 + 1, 1), k) for k in range(130)]
        hoje = r.HOJE
        dias = [(hoje - dt.timedelta(days=4000 - j), j) for j in range(4001)]

        def sgs(cod, ini):
            if cod == 22701:
                return [(d, ca_mensal(k)) for d, k in meses]
            if cod == 24419:  # soma móvel de 12 meses da série mensal
                return [(d, sum(ca_mensal(j) for j in range(k - 11, k + 1))) for d, k in meses if k >= 11]
            if cod == 23079:
                return [(d, ca_pib(k)) for d, k in meses if k >= 11]
            if cod == 22885:
                return [(d, idp(k)) for d, k in meses]
            if cod == 13621:
                return [(d, reservas(j)) for d, j in dias]
            raise AssertionError(cod)
        return sgs

    def test_externo_monta_series_e_confere_soma_de_12_meses(self):
        with mock.patch.object(r, "sgs", self._sgs()), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.setor_externo()
        self.assertEqual(set(out), {"ca_mensal", "ca_12m", "ca_pib", "idp_mensal", "reservas", "reservas_ultima"})
        self.assertEqual(out["ca_12m"][-1][0], out["ca_mensal"][-1][0])
        self.assertEqual(out["reservas"][-1][0], r.HOJE.strftime("%Y-%m"))  # último mês = último dia disponível
        self.assertEqual(out["reservas_ultima"][0], r.HOJE.isoformat())
        self.assertTrue(any(a.startswith("Reservas") for a in dbg["avisos"]))

    def test_externo_recusa_serie_acumulada_que_nao_bate_com_a_mensal(self):
        sgs = self._sgs()

        def torta(cod, ini):
            return [(d, v * 3) for d, v in sgs(cod, ini)] if cod == 24419 else sgs(cod, ini)
        with mock.patch.object(r, "sgs", torta), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError) as e:
                r.setor_externo()
        self.assertIn("não bate", str(e.exception))

    def test_externo_recusa_sinal_trocado_unidade_errada_e_reservas_velhas(self):
        with mock.patch.object(r, "sgs", self._sgs(ca_pib=lambda k: 2.5)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.setor_externo()
        with mock.patch.object(r, "sgs", self._sgs(idp=lambda k: 5.0)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):  # IDP em US$ bilhões no lugar de milhões
                r.setor_externo()
        with mock.patch.object(r, "sgs", self._sgs(reservas=lambda k: 355.0)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):  # reservas em US$ bilhões
                r.setor_externo()
        velhas = self._sgs()
        with mock.patch.object(r, "sgs", lambda cod, ini: velhas(cod, ini)[:-60] if cod == 13621 else velhas(cod, ini)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.setor_externo()

    def _comex(self, n=142, exp=lambda k: 3.0e10 + k * 1e8, imp=lambda k: 2.4e10 + k * 5e7):
        meses = [f"{2015 + k // 12}-{k % 12 + 1:02d}" for k in range(n)]
        return {"mes": meses[-1], "mensal": {"export": [{"mes": m, "fob": exp(k), "kg": 1} for k, m in enumerate(meses)],
                                              "import": [{"mes": m, "fob": imp(k), "kg": 1} for k, m in enumerate(meses)]}}

    def test_balanca_le_comex_em_us_milhoes(self):
        comex = self._comex()
        hoje = dt.date(2026, 11, 13)
        with mock.patch.object(r, "get", lambda *a, **k: FakeResp(comex)), mock.patch.object(r, "sgs", lambda cod, ini: [(dt.date(2026, 9, 1), 7000.0)]), \
                mock.patch.object(r, "HOJE", hoje), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.balanca()
        self.assertEqual(out["mes"], "2026-10")
        self.assertEqual(len(out["export"]), 142)
        self.assertAlmostEqual(out["export"][-1][1], (3.0e10 + 141e8) / 1e6, places=1)  # US$ milhões
        self.assertTrue(any("22707" in a for a in dbg["avisos"]))

    def test_balanca_recusa_dado_curto_em_dolar_inteiro_ou_velho(self):
        hoje = dt.date(2026, 11, 13)
        for comex in (self._comex(n=30), self._comex(exp=lambda k: 3.0e4, imp=lambda k: 2.4e4), self._comex(n=100)):
            with mock.patch.object(r, "get", lambda *a, **k: FakeResp(comex)), mock.patch.object(r, "sgs", lambda *a: []), \
                    mock.patch.object(r, "HOJE", hoje), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
                with self.assertRaises(RuntimeError):
                    r.balanca()

    def test_balanca_segue_sem_a_conferencia_do_bcb(self):
        def quebra(*a):
            raise RuntimeError("fora do ar")
        with mock.patch.object(r, "get", lambda *a, **k: FakeResp(self._comex())), mock.patch.object(r, "sgs", quebra), \
                mock.patch.object(r, "HOJE", dt.date(2026, 11, 13)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.balanca()
        self.assertEqual(out["mes"], "2026-10")
        self.assertTrue(any("não feita" in a for a in dbg["avisos"]))


class TestBolsaFamilia(unittest.TestCase):
    UFS = ["11", "12", "13", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26", "27", "28", "29", "31", "32", "33", "35", "41", "42", "43", "50", "51", "52", "53"]

    def setUp(self):
        self.codigos = [f"{uf}{i:04d}" for uf in self.UFS for i in range(210)]  # 5.670 municípios de mentira
        self.tmp = tempfile.TemporaryDirectory()
        self.arq = Path(self.tmp.name) / "bf.json"
        self.addCleanup(self.tmp.cleanup)

    def _sidra_pop(self):
        cab = {"NC": "Nível Territorial (Código)", "V": "Valor", "D1C": "Município (Código)", "D1N": "Município", "D3C": "Ano (Código)"}
        return [cab] + [{"NC": "6", "V": "37500", "D1C": c + "0", "D1N": f"Cidade {c} - {r_uf(c)}", "D3C": "2026"} for c in self.codigos]

    def _doc(self, c, k, escala=1.0):
        f = int((3000 + int(c[2:]) % 800) * escala) + k  # ~19 milhões de famílias no total, como o programa de verdade
        return {"ibge": c, "anomes": "x", "f": f, "p": f * 2.5, "v": f * 680.0}

    def _get(self, meses_publicados, escala=lambda ym: 1.0, falha_em=(), linhas_por_pagina=None):
        """API fake: meses não publicados voltam sem documentos; `linhas_por_pagina` limita o `rows` para testar a paginação."""
        chamadas = []

        def get(url, params=None, **kw):
            if "/t/6579/" in url:
                return FakeResp(self._sidra_pop())
            chamadas.append(params)
            fq = params["fq"]
            ym = next(x.split(":")[1] for x in fq if x.startswith("anomes_s:"))
            ym = f"{ym[:4]}-{ym[4:]}"
            if ym in falha_em:
                raise RuntimeError("servidor fora do ar")
            if ym not in meses_publicados:
                return FakeResp({"response": {"numFound": 0, "start": 0, "docs": []}})
            k = meses_publicados.index(ym)
            todas = [self._doc(c, k, escala(ym)) for c in self.codigos]
            ini, n = int(params["start"]), min(int(params["rows"]), linhas_por_pagina or 10**9)
            return FakeResp({"response": {"numFound": len(todas), "start": ini, "docs": todas[ini:ini + n]}})
        get.chamadas = chamadas
        return get

    def _roda(self, get, hoje=dt.date(2026, 11, 13), inicio="2023-03"):
        with mock.patch.object(r, "get", get), mock.patch.object(r, "BF_ARQ", self.arq), mock.patch.object(r, "HOJE", hoje), \
                mock.patch.object(r, "BF_INICIO", inicio), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.bolsa_familia()
        return out, dbg

    def test_baixa_os_meses_publicados_e_ignora_o_corrente_sem_dados(self):
        pub = [f"{2023 + (2 + k) // 12}-{(2 + k) % 12 + 1:02d}" for k in range(44)]  # 2023-03 .. 2026-10
        self.assertEqual(pub[-1], "2026-10")
        out, dbg = self._roda(self._get(pub))
        d = json.loads(self.arq.read_text(encoding="utf-8"))
        self.assertEqual(sorted(d["meses"])[0], "2023-03")
        self.assertEqual(sorted(d["meses"])[-1], "2026-10")  # 2026-11 ainda não saiu
        self.assertEqual(len(d["meses"]), 44)
        self.assertEqual(len(d["nomes"]), 5670)
        self.assertEqual(d["nomes"][self.codigos[0]][1], r_uf(self.codigos[0]))
        c = self.codigos[7]
        self.assertEqual(d["meses"]["2026-10"][c][:2], [self._doc(c, 43)["f"], int(round(self._doc(c, 43)["p"]))])
        self.assertEqual(out["ultimo"], "2026-10")
        self.assertTrue(any("sem dados" in a and "2026-11" in a for a in dbg["avisos"]))

    def test_pagina_quando_a_api_devolve_menos_que_o_total(self):
        pub = ["2026-09", "2026-10"]
        self._roda(self._get(pub, linhas_por_pagina=1000), hoje=dt.date(2026, 10, 20), inicio="2026-09")
        d = json.loads(self.arq.read_text(encoding="utf-8"))
        self.assertEqual(len(d["meses"]["2026-10"]), 5670)  # todas as páginas foram lidas

    def test_segunda_execucao_so_refaz_o_ultimo_mes_guardado(self):
        pub = ["2026-08", "2026-09"]
        get = self._get(pub)
        self._roda(get, hoje=dt.date(2026, 9, 20), inicio="2026-08")
        n1 = len(get.chamadas)
        self._roda(get, hoje=dt.date(2026, 9, 21), inicio="2026-08")
        self.assertEqual(len(get.chamadas) - n1, 1)  # só 2026-09 de novo (e a população já estava guardada)
        antes = self.arq.read_text(encoding="utf-8")
        self._roda(get, hoje=dt.date(2026, 9, 22), inicio="2026-08")
        self.assertEqual(self.arq.read_text(encoding="utf-8"), antes)  # arquivo idêntico: nenhum commit à toa

    def test_recusa_mes_incompleto_e_nao_guarda(self):
        pub = ["2026-08", "2026-09"]
        get = self._get(pub, escala=lambda ym: 0.3 if ym == "2026-09" else 1.0)  # setembro com 30% das famílias
        out, dbg = self._roda(get, hoje=dt.date(2026, 9, 20), inicio="2026-08")
        d = json.loads(self.arq.read_text(encoding="utf-8"))
        self.assertEqual(list(d["meses"]), ["2026-08"])
        self.assertTrue(any("recusado" in x and "2026-09" in x for x in dbg["erros"] + dbg["avisos"]))

    def test_mes_recusado_depois_de_historico_e_so_aviso_mas_no_primeiro_download_e_erro(self):
        pub = ["2026-08", "2026-09"]
        ruim = self._get(pub, escala=lambda ym: 0.3 if ym == "2026-09" else 1.0)
        self._roda(self._get(["2026-08"]), hoje=dt.date(2026, 8, 20), inicio="2026-08")  # histórico guardado
        _, dbg = self._roda(ruim, hoje=dt.date(2026, 9, 20), inicio="2026-08")
        self.assertEqual(dbg["erros"], [])
        self.assertTrue(any("recusado" in a for a in dbg["avisos"]))

    def test_duas_falhas_seguidas_abortam(self):
        pub = ["2026-08", "2026-09", "2026-10"]
        with self.assertRaises(RuntimeError):
            self._roda(self._get(pub, falha_em=("2026-10", "2026-09")), hoje=dt.date(2026, 10, 20), inicio="2026-08")

    def _html(self, url):
        class Html:
            status_code, headers, text, content = 200, {"content-type": "text/html"}, "<html>aviso</html>", b"<html>aviso</html>"

            def json(self):
                raise ValueError("Expecting value")
        Html.url = url
        return lambda u, params=None, **kw: FakeResp(self._sidra_pop()) if "/t/6579/" in u else Html()

    def test_pagina_html_no_lugar_do_json_dispara_a_sonda_uma_vez(self):
        with mock.patch.object(r, "bf_sonda") as sonda:
            with self.assertRaises(RuntimeError) as cm:
                self._roda(self._html("https://www.gov.br/captcha"), hoje=dt.date(2026, 10, 20), inicio="2026-08")
        self.assertEqual(sonda.call_count, 1)
        self.assertIn("captcha", str(cm.exception.__cause__))
        self.assertFalse(self.arq.exists())

    def test_mds_em_manutencao_nao_derruba_o_robo_nem_apaga_o_que_ja_existe(self):
        pub = ["2026-08", "2026-09", "2026-10"]
        self._roda(self._get(pub), hoje=dt.date(2026, 10, 20), inicio="2026-08")
        antes = self.arq.read_text(encoding="utf-8")
        with mock.patch.object(r, "bf_sonda") as sonda:
            out, dbg = self._roda(self._html("https://www.gov.br/mds/pt-br/avisos"), hoje=dt.date(2026, 11, 13), inicio="2026-08")
        self.assertIsNone(out)
        self.assertEqual(sonda.call_count, 0)
        self.assertEqual(dbg["erros"], [])
        self.assertTrue(any("fora do ar" in a for a in dbg["avisos"]))
        self.assertEqual(self.arq.read_text(encoding="utf-8"), antes)

    def test_confere_mes_pega_unidade_e_total_absurdos(self):
        bom = {c: [3400, 8500, 2.3e6] for c in self.codigos}
        self.assertIsNone(r.bf_confere_mes("2026-10", bom, None))
        self.assertIn("municípios", r.bf_confere_mes("2026-10", dict(list(bom.items())[:100]), None))
        self.assertIn("milhões", r.bf_confere_mes("2026-10", {c: [1, 2, 680.0] for c in self.codigos}, None))
        self.assertIn("benefício médio", r.bf_confere_mes("2026-10", {c: [3400, 8500, 2.3e5] for c in self.codigos}, None))
        self.assertIn("pessoas", r.bf_confere_mes("2026-10", {c: [3400, 1700, 2.3e6] for c in self.codigos}, None))

    def test_populacao_recusa_resposta_incompleta(self):
        cab = {"V": "Valor", "D1C": "Município (Código)", "D1N": "Município", "D3C": "Ano (Código)"}
        curta = [cab] + [{"V": "1000", "D1C": "2927408", "D1N": "Salvador - BA", "D3C": "2026"}]
        with mock.patch.object(r, "get", lambda *a, **k: FakeResp(curta)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.bf_populacao()

    def test_meses_candidatos_vao_de_2023_03_ate_o_mes_atual(self):
        with mock.patch.object(r, "BF_INICIO", "2023-03"):
            m = r.bf_meses_candidatos(dt.date(2026, 11, 13))
        self.assertEqual(m[0], "2023-03")
        self.assertEqual(m[-1], "2026-11")
        self.assertEqual(len(m), 45)


def r_uf(codigo6):
    return {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE",
            "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS", "51": "MT", "52": "GO", "53": "DF"}[codigo6[:2]]


if __name__ == "__main__":
    unittest.main()
