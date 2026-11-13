"""Dados sintéticos só para testar o gerador (não são dados reais e nunca vão para o site)."""
import datetime as dt
import json
from pathlib import Path

AREAS = {
    "belem": ("Belém", "PA"), "fortaleza": ("Fortaleza", "CE"), "recife": ("Recife", "PE"), "salvador": ("Salvador", "BA"),
    "belo-horizonte": ("Belo Horizonte", "MG"), "grande-vitoria": ("Grande Vitória", "ES"), "rio-de-janeiro": ("Rio de Janeiro", "RJ"),
    "sao-paulo": ("São Paulo", "SP"), "curitiba": ("Curitiba", "PR"), "porto-alegre": ("Porto Alegre", "RS"),
    "rio-branco": ("Rio Branco", "AC"), "sao-luis": ("São Luís", "MA"), "aracaju": ("Aracaju", "SE"),
    "campo-grande": ("Campo Grande", "MS"), "goiania": ("Goiânia", "GO"), "brasilia": ("Brasília", "DF"),
}


def meses(ini: str, fim: str):
    y, m = int(ini[:4]), int(ini[5:])
    out = []
    while f"{y}-{m:02d}" <= fim:
        out.append(f"{y}-{m:02d}")
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def dados_exemplo() -> dict:
    ms = meses("2000-01", "2026-09")
    mensal = [[m, round(0.2 + ((i * 7) % 13) / 20, 2)] for i, m in enumerate(ms)]
    acum = [[m, round(3.5 + ((i * 5) % 17) / 10, 2)] for i, m in enumerate(ms)]
    areas = {}
    for k, (slug, (nome, uf)) in enumerate(AREAS.items()):
        am = meses("2024-08", "2026-09")
        areas[slug] = {"nome": nome, "uf": uf,
                       "mensal": [[m, round(0.1 + ((i + k) % 9) / 15, 2)] for i, m in enumerate(am)],
                       "acum12": [[m, round(3.0 + ((i + k * 3) % 21) / 10, 2)] for i, m in enumerate(am)]}
    meta = [["2016-01-01", 14.25], ["2017-01-12", 13.0], ["2020-08-06", 2.0], ["2022-03-18", 11.75], ["2023-08-04", 13.25],
            ["2024-05-10", 10.5], ["2025-06-19", 15.0], ["2026-01-29", 14.75], ["2026-11-05", 13.75]]
    return {
        "gerado_em": "2026-11-13T12:00:00",
        "selic": {"meta": meta, "ultima_data_serie": "2026-11-12"},
        "ipca": {"mensal": mensal, "acum12": acum},
        "areas": areas,
        "focus": {"data": "2026-11-10", "itens": [
            {"indicador": "Selic", "ano": 2026, "mediana": 13.5, "semana_anterior": 13.5},
            {"indicador": "Selic", "ano": 2027, "mediana": 12.5, "semana_anterior": 12.75},
            {"indicador": "IPCA", "ano": 2026, "mediana": 4.4, "semana_anterior": 4.3},
            {"indicador": "IPCA", "ano": 2027, "mediana": 4.0, "semana_anterior": 4.0},
            {"indicador": "PIB Total", "ano": 2026, "mediana": 2.1, "semana_anterior": 2.15},
            {"indicador": "PIB Total", "ano": 2027, "mediana": 1.8, "semana_anterior": 1.8},
            {"indicador": "Câmbio", "ano": 2026, "mediana": 5.6, "semana_anterior": 5.6},
            {"indicador": "Câmbio", "ano": 2027, "mediana": 5.7, "semana_anterior": 5.7}]},
    }


def gravar(caminho: Path) -> Path:
    caminho.write_text(json.dumps(dados_exemplo(), ensure_ascii=False), encoding="utf-8")
    return caminho
