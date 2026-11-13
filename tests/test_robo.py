import datetime as dt
import sys
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
    CAB_MENSAL = {"NC": "Nível Territorial (Código)", "NN": "Nível Territorial", "MC": "Unidade de Medida (Código)", "MN": "Unidade de Medida", "V": "Valor",
                  "D1C": "Brasil (Código)", "D1N": "Brasil", "D2C": "Variável (Código)", "D2N": "Variável", "D3C": "Mês (Código)", "D3N": "Mês",
                  "D4C": "Atividades (Código)", "D4N": "Atividades"}

    def _ibge(self, atividades=("1 Indústria geral",), com_variacoes=True, n=62):
        pers = [f"{2021 + (i + 7) // 12}{(i + 7) % 12 + 1:02d}" for i in range(n)]
        vars_ = [("A", "Número-índice (2022=100)", "Número-índice", lambda i: 100 + 0.1 * i),
                 ("B", "Número-índice com ajuste sazonal (2022=100)", "Número-índice", lambda i: 101 + 0.1 * i)]
        if com_variacoes:
            vars_ += [("C", "Variação mês/mês imediatamente anterior, com ajuste sazonal", "%", lambda i: 0.1),
                      ("D", "Variação mês/mesmo mês do ano anterior", "%", lambda i: 1.2),
                      ("E", "Variação acumulada em 12 meses", "%", lambda i: 1.1),
                      ("F", "Variação acumulada no ano", "%", lambda i: 9.9)]
        vars_ += [("G", "Receita nominal de vendas", "Número-índice", lambda i: 500.0)]
        linhas = [dict(self.CAB_MENSAL)]
        for at in atividades:
            for i, p in enumerate(pers):
                for cod, nome, un, f in vars_:
                    linhas.append({"NC": "1", "MN": un, "V": f"{f(i):.2f}", "D1C": "1", "D1N": "Brasil", "D2C": cod, "D2N": nome, "D3C": p, "D3N": p, "D4C": "9", "D4N": at})
        return linhas

    META = {"variaveis": [{"id": 1, "nome": "x"}], "classificacoes": [{"id": 544, "nome": "Atividades", "categorias": [
        {"id": 1, "nome": "1 Indústria geral"}, {"id": 2, "nome": "2 Indústrias extrativas"}, {"id": 3, "nome": "Comércio varejista"}, {"id": 4, "nome": "Comércio varejista ampliado"}]}]}

    def _get_ibge(self, linhas, urls=None):
        def get(url, *a, **k):
            if urls is not None:
                urls.append(url)
            return FakeResp(self.META if "metadados" in url else linhas)
        return get

    def test_industria_le_variacoes_do_ibge_e_restringe_a_classificacao(self):
        urls = []
        with mock.patch.object(r, "get", self._get_ibge(self._ibge(), urls)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.producao_industrial()
        self.assertEqual(set(out), {"sa", "idx", "mm", "yoy", "a12"})
        self.assertEqual(len(out["sa"]), 62)
        self.assertEqual(out["mm"][-1][1], 0.1)   # variação oficial, não calculada
        self.assertEqual(out["yoy"][-1][1], 1.2)
        self.assertEqual(out["a12"][-1][1], 1.1)
        self.assertRegex(out["sa"][-1][0], r"^\d{4}-\d{2}$")
        self.assertTrue(any("/c544/1" in u and "/v/all" in u for u in urls), urls)  # só 'indústria geral'
        self.assertTrue(any("calculadas aqui: nenhuma" in a for a in dbg["avisos"]))
        ignoradas = " ".join(a for a in dbg["avisos"] if a.startswith("Indústria: linhas ignoradas"))
        self.assertIn("Receita nominal", ignoradas)       # receita e acumulado no ano ficam de fora
        self.assertIn("acumulada no ano", ignoradas)

    def test_calcula_variacoes_quando_o_ibge_nao_devolve(self):
        with mock.patch.object(r, "get", self._get_ibge(self._ibge(com_variacoes=False))), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.producao_industrial()
        self.assertAlmostEqual(out["mm"][-1][1], round((101 + 0.1 * 61) / (101 + 0.1 * 60) * 100 - 100, 1), places=1)
        self.assertAlmostEqual(out["yoy"][-1][1], round((100 + 0.1 * 61) / (100 + 0.1 * 49) * 100 - 100, 1), places=1)
        self.assertGreater(len(out["a12"]), 30)
        self.assertTrue(any("calculadas aqui: ['mm', 'yoy', 'a12']" in a for a in dbg["avisos"]))

    def test_varejo_restrito_e_ampliado(self):
        meta_varejo = self.META
        linhas = self._ibge(atividades=("Comércio varejista", "Comércio varejista ampliado"))
        with mock.patch.object(r, "get", self._get_ibge(linhas)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            out = r.varejo()
        self.assertEqual(set(out), {"restrito", "ampliado"})
        self.assertEqual(len(out["ampliado"]["sa"]), 62)

    def test_varejo_sem_ampliado_segue_so_com_restrito(self):
        with mock.patch.object(r, "get", self._get_ibge(self._ibge(atividades=("Comércio varejista",)))), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.varejo()
        self.assertEqual(set(out), {"restrito"})
        self.assertTrue(any("Varejo/ampliado" in a for a in dbg["avisos"]))

    def test_ibge_recusa_atividade_ausente_e_indice_absurdo(self):
        with mock.patch.object(r, "get", self._get_ibge(self._ibge(atividades=("Outra coisa",)))), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.producao_industrial()
        linhas = self._ibge()
        for x in linhas[1:]:
            if x["D2C"] in ("A", "B"):
                x["V"] = "9000.00"
        with mock.patch.object(r, "get", self._get_ibge(linhas)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.producao_industrial()

    def test_ibge_segue_sem_metadados(self):
        linhas = self._ibge()

        def get(url, *a, **k):
            if "metadados" in url:
                raise RuntimeError("fora do ar")
            return FakeResp(linhas)
        with mock.patch.object(r, "get", get), mock.patch.object(r, "debug", {"avisos": [], "erros": []}) as dbg:
            out = r.producao_industrial()
        self.assertEqual(len(out["sa"]), 62)
        self.assertTrue(any("metadados indisponíveis" in a for a in dbg["avisos"]))

    def test_desloca_periodo(self):
        self.assertEqual(r._desloca("202601", -1), "202512")
        self.assertEqual(r._desloca("202612", 1), "202701")
        self.assertEqual(r._desloca("202603", -12), "202503")
        self.assertEqual(r.medida_ibge("Número-índice com ajuste sazonal (2022=100)", "Número-índice"), "sa")
        self.assertEqual(r.medida_ibge("Variação acumulada no ano", "%"), None)
        self.assertEqual(r.medida_ibge("Variação mês/mesmo mês do ano anterior", "%"), "yoy")


if __name__ == "__main__":
    unittest.main()
