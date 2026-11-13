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


def trimestres(ini: str, fim: str):
    y, q = int(ini[:4]), int(ini[4:])
    out = []
    while f"{y}{q:02d}" <= fim:
        out.append(f"{y}{q:02d}")
        q += 1
        if q > 4:
            y, q = y + 1, 1
    return out


UF_COD = ["11", "12", "13", "14", "15", "16", "17", "21", "22", "23", "24", "25", "26", "27", "28", "29", "31", "32",
          "33", "35", "41", "42", "43", "50", "51", "52", "53"]


def emprego_exemplo() -> dict:
    tris = trimestres("202301", "202602")
    trimestral = {"1": {"nome": "Brasil", "serie": [[t, f"{t[4:]}º tri {t[:4]}", round(7.0 - i * 0.1, 1)] for i, t in enumerate(tris)]}}
    for k, cod in enumerate(UF_COD):
        trimestral[cod] = {"nome": f"UF {cod}", "serie": [[t, f"{t[4:]}º tri {t[:4]}", round(4.0 + (k % 9) * 0.7 - i * 0.05, 1)] for i, t in enumerate(tris)]}
    movel = []
    y, m = 2023, 3
    while (y, m) <= (2026, 6):
        movel.append([f"{y}{m:02d}", f"mês {m}", round(6.5 - len(movel) * 0.05, 1)])
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return {"trimestral": trimestral, "movel": movel}


def caged_exemplo() -> dict:
    return {"saldo": [[m, (-1) ** i * 90000 + i * 500] for i, m in enumerate(meses("2020-01", "2026-09"))]}


def cambio_exemplo() -> dict:
    d, i, dias = dt.date(2025, 10, 8), 0, []
    while d <= dt.date(2026, 11, 12):
        if d.weekday() < 5:
            dias.append([d.isoformat(), round(5.2 + ((i * 3) % 11) / 20 - i * 0.0005, 4)])
            i += 1
        d += dt.timedelta(days=1)
    mensal = [[m, round(4.0 + (k % 24) / 10, 4), round(4.0 + ((k * 5) % 24) / 10, 4)] for k, m in enumerate(meses("2016-01", "2026-11"))]
    mensal[-1][2] = dias[-1][1]
    for m in mensal:
        if m[0] == "2025-12":
            m[2] = 5.31  # fim do ano anterior, usado nos testes
    return {"diario": dias, "mensal": mensal}


def ibc_exemplo() -> dict:
    ms = meses("2022-01", "2026-08")
    return {"sa": [[m, round(140 + k * 0.15 + (k % 3) * 0.2, 2)] for k, m in enumerate(ms)],
            "nsa": [[m, round(140 + k * 0.15 + ((k % 12) - 6) * 0.9, 2)] for k, m in enumerate(ms)]}


def pib_exemplo() -> dict:
    return {"trimestral": [{"t": t, "yoy": round(2.5 - i * 0.1, 1), "a4": round(3.0 - i * 0.12, 1), "qoq": round(((-1) ** i) * 0.3 + 0.2, 1)}
                           for i, t in enumerate(trimestres("202301", "202602"))]}


def fiscal_exemplo() -> dict:
    """Convenção do Banco Central: NFSP positiva = déficit. A dívida bruta vai até set/2026; as demais, até ago/2026."""
    ate_bruta, ate_resto = meses("2015-01", "2026-09"), meses("2015-01", "2026-08")
    dbgg = [[m, round(58 + k * 0.18 + (k % 5) * 0.1, 2)] for k, m in enumerate(ate_bruta)]
    dlsp = [[m, round(30 + k * 0.22 + (k % 4) * 0.1, 2)] for k, m in enumerate(ate_resto)]
    primario = [[m, round(0.3 + ((k * 7) % 9) / 10, 2)] for k, m in enumerate(ate_resto)]
    nominal = [[m, round(5.5 + ((k * 5) % 13) / 10, 2)] for k, m in enumerate(ate_resto)]
    primario[-1][1], primario[-13][1] = 0.75, 0.40      # déficit primário de 0,75% do PIB em ago/2026 (0,40% um ano antes)
    nominal[-1][1] = 8.10
    return {"dbgg": dbgg, "dlsp": dlsp, "primario": primario, "nominal": nominal}


def credito_exemplo() -> dict:
    """Juros e inadimplência até set/2026; endividamento e comprometimento (que saem com mais defasagem) até ago/2026."""
    a, b = meses("2016-01", "2026-09"), meses("2016-01", "2026-08")
    inad_pf = [[m, round(3.6 + ((k * 3) % 9) / 10, 2)] for k, m in enumerate(a)]
    inad_livre = [[m, round(5.2 + ((k * 3) % 9) / 10, 2)] for k, m in enumerate(a)]
    juros_pf = [[m, round(40 + ((k * 5) % 17) / 2, 2)] for k, m in enumerate(a)]
    juros_livre = [[m, round(52 + ((k * 5) % 17) / 2, 2)] for k, m in enumerate(a)]
    endiv = [[m, round(42 + k * 0.06 + (k % 4) * 0.1, 2)] for k, m in enumerate(b)]
    comp = [[m, round(22 + k * 0.05 + (k % 4) * 0.1, 2)] for k, m in enumerate(b)]
    juros_livre[-1][1], juros_livre[-13][1] = 62.4, 55.0     # +7,4 p.p. em 12 meses
    juros_pf[-1][1], inad_pf[-1][1], inad_livre[-1][1] = 48.0, 6.0, 8.1
    endiv[-1][1], comp[-1][1], endiv[-13][1] = 50.1, 29.0, 48.6
    return {"inad_pf": inad_pf, "inad_livre_pf": inad_livre, "juros_pf": juros_pf, "juros_livre_pf": juros_livre, "endividamento": endiv, "comprometimento": comp}


def _ibge_exemplo(ate: str, mm_ult: float, yoy_ult: float, a12_ult: float, base: float = 100.0) -> dict:
    ms = meses("2021-08", ate)
    sa = [[m, round(base + k * 0.05 + (k % 3) * 0.4, 1)] for k, m in enumerate(ms)]
    idx = [[m, round(base - 1 + k * 0.05 + ((k % 12) - 6) * 0.6, 1)] for k, m in enumerate(ms)]
    mm = [[m, round(((k * 7) % 11 - 5) / 5, 1)] for k, m in enumerate(ms)]
    yoy = [[m, round(((k * 5) % 13 - 6) / 4, 1)] for k, m in enumerate(ms)]
    a12 = [[m, round(((k * 3) % 9 - 4) / 4, 1)] for k, m in enumerate(ms)]
    mm[-1][1], yoy[-1][1], a12[-1][1] = mm_ult, yoy_ult, a12_ult
    return {"sa": sa, "idx": idx, "mm": mm, "yoy": yoy, "a12": a12}


def industria_exemplo() -> dict:
    return _ibge_exemplo("2026-09", -0.8, -1.2, 0.6)


def varejo_exemplo() -> dict:
    """Varejo sai um mês depois da indústria: vai até ago/2026."""
    return {"restrito": _ibge_exemplo("2026-08", 0.4, 1.9, 1.5, 104.0), "ampliado": _ibge_exemplo("2026-08", 0.2, 1.1, 0.9, 102.0)}


def externo_exemplo() -> dict:
    """Setor externo até set/2026 (BCB, US$ milhões); reservas no fim de cada mês, com a leitura mais recente de 12/11/2026."""
    ms = meses("2016-01", "2026-09")
    ca_m = [[m, round(-4200 + ((k * 7) % 13 - 6) * 450 + (1500 if k % 12 in (2, 3) else 0), 1)] for k, m in enumerate(ms)]
    ca_12 = [[ms[k], round(sum(v for _, v in ca_m[k - 11:k + 1]), 1)] for k in range(11, len(ms))]
    ca_pib = [[m, round(v / 2_250_000 * 100, 2)] for m, v in ca_12]
    idp = [[m, round(5200 + ((k * 5) % 11) * 300, 1)] for k, m in enumerate(ms)]
    res = [[m, round(340_000 + ((k * 3) % 17) * 1500, 1)] for k, m in enumerate(meses("2016-01", "2026-11"))]
    res[-1][1] = 358_200.0
    return {"ca_mensal": ca_m, "ca_12m": ca_12, "ca_pib": ca_pib, "idp_mensal": idp, "reservas": res, "reservas_ultima": ["2026-11-12", 358_200.0]}


def balanca_exemplo() -> dict:
    """Exportações e importações mensais (US$ milhões) até out/2026, como o Comex em Números publica."""
    ms = meses("2016-01", "2026-10")
    return {"mes": ms[-1], "export": [[m, round(25_000 + ((k * 5) % 9) * 900 + k * 20, 1)] for k, m in enumerate(ms)],
            "import": [[m, round(20_000 + ((k * 7) % 11) * 700 + k * 15, 1)] for k, m in enumerate(ms)]}


def bf_exemplo() -> dict:
    """Bolsa Família por município (dados sintéticos): 3 estados, 123 municípios, 15 meses; nomes repetidos entre estados e dentro de um estado."""
    estados = {"29": ("BA", 45), "35": ("SP", 45), "12": ("AC", 33)}
    nomes, pop, meses_bf = {}, {}, {}
    cods = []
    for uf, (sigla, n) in estados.items():
        for i in range(1, n + 1):
            cod = f"{uf}{i:04d}"
            nome = {1: "Bom Jesus", 2: "Salvador" if uf == "29" else f"Cidade {uf}-2", 3: "Poá", 4: "Poa" if uf == "35" else f"Cidade {uf}-4"}.get(i, f"Cidade {uf}-{i}")
            nomes[cod] = [nome, sigla]
            pop[cod] = 9000 + (i * 7919) % 90000
            cods.append(cod)
    del pop["120007"]            # um município sem população: a proporção some, o resto continua
    for k, ym in enumerate(meses("2025-08", "2026-10")):
        mes = {}
        for j, cod in enumerate(cods):
            if ym == "2026-10" and cod == "290005":
                continue          # sumiu do último mês
            if cod == "290006" and ym != "2026-10":
                continue          # só aparece no último mês
            f = 1500 + (j * 37) % 2500 + k * 6
            mes[cod] = [f, int(f * 2.6), round(f * 683.5, 2)]
        meses_bf[ym] = mes
    # os cinco primeiros estados da lista (códigos soltos) não têm nome: ficam de fora
    meses_bf["2026-10"]["999999"] = [100, 250, 68000.0]
    return {"fonte": "MDS (MI Social)", "pop_ano": "2025", "nomes": nomes, "pop": pop, "meses": meses_bf}


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
        "desocupacao": emprego_exemplo(),
        "caged": caged_exemplo(),
        "cambio": cambio_exemplo(),
        "ibc": ibc_exemplo(),
        "pib": pib_exemplo(),
        "fiscal": fiscal_exemplo(),
        "credito": credito_exemplo(),
        "industria": industria_exemplo(),
        "varejo": varejo_exemplo(),
        "externo": externo_exemplo(),
        "balanca": balanca_exemplo(),
        "atas": {"282": {"pdf": "https://www.bcb.gov.br/content/copom/atascopom/Copom282-not20261104282.pdf"}},
        "focus": {"data": "2026-11-10", "itens": [
            {"indicador": "Selic", "ano": 2026, "mediana": 13.5, "semana_anterior": 13.5},
            {"indicador": "Selic", "ano": 2027, "mediana": 12.5, "semana_anterior": 12.75},
            {"indicador": "IPCA", "ano": 2026, "mediana": 4.4, "semana_anterior": 4.3},
            {"indicador": "IPCA", "ano": 2027, "mediana": 4.0, "semana_anterior": 4.0},
            {"indicador": "PIB Total", "ano": 2026, "mediana": 2.1, "semana_anterior": 2.15},
            {"indicador": "PIB Total", "ano": 2027, "mediana": 1.8, "semana_anterior": 1.8},
            {"indicador": "Câmbio", "ano": 2026, "mediana": 5.6, "semana_anterior": 5.6},
            {"indicador": "Câmbio", "ano": 2027, "mediana": 5.7, "semana_anterior": 5.7},
            {"indicador": "Resultado primário", "ano": 2026, "mediana": -0.6, "semana_anterior": -0.6},
            {"indicador": "Resultado primário", "ano": 2027, "mediana": -0.5, "semana_anterior": -0.55},
            {"indicador": "Dívida bruta do governo geral", "ano": 2026, "mediana": 81.2, "semana_anterior": 81.0},
            {"indicador": "Dívida bruta do governo geral", "ano": 2027, "mediana": 84.0, "semana_anterior": 84.0}]},
    }


def gravar(caminho: Path) -> Path:
    caminho.write_text(json.dumps(dados_exemplo(), ensure_ascii=False), encoding="utf-8")
    return caminho


def gravar_bf(caminho: Path) -> Path:
    caminho.write_text(json.dumps(bf_exemplo(), ensure_ascii=False), encoding="utf-8")
    return caminho
