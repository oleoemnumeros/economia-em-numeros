import datetime as dt
import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
