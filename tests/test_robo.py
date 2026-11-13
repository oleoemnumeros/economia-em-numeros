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

    def test_caged_formato_e_guarda(self):
        ok = [(dt.date(2026, m, 1), 100000.0 + m) for m in range(1, 10)] + [(dt.date(2025, m, 1), 80000.0) for m in range(1, 13)]
        with mock.patch.object(r, "sgs", lambda *a: sorted(ok)), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            self.assertEqual(r.caged()["saldo"][-1], ["2026-09", 100009.0])
        estranha = [(dt.date(2025, m, 1), 20_000_000.0) for m in range(1, 13)]  # estoque de empregos, não saldo
        with mock.patch.object(r, "sgs", lambda *a: estranha), mock.patch.object(r, "debug", {"avisos": [], "erros": []}):
            with self.assertRaises(RuntimeError):
                r.caged()


if __name__ == "__main__":
    unittest.main()
