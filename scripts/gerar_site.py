#!/usr/bin/env python3
"""Gerador do site Economia em Números.

Lê data/dados.json (feito por scripts/atualizar.py) e data/copom_calendario.json e escreve as páginas
estáticas em docs/. Uso:
    python scripts/gerar_site.py                     # site de verdade
    python scripts/gerar_site.py --dados X --saida Y # outro dado/pasta (testes)
"""
import argparse
import datetime as dt
import html
import json
import math
import re
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SITE = RAIZ / "site"
DOMINIO = "economiaemnumeros.com.br"
BASE = f"https://{DOMINIO}"
# Contador de visitas (GoatCounter: sem cookies, não precisa de aviso de LGPD)
GOAT = '<script data-goatcounter="https://economiaemnumeros.goatcounter.com/count" async src="https://gc.zgo.at/count.js"></script>'

# Família em Números: para incluir um novo portal, acrescente uma linha nesta lista
FAMILIA = [
    ("Óleo em Números", "Petróleo e gás", "https://oleoemnumeros.com.br/", "#B45309"),
    ("Comex em Números", "Exportações e importações", "https://comexemnumeros.com.br/", "#0b7a68"),
    ("Voo em Números", "Pontualidade aérea", "https://vooemnumeros.com.br/", "#7C5CE0"),
    ("Economia em Números", "Juros, preços e emprego", "https://economiaemnumeros.com.br/", "var(--eco)"),
]
NAV = [("/juros/", "Juros e Copom"), ("/inflacao/", "Inflação"), ("/calculadora/", "Calculadora"), ("/sobre/", "Sobre")]

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]
MES_CURTO = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
MUNICIPIOS = {"brasilia", "goiania", "campo-grande", "rio-branco", "sao-luis", "aracaju"}  # as outras 10 áreas são regiões metropolitanas
NFSP_POSITIVO_E_DEFICIT = True  # convenção das séries de necessidades de financiamento (NFSP) do Banco Central: valor positivo = déficit
F_SELIC = "Banco Central do Brasil (SGS 432)"
F_PNAD_BR = "IBGE, PNAD Contínua (SIDRA, tabela 6381)"
F_PNAD_UF = "IBGE, PNAD Contínua (SIDRA, tabela 4099)"
F_CAGED = "Novo Caged (Ministério do Trabalho e Emprego), via Banco Central (SGS 28763)"
F_IPCA = "IBGE, via Banco Central do Brasil (SGS 433 e 13522)"
F_IPCA_AREA = "IBGE (SIDRA, tabela 7060); série do Brasil: SGS 13522 do Banco Central"
F_PIB = "IBGE, Contas Nacionais Trimestrais (SIDRA, tabela 5932)"
F_IBC = "Banco Central do Brasil (SGS 24364 e 24363)"
F_CAMBIO = "Banco Central do Brasil (SGS 1, dólar venda)"
F_CRED_JUROS = "Banco Central do Brasil (SGS 20716 e 20740; Selic: SGS 432)"
F_CRED_INAD = "Banco Central do Brasil (SGS 21084 e 21112)"
F_CRED_ENDIV = "Banco Central do Brasil (SGS 29037)"
F_CRED_COMP = "Banco Central do Brasil (SGS 29034)"
F_PIM = "IBGE, Pesquisa Industrial Mensal - Produção Física (SIDRA, tabela 8888)"
F_PMC = "IBGE, Pesquisa Mensal de Comércio (SIDRA, tabela 8880)"
CRED_CHAVES = ("inad_pf", "inad_livre_pf", "juros_pf", "juros_livre_pf", "endividamento", "comprometimento")
NUM_PRIMEIRA_REUNIAO = 260  # 30–31/01/2024; mesma regra do robô (conferida com as atas 266, 268, 274 e 276 a 281)
ATAS_LISTA = "https://www.bcb.gov.br/publicacoes/atascopom/cronologicos"
UFS = {  # código IBGE -> (endereço, nome, sigla)
    "11": ("rondonia", "Rondônia", "RO"), "12": ("acre", "Acre", "AC"), "13": ("amazonas", "Amazonas", "AM"), "14": ("roraima", "Roraima", "RR"),
    "15": ("para", "Pará", "PA"), "16": ("amapa", "Amapá", "AP"), "17": ("tocantins", "Tocantins", "TO"), "21": ("maranhao", "Maranhão", "MA"),
    "22": ("piaui", "Piauí", "PI"), "23": ("ceara", "Ceará", "CE"), "24": ("rio-grande-do-norte", "Rio Grande do Norte", "RN"),
    "25": ("paraiba", "Paraíba", "PB"), "26": ("pernambuco", "Pernambuco", "PE"), "27": ("alagoas", "Alagoas", "AL"), "28": ("sergipe", "Sergipe", "SE"),
    "29": ("bahia", "Bahia", "BA"), "31": ("minas-gerais", "Minas Gerais", "MG"), "32": ("espirito-santo", "Espírito Santo", "ES"),
    "33": ("rio-de-janeiro", "Rio de Janeiro", "RJ"), "35": ("sao-paulo", "São Paulo", "SP"), "41": ("parana", "Paraná", "PR"),
    "42": ("santa-catarina", "Santa Catarina", "SC"), "43": ("rio-grande-do-sul", "Rio Grande do Sul", "RS"), "50": ("mato-grosso-do-sul", "Mato Grosso do Sul", "MS"),
    "51": ("mato-grosso", "Mato Grosso", "MT"), "52": ("goias", "Goiás", "GO"), "53": ("distrito-federal", "Distrito Federal", "DF"),
}


# ------------------------------------------------------------------ formatação
def esc(s) -> str:
    return html.escape(str(s), quote=True)


def nf(v, d=1) -> str:
    s = f"{v:,.{d}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".").replace("-", "−")  # sinal de menos de verdade


def pct(v, d=2) -> str:
    return nf(v, d) + "%"


def sinal(v, d=2) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "") + nf(abs(v), d)


def mes_nome(p: str) -> str:
    return f"{MESES[int(p[5:]) - 1]} de {p[:4]}"


def mes_curto(p: str) -> str:
    return f"{MES_CURTO[int(p[5:]) - 1]}/{p[:4]}"


def mes_curtinho(p: str) -> str:
    return f"{MES_CURTO[int(p[5:]) - 1]}/{p[2:4]}"


def data_br(d: dt.date) -> str:
    return d.strftime("%d/%m/%Y")


def periodo_reuniao(ini: dt.date, fim: dt.date) -> str:
    if ini.month == fim.month:
        return f"{ini.day} e {fim.day} de {MESES[fim.month - 1]}"
    return f"{ini.day} de {MESES[ini.month - 1]} e {fim.day} de {MESES[fim.month - 1]}"


def periodo_curto(ini: dt.date, fim: dt.date) -> str:
    return f"{ini.day} e {fim.day} {MES_CURTO[fim.month - 1]}"


def periodo_tabela(ini: dt.date, fim: dt.date) -> str:
    """Versão compacta para tabelas estreitas: '3 e 4 nov 2026' ou '31 jul e 1 ago 2026'."""
    if ini.month == fim.month:
        return f"{ini.day} e {fim.day} {MES_CURTO[fim.month - 1]} {fim.year}"
    return f"{ini.day} {MES_CURTO[ini.month - 1]} e {fim.day} {MES_CURTO[fim.month - 1]} {fim.year}"


def ordinal_f(n: int) -> str:
    return f"{n}ª"


EM = {  # "em" + artigo: "na Bahia", "no Ceará", "em São Paulo"
    "RO": "em Rondônia", "AC": "no Acre", "AM": "no Amazonas", "RR": "em Roraima", "PA": "no Pará", "AP": "no Amapá", "TO": "no Tocantins",
    "MA": "no Maranhão", "PI": "no Piauí", "CE": "no Ceará", "RN": "no Rio Grande do Norte", "PB": "na Paraíba", "PE": "em Pernambuco",
    "AL": "em Alagoas", "SE": "em Sergipe", "BA": "na Bahia", "MG": "em Minas Gerais", "ES": "no Espírito Santo", "RJ": "no Rio de Janeiro",
    "SP": "em São Paulo", "PR": "no Paraná", "SC": "em Santa Catarina", "RS": "no Rio Grande do Sul", "MS": "no Mato Grosso do Sul",
    "MT": "no Mato Grosso", "GO": "em Goiás", "DF": "no Distrito Federal",
}


def rot_tri(cod: str, longo: bool = False) -> str:
    """'202602' -> '2º tri/26' (curto) ou '2º trimestre de 2026'."""
    q, ano = int(cod[4:]), cod[:4]
    return f"{q}º trimestre de {ano}" if longo else f"{q}º tri/{ano[2:]}"


def rot_movel(cod: str) -> str:
    """Trimestre móvel pelo mês final: '202606' -> 'abr-mai-jun de 2026'."""
    m, ano = int(cod[4:]), cod[:4]
    nomes = [MES_CURTO[(m - 3 + i) % 12] for i in range(3)]
    return "-".join(nomes) + f" de {ano}"


def rot_movel_curto(cod: str) -> str:
    """'202606' -> 'abr-jun/2026' (para tabelas estreitas)."""
    m, ano = int(cod[4:]), cod[:4]
    return f"{MES_CURTO[(m - 3) % 12]}-{MES_CURTO[m - 1]}/{ano}"


def mes_antes(m: str, n: int) -> str:
    """'2026-09', 12 -> '2025-09'."""
    k = int(m[:4]) * 12 + int(m[5:]) - 1 - n
    return f"{k // 12}-{k % 12 + 1:02d}"


def resultado_txt(v: float) -> str:
    """Resultado fiscal em % do PIB com sinal natural: positivo = superávit, negativo = déficit."""
    if round(abs(v), 1) == 0:
        return "resultado próximo de zero"
    return f"{'superávit' if v > 0 else 'déficit'} de {pct(abs(v), 1)} do PIB"


def var_pct(v, ref):
    return (v / ref - 1) * 100 if ref else None


def verbo_var(v, d=1, pos="cresceu", neg="recuou") -> str:
    """'cresceu 0,4%', 'recuou 0,3%' ou 'ficou estável' (quando arredonda para zero)."""
    if round(abs(v), d) == 0:
        return "ficou estável"
    return f"{pos if v > 0 else neg} {nf(abs(v), d)}%"


def pct_sinal(v, d=1) -> str:
    return "–" if v is None else f"{sinal(v, d)}%"


def saldo_txt(v: float) -> str:
    return ("+" if v > 0 else "−" if v < 0 else "") + nf(abs(v), 0)


# ------------------------------------------------------------------ dados
class Base:
    def __init__(self, dados: dict, calendario: dict, hoje: dt.date, resumos: dict | None = None):
        self.d = dados
        self.hoje = hoje
        self.mud = [(dt.date.fromisoformat(a), float(v)) for a, v in dados["selic"]["meta"]]
        self.ipca_m = {k: float(v) for k, v in dados["ipca"]["mensal"]}
        self.ipca_12 = {k: float(v) for k, v in dados["ipca"]["acum12"]}
        self.ref = max(self.ipca_12)
        self.areas = {}
        for slug, a in (dados.get("areas") or {}).items():
            self.areas[slug] = {"slug": slug, "nome": a["nome"], "uf": a["uf"],
                                "mensal": {k: float(v) for k, v in a["mensal"]}, "acum12": {k: float(v) for k, v in a["acum12"]}}
        # a referência das áreas pode estar um mês atrás do Brasil; usamos o último mês comum
        meses_areas = [max(a["acum12"]) for a in self.areas.values() if a["acum12"]]
        self.ref_areas = min(meses_areas) if meses_areas else None
        self.reunioes = []
        for idx, (ini, fim) in enumerate(calendario["reunioes"]):
            i, f = dt.date.fromisoformat(ini), dt.date.fromisoformat(fim)
            ata = f + dt.timedelta(days=(1 - f.weekday()) % 7 or 7)  # primeira terça-feira depois da reunião
            self.reunioes.append({"ini": i, "fim": f, "ata": ata, "num": NUM_PRIMEIRA_REUNIAO + idx})
        self.focus = dados.get("focus")
        self.atas = dados.get("atas") or {}
        self.resumos = (resumos or {}).get("atas", {})
        self.des = dados.get("desocupacao") or None
        self.caged = dados.get("caged") or None
        self.cambio = dados.get("cambio") or None
        self.pib = (dados.get("pib") or {}).get("trimestral") or None
        self.ibc = dados.get("ibc") or None
        self.fiscal = dados.get("fiscal") or None
        self.credito = dados.get("credito") or None
        self.industria = dados.get("industria") or None
        self.varejo = dados.get("varejo") or None
        self.csvs = {}  # slug -> dados de cada gráfico (viram os arquivos /dados/<slug>.csv)

    # Atas, emprego ----------------------------------------------------------
    def ata_pdf(self, n: int):
        return (self.resumos.get(str(n)) or {}).get("pdf") or (self.atas.get(str(n)) or {}).get("pdf")

    @property
    def tem_emprego(self) -> bool:
        return bool(self.des and "1" in (self.des.get("trimestral") or {}) and self.des.get("movel"))

    @property
    def tem_cambio(self) -> bool:
        return bool(self.cambio and len(self.cambio.get("diario") or []) > 30)

    @property
    def tem_pib(self) -> bool:
        return bool(self.pib and any(r.get("qoq") is not None for r in self.pib))

    @property
    def tem_ibc(self) -> bool:
        return bool(self.ibc and len(self.ibc.get("sa") or []) >= 14 and len(self.ibc.get("nsa") or []) >= 25)

    @property
    def tem_fiscal(self) -> bool:
        return bool(self.fiscal and all(len(self.fiscal.get(k) or []) >= 14 for k in ("dbgg", "dlsp", "primario", "nominal")))

    @property
    def tem_credito(self) -> bool:
        return bool(self.credito and all(len(self.credito.get(k) or []) >= 14 for k in CRED_CHAVES))

    def cred_stats(self) -> dict:
        """Última leitura de cada série de crédito e a diferença para 12 meses antes."""
        res = {}
        for chave in CRED_CHAVES:
            serie = [(m, float(v)) for m, v in self.credito[chave]]
            m, v = serie[-1]
            ant = dict(serie).get(mes_antes(m, 12))
            res[chave] = {"mes": m, "v": v, "dif12": v - ant if ant is not None else None, "serie": serie}
        return res

    def ibge_series(self) -> dict:
        """Indicadores mensais do IBGE que chegaram (indústria, varejo, varejo ampliado), cada um com sa, mm, yoy e (se houver) a12."""
        def ok(med):
            return bool(med) and all(len(med.get(k) or []) >= 14 for k in ("sa", "mm", "yoy"))
        v = self.varejo or {}
        cand = [("ind", "Produção industrial", "A produção industrial", "Indústria", F_PIM, self.industria),
                ("var", "Vendas no varejo", "O volume de vendas do varejo", "Varejo", F_PMC, v.get("restrito")),
                ("amp", "Varejo ampliado", "O volume de vendas do varejo ampliado", "Varejo ampliado", F_PMC, v.get("ampliado"))]
        return {k: {"nome": nome, "sujeito": suj, "curto": curto, "fonte": fonte, "med": med} for k, nome, suj, curto, fonte, med in cand if ok(med)}

    @property
    def tem_ibge(self) -> bool:
        return bool(self.ibge_series())

    @staticmethod
    def ibge_ult(med) -> dict:
        """Última leitura de um indicador do IBGE: mês, índice com ajuste sazonal e as variações desse mês."""
        mm, yoy, a12 = (dict((m, float(x)) for m, x in med.get(k) or []) for k in ("mm", "yoy", "a12"))
        m = max(mm)
        sa = dict((k, float(x)) for k, x in med["sa"])
        return {"mes": m, "sa": sa.get(m), "mm": mm[m], "yoy": yoy.get(m), "a12": a12.get(m)}

    def fis(self, chave: str) -> list:
        return [(m, float(v)) for m, v in self.fiscal[chave]]

    def fis_stats(self) -> dict:
        """Última leitura de cada série fiscal e a diferença para 12 meses antes (em p.p. do PIB)."""
        out = {}
        for chave in ("dbgg", "dlsp"):
            out[chave] = self.fis(chave)
        for chave in ("primario", "nominal"):
            out[chave] = self.fis_resultado(chave)
        res = {}
        for chave, serie in out.items():
            d = dict(serie)
            m, v = serie[-1]
            ant = d.get(mes_antes(m, 12))
            res[chave] = {"mes": m, "v": v, "dif12": v - ant if ant is not None else None, "serie": serie}
        return res

    def fis_resultado(self, chave: str) -> list:
        """Resultado fiscal com sinal 'natural': positivo = superávit, negativo = déficit."""
        return [(m, -v if NFSP_POSITIVO_E_DEFICIT else v) for m, v in self.fis(chave)]

    @property
    def tem_atividade(self) -> bool:
        return self.tem_pib or self.tem_ibc

    def nav(self) -> list:
        itens = [NAV[0]]
        if self.tem_emprego:
            itens.append(("/emprego/", "Emprego"))
        if self.tem_atividade:
            itens.append(("/atividade/", "Atividade"))
        if self.tem_ibge:
            itens.append(("/industria-e-varejo/", "Indústria e varejo"))
        if self.tem_credito:
            itens.append(("/credito/", "Crédito"))
        if self.tem_cambio:
            itens.append(("/cambio/", "Câmbio"))
        if self.tem_fiscal:
            itens.append(("/contas-publicas/", "Contas públicas"))
        return itens + NAV[1:]

    # Câmbio ---------------------------------------------------------------
    def cambio_stats(self) -> dict:
        d = [(dt.date.fromisoformat(a), float(v)) for a, v in self.cambio["diario"]]
        mensal = {m: (med, fim) for m, med, fim in self.cambio.get("mensal", [])}
        data, ult = d[-1]

        def ate(dia):
            vs = [v for x, v in d if x <= dia]
            return vs[-1] if vs else None

        def var(ref):
            return (ult / ref - 1) * 100 if ref else None

        fim_mes_ant = ate(data.replace(day=1) - dt.timedelta(days=1))
        fim_ano_ant = (mensal.get(f"{data.year - 1}-12") or (None, None))[1]
        ult12 = [(x, v) for x, v in d if x > data - dt.timedelta(days=365)]
        linhas = []
        for k in range(len(d) - 1, max(len(d) - 11, 0), -1):
            linhas.append((d[k][0], d[k][1], var_pct(d[k][1], d[k - 1][1])))
        return {"data": data, "ult": ult, "dia": var(d[-2][1]) if len(d) > 1 else None, "mes": var(fim_mes_ant), "ano": var(fim_ano_ant),
                "a12": var(ate(data - dt.timedelta(days=365))), "min12": min(v for _, v in ult12), "max12": max(v for _, v in ult12),
                "serie12": ult12, "linhas": linhas, "mensal": [(m, med) for m, med, _ in self.cambio.get("mensal", [])]}

    # Atividade ------------------------------------------------------------
    def pib_ref(self):
        return next((r for r in reversed(self.pib) if r.get("qoq") is not None), None)

    def ibc_stats(self) -> dict:
        sa = [(m, float(v)) for m, v in self.ibc["sa"]]
        nsa = [(m, float(v)) for m, v in self.ibc["nsa"]]
        linhas = [(sa[k][0], sa[k][1], var_pct(sa[k][1], sa[k - 1][1])) for k in range(len(sa) - 1, max(len(sa) - 13, 0), -1)]
        return {"mes": sa[-1][0], "mm": var_pct(sa[-1][1], sa[-2][1]), "mes_nsa": nsa[-1][0], "yoy": var_pct(nsa[-1][1], nsa[-13][1]),
                "a12": var_pct(sum(v for _, v in nsa[-12:]), sum(v for _, v in nsa[-24:-12])), "sa": sa, "linhas": linhas}

    def uf_lista(self) -> list:
        """UFs com a taxa do último trimestre, ordenadas da maior para a menor taxa de desocupação."""
        if not self.tem_emprego:
            return []
        tri = self.des["trimestral"]
        ult = max(c for c, _, _ in tri["1"]["serie"])
        out = []
        for cod, t in tri.items():
            if cod not in UFS:
                continue
            serie = {c: v for c, _, v in t["serie"]}
            if ult not in serie:
                continue
            ant = sorted(serie)[sorted(serie).index(ult) - 1] if sorted(serie).index(ult) > 0 else None
            ano = f"{int(ult[:4]) - 1}{ult[4:]}"
            slug, nome, sigla = UFS[cod]
            out.append({"cod": cod, "slug": slug, "nome": nome, "sigla": sigla, "serie": serie, "ult": ult, "taxa": serie[ult],
                        "dif_tri": serie[ult] - serie[ant] if ant else None, "dif_ano": serie[ult] - serie[ano] if ano in serie else None})
        return sorted(out, key=lambda u: -u["taxa"])

    def caged_serie(self) -> list:
        return [(m, float(v)) for m, v in (self.caged or {}).get("saldo", [])]

    # Selic -------------------------------------------------------------
    def selic_em(self, dia: dt.date) -> float:
        v = self.mud[0][1]
        for d, x in self.mud:
            if d <= dia:
                v = x
        return v

    @property
    def selic(self) -> float:
        return self.mud[-1][1]

    @property
    def selic_desde(self) -> dt.date:
        return self.mud[-1][0]

    def decisoes(self) -> list:
        out = []
        for r in self.reunioes:
            if r["fim"] + dt.timedelta(days=3) > self.hoje:
                continue
            antes, depois = self.selic_em(r["fim"] - dt.timedelta(days=1)), self.selic_em(r["fim"] + dt.timedelta(days=3))
            out.append({**r, "antes": antes, "depois": depois, "delta": round(depois - antes, 4)})
        return out[::-1]  # mais recentes primeiro

    def proxima(self):
        return next((r for r in self.reunioes if r["fim"] >= self.hoje), None)

    # IPCA --------------------------------------------------------------
    def meses_ipca(self, n: int) -> list:
        return sorted(self.ipca_12)[-n:]

    def ytd(self, mensal: dict, ref: str):
        ms = [m for m in sorted(mensal) if m[:4] == ref[:4] and m <= ref]
        if not ms or ms[0][5:] != "01":
            return None
        f = 1.0
        for m in ms:
            f *= 1 + mensal[m] / 100
        return (f - 1) * 100

    def ranking(self) -> list:
        if not self.ref_areas:
            return []
        lst = [a for a in self.areas.values() if self.ref_areas in a["acum12"]]
        return sorted(lst, key=lambda a: -a["acum12"][self.ref_areas])


# ------------------------------------------------------------------ peças de HTML
def chg(v, d=2, un=" p.p.", sufixo="") -> str:
    k = "up" if v > 0 else "down" if v < 0 else "flat"
    seta = "▲" if v > 0 else "▼" if v < 0 else "●"
    return f'<span class="chg {k}">{seta} {nf(abs(v), d)}{un}{sufixo}</span>'


def tile(rotulo, valor, unidade="", extra="", cor="a", href=None) -> str:
    u = f"<small> {unidade}</small>" if unidade else ""
    corpo = f'<span class="lbl">{rotulo}</span><span class="val">{valor}{u}</span>{extra}'
    if href:
        return f'<a class="tile {cor}" href="{href}">{corpo}</a>'
    return f'<div class="tile {cor}">{corpo}</div>'


def card(inner: str, extra_cls="") -> str:
    return f'<div class="card {extra_cls}">{inner}</div>'


def cab(titulo: str, direita: str = "") -> str:
    return f'<div class="row-head"><h2>{titulo}</h2>{direita}</div>'


def tabela(cabs, linhas, alinh) -> str:
    th = "".join(f'<th class="{"r" if a == "r" else ""}">{h}</th>' for h, a in zip(cabs, alinh))
    trs = "".join("<tr>" + "".join(f'<td class="{"r" if a == "r" else ""}">{c}</td>' for c, a in zip(l, alinh)) + "</tr>" for l in linhas)
    return f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table></div>'


def hbarras(linhas, unidade="") -> str:
    """linhas: (rótulo html, valor, valor formatado, meta html). A unidade vem escrita acima das barras, como nos gráficos."""
    mx = max((abs(v) for _, v, _, _ in linhas), default=1) or 1
    out = []
    for rot, v, fmt, meta in linhas:
        w = max(2, int(abs(v) / mx * 100))
        m = f'<span class="meta">{meta}</span>' if meta else ""
        out.append(f'<div class="hbar"><span class="t">{rot}</span><span class="v">{fmt}</span>'
                   f'<span class="track"><span style="width:{w}%;background:var(--eco)"></span></span>{m}</div>')
    legenda = f'<div class="ul">{esc(unidade)}</div>' if unidade else ""
    return f'<div class="hbars">{legenda}{"".join(out)}</div>'


def lista_links(itens) -> str:
    return '<ul class="list">' + "".join(f'<li><a href="{h}"><span>{t}</span><span>{d}</span></a></li>' for h, t, d in itens) + "</ul>"


# ------------------------------------------------------------------ gráficos SVG (estáticos)
W, H, PL, PR, PT, PB = 640, 240, 58, 16, 42, 34


def _eixo(vals, zero=False, margem=0.12):
    """Escala 'redonda' para o eixo vertical: devolve (mínimo, máximo, marcas, casas decimais)."""
    mn, mx = min(vals), max(vals)
    if zero:
        mn, mx = min(mn, 0), max(mx, 0)
    pad = (mx - mn) * margem or 1
    mn, mx = (mn if zero and mn == 0 else mn - pad), mx + pad
    bruto = (mx - mn) / 3
    mag = 10 ** math.floor(math.log10(bruto))
    passo = next(m * mag for m in (1, 2, 2.5, 5, 10) if bruto <= m * mag)
    lo, hi = math.floor(mn / passo) * passo, math.ceil(mx / passo) * passo
    marcas = [round(lo + i * passo, 6) for i in range(int(round((hi - lo) / passo)) + 1)]
    d = 0 if abs(passo - round(passo)) < 1e-9 else 1 if abs(passo * 10 - round(passo * 10)) < 1e-9 else 2
    return lo, hi, marcas, d


def _rotulo_y(texto: str) -> str:
    """Unidade do eixo vertical, escrita no alto à esquerda (horizontal, para ler sem inclinar a cabeça)."""
    return f'<text class="yl" x="4" y="21" text-anchor="start">{esc(texto)}</text>' if texto else ""


def _grade(lo, hi, marcas, d) -> str:
    y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
    g = ""
    for t in marcas:
        cor = "var(--muted)" if abs(t) < 1e-9 and lo < 0 else "var(--line)"   # o zero fica mais marcado quando há valores negativos
        g += (f'<line x1="{PL}" x2="{W - PR}" y1="{y(t):.1f}" y2="{y(t):.1f}" style="stroke:{cor}"/>'
              f'<text x="{PL - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{nf(t, d)}</text>')
    return g


def _rotulos_x(rotulos, x) -> str:
    n = len(rotulos)
    passo = math.ceil(n / 5)
    pos = [k for k in range(0, n, passo) if (n - 1 - k) >= passo] + [n - 1]
    g = ""
    for k in pos:
        ancora = "start" if k == 0 else "end" if k == n - 1 else "middle"
        g += f'<text x="{x(k):.1f}" y="{H - 8}" text-anchor="{ancora}">{rotulos[k]}</text>'
    return g


def svg_linhas(series, rotulos, aria, zero=False, unidade="") -> str:
    """series: lista de dicts {vals, cor ('a'|'b'|'m'), tracejada}; todas com o mesmo tamanho que rotulos."""
    lo, hi, marcas, d = _eixo([v for s in series for v in s["vals"]], zero=zero)
    n = len(rotulos)
    x = lambda i: PL + (W - PL - PR) * (i / (n - 1) if n > 1 else 0.5)
    y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
    g = _rotulo_y(unidade) + _grade(lo, hi, marcas, d) + _rotulos_x(rotulos, x)
    cores = {"a": "var(--eco)", "b": "var(--eco2)", "m": "var(--muted)"}
    for s in series:
        c = cores[s.get("cor", "a")]
        tr = "".join(("L" if k else "M") + f"{x(k):.1f} {y(v):.1f}" for k, v in enumerate(s["vals"]))
        dash = ' stroke-dasharray="5 4"' if s.get("tracejada") else ""
        if len(series) == 1:
            g += f'<path d="{tr}L{x(n - 1):.1f} {H - PB}L{x(0):.1f} {H - PB}Z" style="fill:{c}" opacity=".12"/>'
        g += f'<path d="{tr}" fill="none" style="stroke:{c}" stroke-width="2.5" stroke-linejoin="round"{dash}/>'
        g += f'<circle cx="{x(n - 1):.1f}" cy="{y(s["vals"][-1]):.1f}" r="4.5" style="fill:{c}"/>'
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(aria)}">{g}</svg>'


def svg_degraus(pontos, ate: dt.date, aria, unidade="") -> str:
    """Gráfico em degraus no tempo. pontos: [(data, valor)] ordenados, o valor vale até o próximo ponto."""
    lo, hi, marcas, d = _eixo([v for _, v in pontos], zero=True)
    t0, t1 = pontos[0][0].toordinal(), ate.toordinal()
    x = lambda dia: PL + (W - PL - PR) * (dia.toordinal() - t0) / max(1, t1 - t0)
    y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
    g = _rotulo_y(unidade) + _grade(lo, hi, marcas, d)
    anos = list(range(pontos[0][0].year + 1, ate.year + 1))
    passo = 2 if len(anos) > 5 else 1
    for ano in anos[::passo]:
        g += f'<text x="{x(dt.date(ano, 1, 1)):.1f}" y="{H - 8}" text-anchor="middle">{ano}</text>'
    tr = f"M{x(pontos[0][0]):.1f} {y(pontos[0][1]):.1f}"
    for k in range(1, len(pontos)):
        tr += f"L{x(pontos[k][0]):.1f} {y(pontos[k - 1][1]):.1f}L{x(pontos[k][0]):.1f} {y(pontos[k][1]):.1f}"
    tr += f"L{x(ate):.1f} {y(pontos[-1][1]):.1f}"
    g += (f'<path d="{tr}L{x(ate):.1f} {H - PB}L{x(pontos[0][0]):.1f} {H - PB}Z" style="fill:var(--eco)" opacity=".12"/>'
          f'<path d="{tr}" fill="none" style="stroke:var(--eco)" stroke-width="2.5" stroke-linejoin="round"/>'
          f'<circle cx="{x(ate):.1f}" cy="{y(pontos[-1][1]):.1f}" r="4.5" style="fill:var(--eco)"/>')
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(aria)}">{g}</svg>'


def svg_barras(vals, rotulos, aria, unidade="") -> str:
    lo, hi, marcas, d = _eixo(vals, zero=True, margem=0.08)
    y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
    n = len(vals)
    bw = (W - PL - PR) / n
    x = lambda k: PL + bw * k + bw / 2
    g = _rotulo_y(unidade) + _grade(lo, hi, marcas, d) + _rotulos_x(rotulos, x)
    for k, v in enumerate(vals):
        y0, y1 = y(max(v, 0)), y(min(v, 0))
        cor = "var(--eco2)" if v < 0 else "var(--eco)"
        g += f'<rect x="{PL + bw * k + bw * 0.15:.1f}" y="{y0:.1f}" width="{bw * 0.7:.1f}" height="{max(1.0, y1 - y0):.1f}" rx="2" style="fill:{cor}"/>'
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(aria)}">{g}</svg>'


# ------------------------------------------------------------------ cartão de gráfico: fonte, data, dados e CSV
def chave_tri(cod: str) -> str:
    return f"{cod[:4]}-T{int(cod[4:])}"


def rot_periodo(p) -> str:
    p = str(p)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p):
        return f"{p[8:]}/{p[5:7]}/{p[:4]}"
    if re.fullmatch(r"\d{4}-\d{2}", p):
        return mes_curto(p)
    if re.fullmatch(r"\d{4}-T[1-4]", p):
        return f"{p[6]}º tri/{p[:4]}"
    return p


def csv_texto(cabecalho, linhas) -> str:
    """CSV para abrir direto no Excel em português: ponto e vírgula, vírgula decimal, UTF-8 com BOM."""
    def cel(v):
        if v is None:
            return ""
        if isinstance(v, float):
            return f"{v:.6f}".rstrip("0").rstrip(".").replace(".", ",")
        v = str(v)
        return '"' + v.replace('"', '""') + '"' if any(c in v for c in ';"\r\n') else v
    return "\ufeff" + "\r\n".join([";".join(cel(c) for c in cabecalho)] + [";".join(cel(c) for c in l) for l in linhas]) + "\r\n"


def grafico(B, slug, titulo, fonte, svg, cabecalho, linhas, grupo, nota="", legenda="", ultimo="", casas=2, csv_linhas=None, csv_cab=None) -> str:
    """Cartão de gráfico: título, gráfico (clicável: abre a tabela de dados), rodapé com fonte, último dado e data de atualização,
    link para o CSV e a tabela dos números. A primeira coluna é o período (texto); as demais, valores."""
    B.csvs[slug] = {"titulo": html.unescape(re.sub(r"<[^>]+>", "", titulo)), "fonte": fonte, "ultimo": ultimo, "grupo": grupo,
                    "cab": [html.unescape(c) for c in (csv_cab or cabecalho)], "linhas": csv_linhas if csv_linhas is not None else linhas}

    def fmt(v):
        if v is None:
            return "–"
        if isinstance(v, (int, float)):
            return nf(v, casas)
        return esc(rot_periodo(v))

    tab = tabela([esc(c) for c in cabecalho], [[fmt(c) for c in l] for l in linhas[::-1]], ["l"] + ["r"] * (len(cabecalho) - 1))
    atual = data_br(dt.datetime.fromisoformat(B.d["gerado_em"]).date())
    ult = f" Último dado: {esc(ultimo)}." if ultimo else ""
    return card(cab(titulo) +
                f'<div class="chart" data-abre="d-{slug}" role="button" tabindex="0" title="Clique para ver os dados">{svg}</div>' +
                legenda + nota +
                f'<div class="gfoot"><span class="src">Fonte: {esc(fonte)}.{ult} Atualizado em {atual}.</span>'
                f'<a class="csv" href="/dados/{slug}.csv" download>Baixar CSV</a></div>'
                f'<details class="dados" id="d-{slug}"><summary>Ver os dados do gráfico ({len(linhas)} linhas)</summary>{tab}</details>')


def pg_dados(B: Base) -> str:
    ordem = ["Juros e Copom", "Inflação", "Inflação por área", "Emprego", "Emprego por estado", "Atividade", "Indústria e varejo", "Crédito", "Câmbio", "Contas públicas"]
    grupos = {}
    for slug, c in B.csvs.items():
        grupos.setdefault(c["grupo"], []).append((slug, c))
    blocos = []
    for g in sorted(grupos, key=lambda x: ordem.index(x) if x in ordem else 99):
        itens = "".join(f'<li><a href="/dados/{slug}.csv" download>{esc(c["titulo"])}</a>'
                        f'<span class="small"> · {esc(c["fonte"])}{" · último dado: " + esc(c["ultimo"]) if c["ultimo"] else ""}</span></li>'
                        for slug, c in sorted(grupos[g], key=lambda x: x[1]["titulo"]))
        if " por " in g:
            blocos.append(card(f'<details><summary><strong>{esc(g)}</strong> ({len(grupos[g])} arquivos)</summary><ul class="plain">{itens}</ul></details>'))
        else:
            blocos.append(card(f'<h2>{esc(g)}</h2><ul class="plain">{itens}</ul>'))
    atual = data_br(dt.datetime.fromisoformat(B.d["gerado_em"]).date())
    hero = card('<span class="eyebrow">Dados abertos</span><h1>Baixe os números dos gráficos em CSV</h1>'
                '<p class="lede">Cada gráfico do portal tem um arquivo CSV com a série completa. Os arquivos abrem direto no Excel em português '
                '(separador ponto e vírgula, vírgula decimal, acentos corretos) e se atualizam sozinhos junto com o site.</p>')
    citar = card("<h2>Como citar</h2>"
                 "<p>Os números são públicos e vêm das fontes oficiais indicadas em cada gráfico e em cada arquivo. Ao publicar, cite a fonte original e este portal, por exemplo:</p>"
                 f'<p><em>Fonte: Banco Central do Brasil, via Economia em Números (economiaemnumeros.com.br), dados atualizados em {atual}.</em></p>'
                 '<p class="small">Cada arquivo traz a série completa disponível no portal; o período mais curto mostrado no gráfico é só um recorte para leitura.</p>')
    return pagina(B, "/dados/", "Dados em CSV: baixe as séries de juros, inflação, emprego, atividade, crédito, câmbio e contas públicas",
                  "Arquivos CSV com os números de cada gráfico do Economia em Números: Selic, IPCA, desemprego, PIB, produção industrial, varejo, crédito, dólar e dívida pública, com fonte e data.",
                  f"{hero}{''.join(blocos)}{citar}", "", [(None, "Dados em CSV")])


# ------------------------------------------------------------------ moldura
def familia_html(atual="Economia em Números") -> str:
    itens = []
    for nome, tema, url, cor in FAMILIA:
        miolo = f'<span class="ponto" style="background:{cor}"></span><span><b>{nome}</b> {tema}</span>'
        itens.append(f'<li>{miolo} <em>você está aqui</em></li>' if nome == atual else f'<li><a href="{url}">{miolo}</a></li>')
    return ('<div class="familia"><p><b>Família em Números</b> · portais independentes que organizam dados públicos do Brasil</p>'
            f'<ul>{"".join(itens)}</ul></div>')


def pagina(B: Base, caminho, titulo, descricao, corpo, ativo="", migalhas=None, noindex=False) -> str:
    url = BASE + caminho
    nav = "".join(f'<a href="{h}"' + (' aria-current="page"' if h == ativo else "") + f">{t}</a>" for h, t in B.nav())
    bc = ""
    if migalhas:
        partes = ['<a href="/">Início</a>'] + [f'<a href="{h}">{esc(t)}</a>' if h else esc(t) for h, t in migalhas]
        bc = '<nav class="bc" aria-label="Você está em">' + " › ".join(partes) + "</nav>"
    gerado = data_br(dt.datetime.fromisoformat(B.d["gerado_em"]).date())
    v = B.d["gerado_em"][:10]
    robots = '<meta name="robots" content="noindex">\n' if noindex else ""
    rodape = " · ".join(f'<a href="{h}">{"Como funciona" if h == "/sobre/" else t}</a>' for h, t in B.nav()) + ' · <a href="/dados/">Dados em CSV</a>'
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(titulo)}</title>
<meta name="description" content="{esc(descricao)}">
{robots}<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Economia em Números">
<meta property="og:title" content="{esc(titulo)}">
<meta property="og:description" content="{esc(descricao)}">
<meta property="og:url" content="{url}">
<meta property="og:locale" content="pt_BR">
<meta name="twitter:card" content="summary">
<meta name="theme-color" content="#2a5bc4">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/estilo.css?v={v}">
</head>
<body>
<header class="top"><div class="top-in">
<a class="brand" href="/" aria-label="Economia em Números, início"><svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true"><rect x="1" y="1" width="26" height="26" rx="6" fill="none" stroke="currentColor" stroke-width="1.5" opacity=".35"/><rect x="6" y="14" width="4" height="8" rx="1" fill="var(--eco)"/><rect x="12" y="9" width="4" height="13" rx="1" fill="var(--eco)"/><rect x="18" y="6" width="4" height="16" rx="1" fill="var(--eco2)"/></svg><b>Economia <span>em Números</span></b></a>
<nav class="main" aria-label="Seções">{nav}</nav>
</div></header>
<div class="info-bar"><div><strong>Dados de {mes_nome(B.ref)}.</strong> Fontes: Banco Central e IBGE, atualizado automaticamente em {gerado}.</div></div>
<main>
{bc}
{corpo}
</main>
<footer><div>
<span><strong>Economia em Números</strong> · versão beta</span>
<span>Portal independente, sem ligação com o governo. Os números vêm de fontes públicas (Banco Central e IBGE) e não são recomendação de investimento nem aconselhamento financeiro.</span>
<span>{rodape}</span>
</div>{familia_html()}</footer>
<script src="/assets/graficos.js?v={v}" defer></script>
{GOAT}
</body>
</html>
"""


# ------------------------------------------------------------------ páginas
FOCUS_PRINCIPAL = {"Selic": ("Selic ao fim do ano", lambda v: pct(v, 2)), "IPCA": ("IPCA (inflação)", lambda v: pct(v, 2)),
                   "PIB Total": ("PIB (crescimento)", lambda v: pct(v, 2)), "Câmbio": ("Câmbio (R$ por US$)", lambda v: nf(v, 2))}
FOCUS_FISCAL = {"Resultado primário": ("Resultado primário", lambda v: pct(v, 2)), "Resultado nominal": ("Resultado nominal", lambda v: pct(v, 2)),
                "Dívida bruta do governo geral": ("Dívida bruta", lambda v: pct(v, 1)), "Dívida líquida do setor público": ("Dívida líquida", lambda v: pct(v, 1))}


def blocos_focus(B: Base, nomes=None, titulo="Expectativas do mercado (Boletim Focus)", complemento="") -> str:
    f = B.focus
    if not f or not f.get("itens"):
        return ""
    nomes = nomes or FOCUS_PRINCIPAL
    itens = [it for it in f["itens"] if it["indicador"] in nomes]
    if not itens:
        return ""
    por = {}
    for it in itens:
        por.setdefault(it["indicador"], {})[it["ano"]] = it
    anos = sorted({it["ano"] for it in itens})
    linhas = []
    for ind, (rot, fm) in nomes.items():
        if ind not in por:
            continue
        cels = [rot]
        var = ""
        for a in anos:
            it = por[ind].get(a)
            cels.append(fm(it["mediana"]) if it else "–")
        a0 = por[ind].get(anos[0])
        if a0 and a0.get("semana_anterior") is not None:
            var = chg(a0["mediana"] - a0["semana_anterior"], 2, "")
        cels.append(var or "–")
        linhas.append(cels)
    dia = data_br(dt.date.fromisoformat(f["data"]))
    return card(cab(titulo) +
                tabela(["Indicador"] + [str(a) for a in anos] + ["Semana"], linhas, ["l"] + ["r"] * (len(anos) + 1)) +
                f'<span class="src">Mediana das projeções do mercado, Boletim Focus (posição de {dia}). \"Semana\" é a variação da projeção para {anos[0]} desde o boletim anterior.{complemento} Fonte: Banco Central do Brasil.</span>')


def card_copom(B: Base) -> str:
    p = B.proxima()
    dec = B.decisoes()
    partes = [f'<span class="eyebrow">Próxima reunião do Copom</span>']
    if p:
        dias = (p["fim"] - B.hoje).days
        quando = "hoje" if dias <= 0 else "amanhã" if dias == 1 else f"faltam {dias} dias"
        partes.append(f'<h2>{periodo_reuniao(p["ini"], p["fim"])}</h2>')
        partes.append(f'<p class="small">A decisão sai no fim do dia {p["fim"].day:02d}/{p["fim"].month:02d} ({quando}). A ata, na terça-feira, {data_br(p["ata"])}, às 8h.</p>')
    if dec:
        u = dec[0]
        verbo = "manteve" if u["delta"] == 0 else "reduziu" if u["delta"] < 0 else "elevou"
        txt = (f'Na última reunião ({periodo_reuniao(u["ini"], u["fim"])}), o Copom {verbo} a meta da Selic'
               + ("" if u["delta"] == 0 else f' em {nf(abs(u["delta"]), 2)} ponto percentual') + f', para {pct(u["depois"], 2)} ao ano.')
        partes.append(f'<p>{txt}</p>')
        if u["ata"] <= B.hoje:
            partes.append(f'<p class="small">A ata saiu em {data_br(u["ata"])}: <a href="/juros/#ata-{u["num"]}">ver o resumo e o link</a>.</p>')
    partes.append('<p><a href="/juros/">Calendário, decisões e expectativas →</a></p>')
    return card("".join(partes))


def pg_inicio(B: Base) -> str:
    ref = B.ref
    m_ant = sorted(B.ipca_12)[-2]
    sel_prev = B.mud[-2][1] if len(B.mud) > 1 else B.selic
    p = B.proxima()
    tiles = []
    ex = chg(B.selic - sel_prev, 2, " p.p.", " na última mudança") if B.selic != sel_prev else '<span class="chg flat">● sem mudança recente</span>'
    tiles.append(tile("Meta da Selic", nf(B.selic, 2), "% ao ano", ex, "a", "/juros/"))
    tiles.append(tile("IPCA em 12 meses", nf(B.ipca_12[ref], 2), "%", chg(B.ipca_12[ref] - B.ipca_12[m_ant], 2, " p.p.", " no mês"), "b", "/inflacao/"))
    tiles.append(tile(f"IPCA em {MESES[int(ref[5:]) - 1]}", nf(B.ipca_m[ref], 2), "%", chg(B.ipca_m[ref] - B.ipca_m[m_ant], 2, " p.p.", " vs. mês anterior"), "k", "/inflacao/"))
    if p:
        dias = (p["fim"] - B.hoje).days
        tiles.append(tile("Próximo Copom", periodo_curto(p["ini"], p["fim"]), "", f'<span class="chg flat">● {"hoje" if dias <= 0 else f"em {dias} dias"}</span>', "g", "/juros/"))
    hero = card('<span class="eyebrow">O Brasil em números</span>'
                "<h1>Juros, inflação e expectativas da economia, em números simples</h1>"
                '<p class="lede">Os principais indicadores da economia brasileira em um só lugar, direto das fontes oficiais: '
                f"a <strong>Selic está em {pct(B.selic, 2)} ao ano</strong> e a inflação em 12 meses é de <strong>{pct(B.ipca_12[ref], 2)}</strong> ({mes_nome(ref)}). "
                "Sem cadastro e sem opinião: só o número, a fonte e a data.</p>")
    sel19 = [(d, v) for d, v in B.mud if d >= dt.date(2019, 1, 1)] or B.mud
    selic = grafico(B, "selic-meta", "Taxa Selic (meta do Copom) desde 2019", F_SELIC,
                    svg_degraus(sel19, B.hoje, "Gráfico em degraus da meta da taxa Selic desde 2019", unidade="% ao ano"),
                    ["Em vigor desde", "Meta da Selic (% ao ano)"], [(d.isoformat(), v) for d, v in sel19], "Juros e Copom",
                    nota='<p class="small">Meta da taxa Selic definida pelo Copom, em % ao ano. Cada degrau é uma decisão do comitê.</p>',
                    ultimo=f"{pct(B.selic, 2)} ao ano, em vigor desde {data_br(B.selic_desde)}", csv_linhas=[(d.isoformat(), v) for d, v in B.mud])
    rk = B.ranking()
    infl = card(cab("Inflação por região", '<a class="small" href="/inflacao/">ver as 16 áreas →</a>') +
                hbarras([(f'<a href="/inflacao/{a["slug"]}/">{esc(a["nome"])}</a>', a["acum12"][B.ref_areas], pct(a["acum12"][B.ref_areas], 2), "") for a in rk[:8]], "IPCA acumulado em 12 meses (%)") +
                f'<span class="src">IPCA acumulado em 12 meses até {mes_nome(B.ref_areas)}. As 8 maiores de 16 áreas. Fonte: IBGE.</span>') if rk else ""
    focus = blocos_focus(B)
    linha2 = f'<div class="cols">{infl}{focus}</div>' if infl and focus else (infl or focus)
    calc = card('<span class="eyebrow">Ferramenta</span><h2>Calculadora de correção pelo IPCA</h2>'
                '<p class="small">Quanto R$ 1.000 de alguns anos atrás valem hoje? Corrija qualquer valor pela inflação oficial, mês a mês, desde 2000.</p>'
                '<p><a href="/calculadora/">Abrir a calculadora →</a></p>')
    mais = [x for x in (card_emprego_inicio(B), card_atividade_inicio(B), card_ibge_inicio(B), card_credito_inicio(B), card_cambio_inicio(B), card_fiscal_inicio(B)) if x]
    mais_html = "".join(f'<div class="cols">{"".join(mais[k:k + 2])}</div>' if len(mais[k:k + 2]) == 2 else mais[k] for k in range(0, len(mais), 2))
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div><div class="two">{selic}{card_copom(B)}</div>{linha2}{mais_html}{calc}'
    return pagina(B, "/", "Economia em Números: Selic, inflação (IPCA) e Copom em dados oficiais",
                  f"Selic em {pct(B.selic, 2)} ao ano e IPCA de {pct(B.ipca_12[ref], 2)} em 12 meses. Juros, inflação por região, calendário do Copom e expectativas do Focus, com fonte e data.",
                  corpo)


def decisao_frase(u: dict) -> str:
    verbo = "manteve" if u["delta"] == 0 else "reduziu" if u["delta"] < 0 else "elevou"
    return (f"O Copom {verbo} a meta da Selic" + ("" if u["delta"] == 0 else f' em {nf(abs(u["delta"]), 2)} ponto percentual') +
            f', para {pct(u["depois"], 2)} ao ano')


def atas_mostradas(B: Base) -> list:
    """A ata mais recente (com ou sem resumo) e as anteriores que têm resumo, até 4 no total."""
    cand = [u for u in B.decisoes() if u["ata"] <= B.hoje]
    if not cand:
        return []
    return ([cand[0]] + [u for u in cand[1:] if str(u["num"]) in B.resumos])[:4]


def cards_atas(B: Base) -> str:
    mostrar = atas_mostradas(B)
    if not mostrar:
        return ""
    out = [card(cab("Atas do Copom, resumidas") +
                '<p class="small">A ata é publicada na terça-feira seguinte à decisão e explica o raciocínio do comitê. Abaixo, um resumo curto de cada uma, com o link para o documento original no Banco Central.</p>')]
    for u in mostrar:
        n = u["num"]
        r = B.resumos.get(str(n))
        pdf = B.ata_pdf(n)
        frase = decisao_frase(u) + (f', por {r["votacao"]}' if r and r.get("votacao") else "")
        corpo = (f'<h3 id="ata-{n}">{n}ª reunião do Copom · {periodo_reuniao(u["ini"], u["fim"])} de {u["fim"].year}</h3>'
                 f'<p><strong>{frase}.</strong> <span class="small">Ata publicada em {data_br(u["ata"])}.</span></p>')
        nota = ""
        if r:
            corpo += '<ul class="plain">' + "".join(f'<li><strong>{esc(x["t"])}.</strong> {esc(x["x"])}</li>' for x in r["pontos"]) + "</ul>"
            nota = (f'<span class="src">Resumo do Economia em Números, escrito a partir da ata oficial; não a substitui. '
                    f'Publicado em {data_br(dt.date.fromisoformat(r["publicado_em"]))}.</span>')
        else:
            corpo += "<p>O resumo desta ata ainda está em preparação.</p>"
        link = (f'<a href="{pdf}" rel="noopener">Ler a ata completa (PDF, Banco Central) →</a>' if pdf
                else f'<a href="{ATAS_LISTA}" rel="noopener">Ver as atas no site do Banco Central →</a>')
        out.append(card(corpo + f'<p class="small">{link}</p>' + nota))
    return "".join(out)


def pg_juros(B: Base) -> str:
    p = B.proxima()
    dec = B.decisoes()
    hero = card('<span class="eyebrow">Política monetária</span><h1>Selic e reuniões do Copom</h1>'
                f'<p class="lede">A meta da Selic está em <strong>{pct(B.selic, 2)} ao ano</strong> desde {data_br(B.selic_desde)}. '
                "Veja o histórico de decisões, o calendário das próximas reuniões e o que o mercado espera para os juros.</p>")
    graf = grafico(B, "selic-meta", "Taxa Selic (meta do Copom) desde 2016", F_SELIC, svg_degraus(B.mud, B.hoje, "Gráfico em degraus da meta da taxa Selic desde 2016", unidade="% ao ano"),
                   ["Em vigor desde", "Meta da Selic (% ao ano)"], [(d.isoformat(), v) for d, v in B.mud], "Juros e Copom",
                   ultimo=f"{pct(B.selic, 2)} ao ano, em vigor desde {data_br(B.selic_desde)}")
    fut = [r for r in B.reunioes if r["fim"] >= B.hoje][:8]
    cal = card(cab("Próximas reuniões do Copom") +
               tabela(["Reunião", "Datas", "Ata"], [[f"{r['num']}ª", periodo_reuniao(r["ini"], r["fim"]) + f" de {r['fim'].year}", data_br(r["ata"])] for r in fut], ["l", "l", "r"]) +
               '<span class="src">Calendário oficial do Banco Central. A decisão sai no fim da segunda sessão; a ata, na terça-feira seguinte, às 8h.</span>')
    linhas = []
    mostradas = {u["num"] for u in atas_mostradas(B)}
    for u in dec[:10]:
        sel = chg(u["delta"], 2, "") if u["delta"] else '<span class="chg flat">● mantida</span>'
        links = []
        if u["ata"] <= B.hoje:
            if u["num"] in mostradas:
                links.append(f'<a href="#ata-{u["num"]}">resumo</a>')
            if B.ata_pdf(u["num"]):
                links.append(f'<a href="{B.ata_pdf(u["num"])}" rel="noopener">PDF</a>')
        linhas.append([periodo_tabela(u["ini"], u["fim"]), sel, pct(u["depois"], 2), " · ".join(links) or "–"])
    decs = card(cab("Decisões recentes") + tabela(["Reunião", "Decisão (p.p.)", "Selic", "Ata"], linhas, ["l", "r", "r", "r"]) +
                '<span class="src">Calculado a partir da meta da Selic registrada pelo Banco Central.</span>')
    focus = blocos_focus(B)
    texto = card("<h2>O que é a Selic</h2>"
                 "<p>A Selic é a taxa básica de juros da economia brasileira. O Comitê de Política Monetária (Copom), do Banco Central, define a <strong>meta</strong> da Selic em oito reuniões por ano. "
                 "Essa meta serve de referência para os juros de financiamentos e de aplicações de renda fixa: quando ela sobe, o crédito tende a ficar mais caro e a inflação perde força; quando cai, ocorre o contrário.</p>"
                 "<p>Em cada reunião, o comitê pode elevar, reduzir ou manter a meta. O comunicado com a decisão sai no fim do segundo dia, e a ata, com a análise do comitê, "
                 "é publicada na terça-feira seguinte. Os números desta página vêm do Banco Central do Brasil.</p>")
    corpo = f'{hero}{graf}<div class="cols">{cal}{decs}</div>{cards_atas(B)}{focus}{texto}'
    return pagina(B, "/juros/", "Selic e Copom: meta atual, calendário e decisões das reuniões",
                  f"Meta da Selic em {pct(B.selic, 2)} ao ano. Histórico de decisões do Copom, calendário das próximas reuniões e expectativas do Boletim Focus.",
                  corpo, "/juros/", [(None, "Juros e Copom")])


def card_emprego_inicio(B: Base) -> str:
    if not B.tem_emprego:
        return ""
    m = B.des["movel"][-1]
    txt = f'A taxa de desocupação no Brasil é de <strong>{pct(m[2], 1)}</strong> no trimestre {rot_movel(m[0])}.'
    cg = B.caged_serie()
    if cg:
        mes, v = cg[-1]
        txt += f' O Novo Caged registrou saldo de <strong>{saldo_txt(v)}</strong> vagas formais em {mes_nome(mes)}.'
    return card('<span class="eyebrow">Mercado de trabalho</span><h2>Desemprego e vagas formais</h2>'
                f'<p>{txt}</p><p><a href="/emprego/">Ver a taxa em cada estado e o saldo de vagas →</a></p>')


def pg_emprego(B: Base) -> str:
    mov = B.des["movel"]
    ult, ant = mov[-1], mov[-2]
    ano = next((x for x in mov if x[0] == f"{int(ult[0][:4]) - 1}{ult[0][4:]}"), None)
    ufs = B.uf_lista()
    cg = B.caged_serie()
    lede = f'A taxa de desocupação no Brasil foi de <strong>{pct(ult[2], 1)}</strong> no trimestre {rot_movel(ult[0])}'
    if ano:
        rel = "abaixo do" if ult[2] < ano[2] else "acima do" if ult[2] > ano[2] else "igual ao"
        lede += f", {rel} mesmo período de um ano antes ({pct(ano[2], 1)})."
    else:
        lede += "."
    if cg:
        mes, v = cg[-1]
        lede += f' O Novo Caged {"criou" if v > 0 else "fechou"} <strong>{nf(abs(v), 0)}</strong> vagas formais líquidas em {mes_nome(mes)}.'
    hero = card('<span class="eyebrow">Mercado de trabalho</span><h1>Desemprego e vagas formais no Brasil</h1>' f'<p class="lede">{lede}</p>')
    tiles = [tile("Desocupação (trim. móvel)", nf(ult[2], 1), "%", chg(ult[2] - ant[2], 1, " p.p.", " vs. trim. anterior"), "a")]
    if ano:
        tiles.append(tile("Um ano antes", nf(ano[2], 1), "%", "", "k"))
    if cg:
        tiles.append(tile(f"Vagas formais em {MES_CURTO[int(cg[-1][0][5:]) - 1]}", saldo_txt(cg[-1][1]), "", "", "b"))
        ult12 = sum(v for _, v in cg[-12:]) if len(cg) >= 12 else None
        if ult12 is not None:
            tiles.append(tile("Vagas em 12 meses", saldo_txt(ult12), "", "", "g"))
    elif ufs:
        tiles.append(tile("Menor taxa", nf(ufs[-1]["taxa"], 1), f'% · {ufs[-1]["sigla"]}', "", "b"))
        tiles.append(tile("Maior taxa", nf(ufs[0]["taxa"], 1), f'% · {ufs[0]["sigla"]}', "", "g"))
    ult36 = mov[-36:]
    g1 = grafico(B, "desocupacao-brasil", "Taxa de desocupação", F_PNAD_BR,
                 svg_linhas([{"vals": [x[2] for x in ult36], "cor": "a"}], [mes_curtinho(f"{x[0][:4]}-{x[0][4:]}") for x in ult36],
                            "Gráfico da taxa de desocupação no Brasil, em trimestres móveis, nos últimos 36 meses", unidade="% da força de trabalho"),
                 ["Trimestre móvel", "Taxa de desocupação (%)"], [(rot_movel_curto(x[0]), x[2]) for x in ult36], "Emprego", casas=1,
                 nota='<p class="small">Pessoas de 14 anos ou mais sem trabalho que procuraram emprego, em % da força de trabalho. Cada ponto é um trimestre móvel, identificado pelo mês final.</p>',
                 ultimo=f"trimestre {rot_movel(ult[0])} ({pct(ult[2], 1)})",
                 csv_cab=["Mês final do trimestre (AAAA-MM)", "Trimestre móvel", "Taxa de desocupação (%)"],
                 csv_linhas=[(f"{x[0][:4]}-{x[0][4:]}", rot_movel(x[0]), x[2]) for x in mov])
    g2 = ""
    if cg:
        c24 = cg[-24:]
        g2 = grafico(B, "caged-saldo", "Saldo mensal de vagas formais", F_CAGED,
                     svg_barras([v / 1000 for _, v in c24], [mes_curtinho(m) for m, _ in c24], "Gráfico de barras do saldo mensal de vagas formais do Novo Caged nos últimos 24 meses, em milhares", unidade="Milhares de vagas no mês"),
                     ["Mês", "Saldo (vagas)"], c24, "Emprego", casas=0, csv_linhas=cg,
                     nota='<p class="small">Em milhares de vagas. Admissões menos desligamentos de empregos com carteira assinada. Dezembro costuma ter saldo negativo.</p>',
                     ultimo=f"{mes_nome(cg[-1][0])}: {saldo_txt(cg[-1][1])} vagas")
    graficos = f'<div class="cols">{g1}{g2}</div>' if g2 else g1
    tab = ""
    if ufs:
        rows = []
        for u in ufs:
            rows.append([f'<a href="/emprego/{u["slug"]}/">{esc(u["nome"])} ({u["sigla"]})</a>', pct(u["taxa"], 1),
                         f'{sinal(u["dif_tri"], 1)} p.p.' if u["dif_tri"] is not None else "–",
                         f'{sinal(u["dif_ano"], 1)} p.p.' if u["dif_ano"] is not None else "–"])
        tab = card(cab(f'Por estado · {rot_tri(ufs[0]["ult"], True)}', '<span class="src">Fonte: IBGE (PNAD Contínua)</span>') +
                   tabela(["Estado", "Taxa", "Trim. ant.", "Ano ant."], rows, ["l", "r", "r", "r"]) +
                   '<span class="src">Dos maiores para os menores valores. As duas últimas colunas mostram a diferença para o trimestre anterior e para o mesmo trimestre do ano anterior, em pontos percentuais; variações pequenas podem estar dentro da margem de erro da pesquisa.</span>')
    texto = card("<h2>Como ler os números de emprego</h2>"
                 "<p>A <strong>taxa de desocupação</strong> vem da PNAD Contínua, pesquisa por amostra de domicílios do IBGE. Ela considera todos os tipos de trabalho, inclusive informal, "
                 "e mede a parcela da força de trabalho que está sem emprego e procurando uma vaga.</p>"
                 "<p>O <strong>saldo do Novo Caged</strong>, do Ministério do Trabalho e Emprego, conta só os empregos com carteira assinada: admissões menos desligamentos no mês. "
                 "As duas medidas respondem a perguntas diferentes e podem se mover em direções distintas.</p>")
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div>{graficos}{tab}{texto}'
    return pagina(B, "/emprego/", f"Desemprego no Brasil: taxa de {pct(ult[2], 1)} ({rot_movel(ult[0])}) e vagas formais",
                  f"Taxa de desocupação de {pct(ult[2], 1)} no trimestre {rot_movel(ult[0])}, por estado, e saldo mensal de vagas formais do Novo Caged. Dados do IBGE e do Ministério do Trabalho.",
                  corpo, "/emprego/", [(None, "Emprego")])


def pg_uf(B: Base, u: dict) -> str:
    ufs = B.uf_lista()
    pos = next(i for i, x in enumerate(ufs) if x["cod"] == u["cod"]) + 1
    br = {c: v for c, _, v in B.des["trimestral"]["1"]["serie"]}
    ult = u["ult"]
    comuns = [c for c in sorted(u["serie"]) if c in br][-13:]
    rel = ""
    if ult in br:
        dif = u["taxa"] - br[ult]
        rel = f' Isso é {nf(abs(dif), 1)} p.p. {"acima" if dif > 0 else "abaixo"} da média do Brasil ({pct(br[ult], 1)}).' if dif else f" Igual à média do Brasil ({pct(br[ult], 1)})."
    rank = f" Foi a {ordinal_f(pos)} maior taxa entre as {len(ufs)} unidades da federação."
    hero = card(f'<span class="eyebrow">Desocupação · estado</span><h1>Desemprego {EM[u["sigla"]]}: taxa de {pct(u["taxa"], 1)} no {rot_tri(ult, True)}</h1>'
                f'<p class="lede">A taxa de desocupação {EM[u["sigla"]]} ({u["sigla"]}) foi de <strong>{pct(u["taxa"], 1)}</strong> no {rot_tri(ult, True)}.{rel}{rank}</p>')
    tiles = [tile("Taxa de desocupação", nf(u["taxa"], 1), "%", chg(u["dif_tri"], 1, " p.p.", " vs. trim. anterior") if u["dif_tri"] is not None else "", "a")]
    if u["dif_ano"] is not None:
        tiles.append(tile("Vs. ano anterior", sinal(u["dif_ano"], 1), "p.p.", "", "k"))
    if ult in br:
        tiles.append(tile("Brasil", nf(br[ult], 1), "%", "", "g"))
    tiles.append(tile("Posição", ordinal_f(pos), f"de {len(ufs)}", "", "b"))
    series = [{"vals": [u["serie"][c] for c in comuns], "cor": "b"}, {"vals": [br[c] for c in comuns], "cor": "m", "tracejada": True}]
    todos = [c for c in sorted(u["serie"]) if c in br]
    graf = grafico(B, f"desocupacao-{u['slug']}", f"Taxa de desocupação: {esc(u['nome'])} e Brasil", F_PNAD_UF,
                   svg_linhas(series, [rot_tri(c) for c in comuns], f"Gráfico da taxa de desocupação em {u['nome']} e no Brasil", unidade="% da força de trabalho"),
                   ["Trimestre", f'{u["nome"]} (%)', "Brasil (%)"], [(rot_tri(c, True), u["serie"][c], br[c]) for c in comuns], "Emprego por estado", casas=1,
                   legenda=f'<div class="leg"><span><i style="background:var(--eco2)"></i>{esc(u["nome"])}</span><span><i style="background:var(--muted)"></i>Brasil</span></div>',
                   ultimo=f"{rot_tri(ult, True)}: {pct(u['taxa'], 1)}",
                   csv_cab=["Trimestre", f"Desocupação {u['nome']} (%)", "Desocupação Brasil (%)"],
                   csv_linhas=[(chave_tri(c), u["serie"][c], br[c]) for c in todos])
    rows = [[rot_tri(c, True), pct(u["serie"][c], 1), pct(br[c], 1), f'{sinal(u["serie"][c] - br[c], 1)} p.p.'] for c in comuns[::-1]]
    tab = card(cab("Trimestre a trimestre") + tabela(["Trimestre", esc(u["nome"]), "Brasil", "Diferença"], rows, ["l", "r", "r", "r"]))
    outras = card(cab("Outros estados") + lista_links([(f'/emprego/{x["slug"]}/', f'{esc(x["nome"])} ({x["sigla"]})', pct(x["taxa"], 1)) for x in ufs if x["cod"] != u["cod"]]) +
                  '<p class="small"><a href="/emprego/">← Emprego no Brasil e nos estados</a></p>')
    texto = card("<h2>O que a taxa de desocupação mede</h2>"
                 "<p>A taxa de desocupação é a parcela da força de trabalho (pessoas de 14 anos ou mais que trabalham ou procuram trabalho) que está sem ocupação e procurando uma vaga. "
                 f"Os dados vêm da PNAD Contínua, pesquisa por amostra do IBGE, e as diferenças pequenas entre trimestres {EM[u['sigla']]} podem estar dentro da margem de erro.</p>")
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div>{graf}<div class="cols">{tab}{outras}</div>{texto}'
    return pagina(B, f"/emprego/{u['slug']}/", f"Desemprego {EM[u['sigla']]} ({u['sigla']}): taxa de {pct(u['taxa'], 1)} no {rot_tri(ult, True)}",
                  f"Taxa de desocupação {EM[u['sigla']]} ({u['sigla']}): {pct(u['taxa'], 1)} no {rot_tri(ult, True)}, comparada ao Brasil. Série trimestral da PNAD Contínua do IBGE.",
                  corpo, "/emprego/", [("/emprego/", "Emprego"), (None, u["nome"])])


def focus_item(B: Base, ind: str, ano: int):
    return next((it for it in (B.focus or {}).get("itens", []) if it["indicador"] == ind and it["ano"] == ano), None)


def card_cambio_inicio(B: Base) -> str:
    if not B.tem_cambio:
        return ""
    c = B.cambio_stats()
    txt = f'No fechamento de {data_br(c["data"])}, a cotação de venda foi de <strong>R$ {nf(c["ult"], 2)}</strong>.'
    if c["a12"] is not None:
        txt += f' Em 12 meses, o dólar {verbo_var(c["a12"], 1, "subiu", "caiu")}.'
    return card('<span class="eyebrow">Câmbio</span><h2>Dólar em reais</h2>'
                f'<p>{txt}</p><p><a href="/cambio/">Ver o histórico e as projeções do mercado →</a></p>')


def card_atividade_inicio(B: Base) -> str:
    if not B.tem_atividade:
        return ""
    partes = []
    r = B.pib_ref() if B.tem_pib else None
    if r:
        partes.append(f'O PIB {verbo_var(r["qoq"], 1)} no {rot_tri(r["t"], True)} frente ao trimestre anterior.')
    if B.tem_ibc:
        i = B.ibc_stats()
        partes.append(f'O IBC-Br, termômetro mensal do Banco Central, {verbo_var(i["mm"], 1, "subiu", "caiu")} em {mes_nome(i["mes"])}.')
    return card('<span class="eyebrow">Atividade econômica</span><h2>PIB e IBC-Br</h2>'
                f'<p>{" ".join(partes)}</p><p><a href="/atividade/">Ver PIB trimestral e IBC-Br mensal →</a></p>')


def card_fiscal_inicio(B: Base) -> str:
    if not B.tem_fiscal:
        return ""
    f = B.fis_stats()
    txt = (f'A dívida bruta do governo geral ficou em <strong>{pct(f["dbgg"]["v"], 1)} do PIB</strong> em {mes_nome(f["dbgg"]["mes"])}. '
           f'O setor público teve {resultado_txt(f["primario"]["v"])} no resultado primário em 12 meses.')
    return card('<span class="eyebrow">Contas públicas</span><h2>Dívida e resultado fiscal</h2>'
                f'<p>{txt}</p><p><a href="/contas-publicas/">Ver dívida, resultado primário e nominal →</a></p>')


def pg_fiscal(B: Base) -> str:
    f = B.fis_stats()
    dbgg, dlsp, prim, nom = f["dbgg"], f["dlsp"], f["primario"], f["nominal"]
    lede = (f'A dívida bruta do governo geral ficou em <strong>{pct(dbgg["v"], 1)} do PIB</strong> em {mes_nome(dbgg["mes"])}'
            f' e a dívida líquida do setor público, em <strong>{pct(dlsp["v"], 1)}</strong>'
            + ("" if dlsp["mes"] == dbgg["mes"] else f' em {mes_nome(dlsp["mes"])}') + ". "
            f'No resultado primário, o setor público consolidado teve <strong>{resultado_txt(prim["v"])}</strong> em 12 meses até {mes_nome(prim["mes"])}; '
            f'no nominal, que inclui os juros, {resultado_txt(nom["v"])}.')
    hero = card('<span class="eyebrow">Contas públicas</span><h1>Dívida pública e resultado fiscal do Brasil</h1>' f'<p class="lede">{lede}</p>')

    def tl(rot, d, un, cor, resultado=False):
        extra = chg(d["dif12"], 1, " p.p.", " em 12 meses") if d["dif12"] is not None else ""
        if resultado:
            extra = f'<span class="chg flat">● {"superávit" if d["v"] > 0 else "déficit" if d["v"] < 0 else "equilíbrio"}</span>' + (" " + extra if extra else "")
        valor = sinal(d["v"], 1) if resultado else nf(d["v"], 1)
        return tile(f'{rot} · {mes_curtinho(d["mes"])}', valor, un, extra, cor)
    tiles = [tl("Dívida bruta", dbgg, "% do PIB", "a"), tl("Dívida líquida", dlsp, "% do PIB", "b"),
             tl("Primário, 12 meses", prim, "% do PIB", "k", True), tl("Nominal, 12 meses", nom, "% do PIB", "g", True)]

    def serie_dict(chave):
        return dict(f[chave]["serie"])
    d1, d2, d3, d4 = serie_dict("dbgg"), serie_dict("dlsp"), serie_dict("primario"), serie_dict("nominal")
    leg = lambda a, b: (f'<div class="leg"><span><i style="background:var(--eco)"></i>{a}</span>'
                        f'<span><i style="background:var(--eco2)"></i>{b}</span></div>')
    cm = sorted(set(d1) & set(d2))
    g1 = grafico(B, "divida-publica", "Dívida bruta e dívida líquida (% do PIB)", "Banco Central do Brasil (SGS 13762 e 4513)",
                 svg_linhas([{"vals": [d1[m] for m in cm], "cor": "a"}, {"vals": [d2[m] for m in cm], "cor": "b"}], [mes_curtinho(m) for m in cm],
                            "Gráfico da dívida bruta do governo geral e da dívida líquida do setor público, em % do PIB", unidade="% do PIB"),
                 ["Mês", "Dívida bruta (% do PIB)", "Dívida líquida (% do PIB)"], [(m, d1[m], d2[m]) for m in cm], "Contas públicas", casas=1,
                 legenda=leg("Dívida bruta (governo geral)", "Dívida líquida (setor público)"),
                 nota='<p class="small">A bruta soma o que o governo deve; a líquida desconta ativos do setor público, como as reservas internacionais.</p>',
                 ultimo=f"bruta {pct(dbgg['v'], 1)} ({mes_curto(dbgg['mes'])}); líquida {pct(dlsp['v'], 1)} ({mes_curto(dlsp['mes'])})",
                 csv_cab=["Mês", "Dívida bruta do governo geral (% do PIB)", "Dívida líquida do setor público (% do PIB)"],
                 csv_linhas=[(m, d1.get(m), d2.get(m)) for m in sorted(set(d1) | set(d2))])
    cr = sorted(set(d3) & set(d4))
    g2 = grafico(B, "resultado-fiscal", "Resultado primário e nominal em 12 meses (% do PIB)", "Banco Central do Brasil (SGS 5793 e 5727)",
                 svg_linhas([{"vals": [d3[m] for m in cr], "cor": "a"}, {"vals": [d4[m] for m in cr], "cor": "b"}], [mes_curtinho(m) for m in cr],
                            "Gráfico do resultado primário e do resultado nominal do setor público consolidado, acumulados em 12 meses, em % do PIB", zero=True, unidade="% do PIB (abaixo de zero = déficit)"),
                 ["Mês", "Primário (% do PIB)", "Nominal (% do PIB)"], [(m, d3[m], d4[m]) for m in cr], "Contas públicas",
                 legenda=leg("Resultado primário", "Resultado nominal (com juros)"),
                 nota='<p class="small">Soma dos últimos 12 meses, em % do PIB. Acima de zero é superávit; abaixo de zero, déficit.</p>',
                 ultimo=f"primário {sinal(prim['v'], 2)}% e nominal {sinal(nom['v'], 2)}% ({mes_curto(prim['mes'])})",
                 csv_cab=["Mês", "Resultado primário em 12 meses (% do PIB, negativo = déficit)", "Resultado nominal em 12 meses (% do PIB, negativo = déficit)"],
                 csv_linhas=[(m, d3.get(m), d4.get(m)) for m in sorted(set(d3) | set(d4))])
    rows = []
    for rot, d in (("Dívida bruta", dbgg), ("Dívida líquida", dlsp), ("Primário, 12 meses", prim), ("Nominal, 12 meses", nom)):
        rows.append([rot, mes_curtinho(d["mes"]), pct(d["v"], 2), f'{sinal(d["dif12"], 1)} p.p.' if d["dif12"] is not None else "–"])
    tab = card(cab("Últimas leituras", '<span class="src">Fonte: Banco Central</span>') +
               tabela(["Indicador", "Mês", "% do PIB", "Vs. 12m"], rows, ["l", "l", "r", "r"]) +
               '<span class="src">Os resultados fiscais usam sinal de saldo: negativo é déficit, positivo é superávit. Dívida bruta: governo geral; dívida líquida: setor público. A última coluna é a diferença, em pontos percentuais do PIB, para o mesmo mês um ano antes.</span>')
    foc = blocos_focus(B, FOCUS_FISCAL, "O que o mercado espera (Boletim Focus)", " Resultados fiscais: negativo é déficit. Em % do PIB.")
    linha = f'<div class="cols">{tab}{foc}</div>' if foc else tab
    texto = card("<h2>Como ler as contas públicas</h2>"
                 "<p>A <strong>dívida bruta do governo geral</strong> reúne o que o governo federal, o INSS e os governos estaduais e municipais devem. "
                 "A <strong>dívida líquida do setor público</strong> desconta desse total os ativos do setor público, como as reservas internacionais, e por isso costuma ser menor.</p>"
                 "<p>O <strong>resultado primário</strong> é a diferença entre o que o setor público arrecada e o que gasta, sem contar os juros da dívida. "
                 "O <strong>resultado nominal</strong> inclui os juros, e por isso mostra o quanto a dívida cresce por causa do saldo das contas. "
                 "Os dois são somados em 12 meses e divididos pelo PIB do mesmo período, para comparar anos diferentes.</p>"
                 "<p>Os números vêm do Banco Central, que divulga as estatísticas fiscais todo mês, com defasagem de cerca de um mês e meio a dois meses. "
                 "Este portal mostra dados e não opina sobre a política fiscal.</p>")
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div><div class="cols">{g1}{g2}</div>{linha}{texto}'
    return pagina(B, "/contas-publicas/", f"Contas públicas: dívida bruta de {pct(dbgg['v'], 1)} do PIB e resultado fiscal em 12 meses",
                  f"Dívida bruta de {pct(dbgg['v'], 1)} do PIB em {mes_nome(dbgg['mes'])} e {resultado_txt(prim['v'])} no resultado primário em 12 meses. "
                  "Dívida líquida, resultado nominal e projeções do Focus, com dados do Banco Central.",
                  corpo, "/contas-publicas/", [(None, "Contas públicas")])


def legenda_linhas(*itens) -> str:
    """Legenda de gráfico de linhas: itens (cor 'a'|'b'|'m', texto), na mesma ordem das séries."""
    cores = {"a": "var(--eco)", "b": "var(--eco2)", "m": "var(--muted)"}
    return '<div class="leg">' + "".join(f'<span><i style="background:{cores[c]}"></i>{t}</span>' for c, t in itens) + "</div>"


def colunas(blocos) -> str:
    """Blocos em pares lado a lado (um bloco sobrando fica sozinho)."""
    blocos = [b for b in blocos if b]
    return "".join(f'<div class="cols">{"".join(blocos[k:k + 2])}</div>' if len(blocos[k:k + 2]) == 2 else blocos[k] for k in range(0, len(blocos), 2))


def fim_do_mes(m: str) -> dt.date:
    a, n = int(m[:4]), int(m[5:])
    return dt.date(a + n // 12, n % 12 + 1, 1) - dt.timedelta(days=1)


def card_credito_inicio(B: Base) -> str:
    if not B.tem_credito:
        return ""
    c = B.cred_stats()
    jl, ip = c["juros_livre_pf"], c["inad_pf"]
    return card('<span class="eyebrow">Crédito</span><h2>Juros e inadimplência das famílias</h2>'
                f'<p>O crédito livre para pessoas físicas custava <strong>{pct(jl["v"], 1)} ao ano</strong> em {mes_nome(jl["mes"])}, '
                f'e a inadimplência das pessoas físicas era de <strong>{pct(ip["v"], 1)}</strong> da carteira.</p>'
                '<p><a href="/credito/">Ver juros, inadimplência, endividamento e comprometimento da renda →</a></p>')


def card_ibge_inicio(B: Base) -> str:
    S = B.ibge_series()
    partes = []
    for k, verbos in (("ind", ("cresceu", "recuou")), ("var", ("cresceu", "recuou"))):
        if k in S:
            u = B.ibge_ult(S[k]["med"])
            partes.append(f'{S[k]["sujeito"]} {verbo_var(u["mm"], 1, *verbos)} em {mes_nome(u["mes"])} frente ao mês anterior.')
    if not partes:
        return ""
    return card('<span class="eyebrow">Indústria e varejo</span><h2>Os dados mensais que saem antes do PIB</h2>'
                f'<p>{" ".join(partes)}</p><p><a href="/industria-e-varejo/">Ver produção industrial e vendas no varejo →</a></p>')


def pg_credito(B: Base) -> str:
    c = B.cred_stats()
    jl, jp, ip, il, en, co = (c[k] for k in ("juros_livre_pf", "juros_pf", "inad_pf", "inad_livre_pf", "endividamento", "comprometimento"))
    lede = (f'A taxa média de juros do crédito livre para pessoas físicas ficou em <strong>{pct(jl["v"], 1)} ao ano</strong> em {mes_nome(jl["mes"])}, '
            f'e a inadimplência da carteira de pessoas físicas, em <strong>{pct(ip["v"], 1)}</strong>. '
            f'As famílias deviam ao sistema financeiro o equivalente a <strong>{pct(en["v"], 1)} da renda de 12 meses</strong> '
            f'e usavam <strong>{pct(co["v"], 1)} da renda mensal</strong> no pagamento de dívidas'
            + ("" if en["mes"] == jl["mes"] else f' (dados de {mes_nome(en["mes"])})') + ".")
    hero = card('<span class="eyebrow">Crédito</span><h1>Crédito e inadimplência das famílias brasileiras</h1>' f'<p class="lede">{lede}</p>')

    def tl(rot, d, un, cor):
        extra = chg(d["dif12"], 1, " p.p.", " em 12 meses") if d["dif12"] is not None else ""
        return tile(f'{rot} · {mes_curtinho(d["mes"])}', nf(d["v"], 1), un, extra, cor)
    tiles = [tl("Juros do crédito livre", jl, "% ao ano", "a"), tl("Inadimplência PF", ip, "% da carteira", "b"),
             tl("Endividamento", en, "% da renda", "k"), tl("Comprometimento", co, "% da renda", "g")]

    djl, djp, dip, dil = dict(jl["serie"]), dict(jp["serie"]), dict(ip["serie"]), dict(il["serie"])
    sel = lambda m: B.selic_em(fim_do_mes(m))
    cm = sorted(set(djl) & set(djp))[-60:]
    g1 = grafico(B, "juros-credito-familias", "Juros do crédito às famílias e a Selic (% ao ano)", F_CRED_JUROS,
                 svg_linhas([{"vals": [djl[m] for m in cm], "cor": "b"}, {"vals": [djp[m] for m in cm], "cor": "a"},
                             {"vals": [sel(m) for m in cm], "cor": "m", "tracejada": True}], [mes_curtinho(m) for m in cm],
                            "Gráfico da taxa média de juros do crédito livre às pessoas físicas, do crédito total às pessoas físicas e da meta da Selic, em % ao ano, nos últimos 60 meses", zero=True, unidade="% ao ano"),
                 ["Mês", "Crédito livre PF", "Crédito PF total", "Meta da Selic"], [(m, djl[m], djp[m], sel(m)) for m in cm], "Crédito", casas=1,
                 legenda=legenda_linhas(("b", "Crédito livre (PF)"), ("a", "Crédito total (PF)"), ("m", "Meta da Selic")),
                 nota='<p class="small">Taxa média das operações contratadas no mês, em % ao ano. O crédito livre tem juros de mercado (cartão, cheque especial, crédito pessoal); a Selic é a meta no fim do mês.</p>',
                 ultimo=f"crédito livre {pct(jl['v'], 1)} ao ano ({mes_curto(jl['mes'])}); Selic {pct(sel(jl['mes']), 2)}",
                 csv_cab=["Mês", "Juros do crédito livre às pessoas físicas (% ao ano)", "Juros do crédito às pessoas físicas, total (% ao ano)", "Meta da Selic no fim do mês (% ao ano)"],
                 csv_linhas=[(m, djl.get(m), djp.get(m), sel(m)) for m in sorted(set(djl) | set(djp))])
    ci = sorted(set(dip) & set(dil))[-60:]
    g2 = grafico(B, "inadimplencia-familias", "Inadimplência das pessoas físicas (% da carteira)", F_CRED_INAD,
                 svg_linhas([{"vals": [dil[m] for m in ci], "cor": "b"}, {"vals": [dip[m] for m in ci], "cor": "a"}], [mes_curtinho(m) for m in ci],
                            "Gráfico da inadimplência da carteira de crédito das pessoas físicas, total e de crédito livre, em % da carteira, nos últimos 60 meses", unidade="% da carteira"),
                 ["Mês", "Crédito livre PF (%)", "Crédito PF total (%)"], [(m, dil[m], dip[m]) for m in ci], "Crédito", casas=1,
                 legenda=legenda_linhas(("b", "Crédito livre (PF)"), ("a", "Crédito total (PF)")),
                 nota='<p class="small">Parcela da carteira com atraso de mais de 90 dias.</p>',
                 ultimo=f"total {pct(ip['v'], 1)}; crédito livre {pct(il['v'], 1)} ({mes_curto(ip['mes'])})",
                 csv_cab=["Mês", "Inadimplência do crédito livre às pessoas físicas (% da carteira)", "Inadimplência do crédito às pessoas físicas, total (% da carteira)"],
                 csv_linhas=[(m, dil.get(m), dip.get(m)) for m in sorted(set(dip) | set(dil))])

    def uma(slug, titulo, fonte, d, unid, nota, cabc, csvc, cor="a"):
        s60 = d["serie"][-60:]
        return grafico(B, slug, titulo, fonte,
                       svg_linhas([{"vals": [v for _, v in s60], "cor": cor}], [mes_curtinho(m) for m, _ in s60], f"Gráfico de {titulo.lower()}, nos últimos 60 meses", unidade=unid),
                       ["Mês", cabc], s60, "Crédito", casas=1, nota=nota, ultimo=f"{pct(d['v'], 1)} ({mes_curto(d['mes'])})",
                       csv_cab=["Mês", csvc], csv_linhas=d["serie"])
    g3 = uma("endividamento-familias", "Endividamento das famílias (% da renda)", F_CRED_ENDIV, en, "% da renda de 12 meses",
             '<p class="small">Dívidas das famílias com o sistema financeiro, inclusive financiamento imobiliário, em relação à renda dos últimos 12 meses. Com ajuste sazonal.</p>',
             "Endividamento (%)", "Endividamento das famílias com o sistema financeiro (% da renda acumulada em 12 meses, com ajuste sazonal)")
    g4 = uma("comprometimento-renda", "Comprometimento da renda das famílias (%)", F_CRED_COMP, co, "% da renda mensal",
             '<p class="small">Pagamentos esperados de juros e principal das dívidas, em relação à renda mensal. Média móvel trimestral, com ajuste sazonal.</p>',
             "Comprometimento (%)", "Comprometimento de renda das famílias com o serviço da dívida (% da renda mensal, média móvel trimestral, com ajuste sazonal)", "b")

    rows = []
    for rot, d in (("Juros, crédito livre (% a.a.)", jl), ("Juros, crédito total (% a.a.)", jp), ("Inadimplência, total", ip), ("Inadimplência, crédito livre", il),
                   ("Endividamento", en), ("Comprometimento", co)):
        rows.append([rot, mes_curtinho(d["mes"]), nf(d["v"], 1), f'{sinal(d["dif12"], 1)} p.p.' if d["dif12"] is not None else "–"])
    tab = card(cab("Últimas leituras", '<span class="src">Fonte: Banco Central</span>') +
               tabela(["Indicador", "Mês", "Valor (%)", "Vs. 12m"], rows, ["l", "l", "r", "r"]) +
               '<span class="src">Todas as pessoas físicas, sem contar empresas. A última coluna é a diferença, em pontos percentuais, para o mesmo mês um ano antes.</span>')
    texto = card("<h2>Como ler os números do crédito</h2>"
                 "<p>Os <strong>juros</strong> são a taxa média cobrada nas operações contratadas no mês, em % ao ano. O <strong>crédito livre</strong> é o que os bancos precificam livremente (cartão de crédito, cheque especial, crédito pessoal, financiamento de veículos); "
                 "o crédito direcionado, como o financiamento imobiliário e o rural, tem regras e taxas próprias e não entra aí. Os juros do crédito livre ficam bem acima da Selic porque somam o custo do dinheiro para o banco, o risco de calote e a margem da instituição.</p>"
                 "<p>A <strong>inadimplência</strong> é a parcela da carteira de crédito com atraso de mais de 90 dias. "
                 "O <strong>endividamento</strong> compara o saldo das dívidas com a renda das famílias nos últimos 12 meses, e o <strong>comprometimento de renda</strong> mostra quanto da renda mensal vai para pagar juros e parte do principal. "
                 "Os dois últimos usam ajuste sazonal e saem com mais defasagem, de até oito semanas.</p>"
                 '<p>O Banco Central divulga as estatísticas de crédito todo mês. Para acompanhar a Selic, veja <a href="/juros/">Juros e Copom</a>. '
                 "Este portal mostra dados e não é recomendação de crédito nem de investimento.</p>")
    foc = blocos_focus(B, {k: FOCUS_PRINCIPAL[k] for k in ("Selic", "IPCA")}, "O que o mercado espera para a Selic e a inflação (Boletim Focus)")
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div>{colunas([g1, g2, g3, g4])}{colunas([tab, foc])}{texto}'
    return pagina(B, "/credito/", f"Crédito e inadimplência das famílias: juros de {pct(jl['v'], 1)} ao ano no crédito livre",
                  f"Juros do crédito livre de {pct(jl['v'], 1)} ao ano e inadimplência de {pct(ip['v'], 1)} entre pessoas físicas em {mes_nome(jl['mes'])}. "
                  "Endividamento e comprometimento da renda das famílias, com dados do Banco Central.",
                  corpo, "/credito/", [(None, "Crédito")])


def pg_ind_var(B: Base) -> str:
    S = B.ibge_series()
    U = {k: B.ibge_ult(S[k]["med"]) for k in S}
    lede = []
    for k, verbos in (("ind", ("cresceu", "recuou")), ("var", ("cresceu", "recuou"))):
        if k not in S:
            continue
        u = U[k]
        t = f'{S[k]["sujeito"]} <strong>{verbo_var(u["mm"], 1, *verbos)}</strong> em {mes_nome(u["mes"])} frente ao mês anterior (com ajuste sazonal)'
        if u["yoy"] is not None:
            ref = f'{MESES[int(u["mes"][5:]) - 1]} de {int(u["mes"][:4]) - 1}'
            t += (f' e ficou no mesmo nível de {ref}' if round(abs(u["yoy"]), 1) == 0
                  else f' e ficou {nf(abs(u["yoy"]), 1)}% {"acima" if u["yoy"] > 0 else "abaixo"} do nível de {ref}')
        lede.append(t + ".")
    h1 = ("Produção industrial e vendas no varejo: os dados que saem antes do PIB" if "ind" in S and "var" in S
          else "Produção industrial do Brasil: um dado que sai antes do PIB" if "ind" in S else "Vendas no varejo do Brasil: um dado que sai antes do PIB")
    hero = card(f'<span class="eyebrow">Indústria e varejo</span><h1>{h1}</h1><p class="lede">{" ".join(lede)}</p>')

    tiles, cores = [], iter("abkg")
    for k in ("ind", "var") if ("ind" in S or "var" in S) else ("amp",):   # o ampliado aparece nos gráficos e na tabela
        if k not in S:
            continue
        u = U[k]
        tiles.append(tile(f'{S[k]["curto"]} vs. mês anterior · {mes_curtinho(u["mes"])}', sinal(u["mm"], 1), "%", '<span class="chg flat">● com ajuste sazonal</span>', next(cores)))
        if u["yoy"] is not None:
            tiles.append(tile(f'{S[k]["curto"]} vs. mesmo mês · {mes_curtinho(u["mes"])}', sinal(u["yoy"], 1), "%", "", next(cores)))

    def dic(k, med):
        return dict((m, float(x)) for m, x in S[k]["med"].get(med) or [])
    cor = {"ind": "a", "var": "b", "amp": "m"}
    graf = []

    def linhas(slug, titulo, med, unid, nota, cab_csv, aria, zero, casas, suf="", fontes_k=None):
        ks = [k for k in (fontes_k or S) if dic(k, med)]
        if not ks:
            return
        ds = {k: dic(k, med) for k in ks}
        cm = sorted(set.intersection(*[set(d) for d in ds.values()]))[-36:]
        if len(cm) < 3:
            return
        todos = sorted(set().union(*[set(d) for d in ds.values()]))
        fonte = F_PIM if ks == ["ind"] else F_PMC if "ind" not in ks else f"{F_PIM}; {F_PMC}"
        graf.append(grafico(B, slug, titulo, fonte,
                            svg_linhas([{"vals": [ds[k][m] for m in cm], "cor": cor[k], "tracejada": k == "amp"} for k in ks], [mes_curtinho(m) for m in cm], aria, zero=zero, unidade=unid),
                            ["Mês"] + [S[k]["curto"] for k in ks], [(m, *[ds[k][m] for k in ks]) for m in cm], "Indústria e varejo", casas=casas,
                            legenda=legenda_linhas(*[(cor[k], S[k]["nome"]) for k in ks]) if len(ks) > 1 else "", nota=nota,
                            ultimo="; ".join(f"{S[k]['curto'].lower()} {nf(ds[k][max(ds[k])], casas)}{suf} ({mes_curto(max(ds[k]))})" for k in ks),
                            csv_cab=["Mês"] + [f"{S[k]['nome']} ({cab_csv})" for k in ks], csv_linhas=[(m, *[ds[k].get(m) for k in ks]) for m in todos]))
    linhas("industria-varejo-indice", "Produção industrial e vendas no varejo: índice", "sa", "Índice (2022 = 100)",
           '<p class="small">Índice com ajuste sazonal, base 2022 = 100, nos últimos 36 meses. Acima de 100, o nível está acima da média de 2022.</p>',
           "índice 2022=100, com ajuste sazonal", "Gráfico dos índices de produção industrial e de vendas no varejo, com ajuste sazonal, base 2022 igual a 100, nos últimos 36 meses", False, 1)
    linhas("industria-varejo-12m", "Variação contra o mesmo mês do ano anterior", "yoy", "% sobre o mesmo mês do ano anterior",
           '<p class="small">Compara cada mês com o mesmo mês um ano antes, sem ajuste sazonal. Abaixo de zero, o mês foi pior que o de um ano atrás.</p>',
           "% sobre o mesmo mês do ano anterior", "Gráfico da variação da produção industrial e das vendas no varejo contra o mesmo mês do ano anterior, nos últimos 36 meses", True, 1, "%")

    def barras(k, slug, titulo, aria):
        if k not in S:
            return
        d = dic(k, "mm")
        ms = sorted(d)[-24:]
        u = U[k]
        graf.append(grafico(B, slug, titulo, S[k]["fonte"],
                            svg_barras([d[m] for m in ms], [mes_curtinho(m) for m in ms], aria, unidade="% sobre o mês anterior"),
                            ["Mês", "Vs. mês anterior (%)"], [(m, d[m]) for m in ms], "Indústria e varejo", casas=1,
                            nota='<p class="small">Em %, com ajuste sazonal, comparando cada mês com o anterior. Os dois últimos anos.</p>',
                            ultimo=f"{mes_curto(u['mes'])}: {sinal(u['mm'], 1)}%", csv_cab=["Mês", f"{S[k]['nome']}: variação sobre o mês anterior, com ajuste sazonal (%)"],
                            csv_linhas=[(m, v) for m, v in sorted(d.items())]))
    barras("ind", "producao-industrial-mensal", "Produção industrial: variação sobre o mês anterior", "Gráfico de barras da variação mensal da produção industrial, com ajuste sazonal, nos últimos 24 meses")
    barras("var", "varejo-mensal", "Vendas no varejo: variação sobre o mês anterior", "Gráfico de barras da variação mensal do volume de vendas no varejo, com ajuste sazonal, nos últimos 24 meses")
    linhas("industria-varejo-acumulado", "Acumulado em 12 meses", "a12", "% acumulado em 12 meses",
           '<p class="small">Variação do volume nos últimos 12 meses contra os 12 meses anteriores: mostra a tendência, sem o ruído de cada mês.</p>',
           "% acumulado em 12 meses", "Gráfico da variação acumulada em 12 meses da produção industrial e das vendas no varejo, nos últimos 36 meses", True, 1, "%")

    rows = []
    for k in S:
        u = U[k]
        rows.append([S[k]["curto"], mes_curtinho(u["mes"]), pct_sinal(u["mm"]), pct_sinal(u["yoy"]), pct_sinal(u["a12"])])
    tab = card(cab("Últimas leituras", '<span class="src">Fonte: IBGE</span>') +
               tabela(["Indicador", "Mês", "Vs. mês ant.", "Vs. mesmo mês", "12 meses"], rows, ["l", "l", "r", "r", "r"]) +
               '<span class="src">Volume físico (produção) e volume de vendas, sem efeito de preços. A variação sobre o mês anterior usa série com ajuste sazonal; as demais comparam com o mesmo período do ano anterior.</span>')
    texto = card("<h2>Como ler a indústria e o varejo</h2>"
                 "<p>A <strong>produção industrial</strong> vem da Pesquisa Industrial Mensal do IBGE e mede o volume produzido pela indústria extrativa e de transformação. "
                 "O <strong>volume de vendas do varejo</strong> vem da Pesquisa Mensal de Comércio, que acompanha lojas e supermercados descontando a inflação; "
                 "o <strong>varejo ampliado</strong> acrescenta veículos, motos, partes e peças, material de construção e atacado de alimentos, bebidas e fumo.</p>"
                 "<p>Os dois saem cerca de um mês e meio depois do mês de referência, bem antes do PIB trimestral, e por isso servem de pista sobre o que o PIB vai mostrar. "
                 "O <strong>ajuste sazonal</strong> tira o efeito de épocas do ano, como o Natal ou as férias coletivas, para comparar um mês com o anterior.</p>"
                 '<p>Para o quadro completo, veja <a href="/atividade/">PIB e IBC-Br</a>. Este portal mostra dados e não faz recomendação de investimento.</p>')
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div>{colunas(graf + [tab])}{texto}'
    partes = [(S[k]["nome"].lower(), U[k]) for k in ("ind", "var") if k in S] or [(S["amp"]["nome"].lower(), U["amp"])]
    titulo = " e ".join(f"{n} {sinal(u['mm'], 1)}% em {MESES[int(u['mes'][5:]) - 1]}" for n, u in partes)
    desc = " e ".join(f"{n} {sinal(u['mm'], 1)}% sobre o mês anterior em {mes_nome(u['mes'])}" for n, u in partes)
    return pagina(B, "/industria-e-varejo/", titulo[0].upper() + titulo[1:],
                  desc[0].upper() + desc[1:] + " (com ajuste sazonal). Dados do IBGE, com gráficos, tabelas e CSV.",
                  corpo, "/industria-e-varejo/", [(None, "Indústria e varejo")])


def pg_cambio(B: Base) -> str:
    c = B.cambio_stats()
    dia = c["dia"]
    lede = f'O dólar fechou a <strong>R$ {nf(c["ult"], 2)}</strong> em {data_br(c["data"])} (cotação de venda do Banco Central)'
    if dia is not None:
        lede += f', {verbo_var(dia, 2, "em alta de", "em queda de").replace("ficou estável", "estável")} no dia'
    lede += "."
    if c["ano"] is not None and c["a12"] is not None:
        lede += f' No ano, {verbo_var(c["ano"], 1, "alta de", "queda de").replace("ficou estável", "variação nula")}; em 12 meses, {verbo_var(c["a12"], 1, "alta de", "queda de").replace("ficou estável", "variação nula")}.'
    hero = card('<span class="eyebrow">Câmbio</span><h1>Dólar hoje e histórico: último fechamento e variação</h1>' f'<p class="lede">{lede}</p>')
    tiles = [tile("Dólar (venda)", f'R$ {nf(c["ult"], 2)}', "", chg(dia, 2, "%", " no dia") if dia is not None else "", "a")]
    for rot, k, cor in (("No mês", "mes", "b"), ("No ano", "ano", "k"), ("Em 12 meses", "a12", "g")):
        if c[k] is not None:
            tiles.append(tile(rot, sinal(c[k], 2), "%", "", cor))
    s12 = c["serie12"]
    g1 = grafico(B, "dolar-diario", "Dólar nos últimos 12 meses", F_CAMBIO,
                 svg_linhas([{"vals": [v for _, v in s12], "cor": "a"}], [mes_curtinho(x.strftime("%Y-%m")) for x, _ in s12],
                            "Gráfico da cotação de venda do dólar em reais nos últimos 12 meses", unidade="R$ por US$"),
                 ["Data", "Dólar venda (R$ por US$)"], [(x.isoformat(), v) for x, v in s12], "Câmbio",
                 nota=f'<p class="small">Cotação de venda, em R$ por US$, a cada dia útil. Mínima em 12 meses: R$ {nf(c["min12"], 2)}; máxima: R$ {nf(c["max12"], 2)}.</p>',
                 ultimo=f"{data_br(c['data'])}: R$ {nf(c['ult'], 2)}",
                 csv_cab=["Data", "Dólar venda (R$ por US$)"], csv_linhas=[(a, float(v)) for a, v in B.cambio["diario"]])
    m = c["mensal"]
    g2 = grafico(B, "dolar-mensal", "Dólar desde 2016 (média mensal)", F_CAMBIO,
                 svg_linhas([{"vals": [v for _, v in m], "cor": "b"}], [mes_curtinho(x) for x, _ in m],
                            "Gráfico da média mensal da cotação do dólar em reais desde 2016", unidade="R$ por US$ (média do mês)"),
                 ["Mês", "Média do mês (R$ por US$)"], m, "Câmbio",
                 nota='<p class="small">Média das cotações de venda de cada mês, em R$ por US$.</p>',
                 ultimo=f"{mes_nome(m[-1][0])}: R$ {nf(m[-1][1], 2)} (média)",
                 csv_cab=["Mês", "Média do mês (R$ por US$)", "Fechamento do mês (R$ por US$)"],
                 csv_linhas=[(a, float(b), float(f)) for a, b, f in B.cambio["mensal"]]) if len(m) >= 24 else ""
    graficos = f'<div class="cols">{g1}{g2}</div>' if g2 else g1
    rows = [[data_br(x), nf(v, 2), chg(vr, 2, "%") if vr is not None else "–"] for x, v, vr in c["linhas"]]
    tab = card(cab("Últimas cotações", '<span class="src">Fonte: Banco Central</span>') +
               tabela(["Data", "Venda (R$)", "No dia"], rows, ["l", "r", "r"]))
    foc = ""
    anos = [a for a in (B.hoje.year, B.hoje.year + 1) if focus_item(B, "Câmbio", a)]
    if anos:
        frows = []
        for a in anos:
            it = focus_item(B, "Câmbio", a)
            frows.append([str(a), f'R$ {nf(it["mediana"], 2)}', pct_sinal(var_pct(it["mediana"], c["ult"]), 1),
                          chg(it["mediana"] - it["semana_anterior"], 2, "") if it.get("semana_anterior") is not None else "–"])
        dfoc = data_br(dt.date.fromisoformat(B.focus["data"]))
        foc = card(cab("O que o mercado espera (Boletim Focus)") +
                   tabela(["Fim de", "Mediana", "Vs. atual", "Semana"], frows, ["l", "r", "r", "r"]) +
                   f'<span class="src">Mediana das projeções do mercado para o câmbio ao fim de cada ano, em R$ por US$ (posição de {dfoc}). "Vs. atual" compara com o último fechamento; "Semana" é a variação da projeção desde o boletim anterior. Fonte: Banco Central.</span>')
    linha = f'<div class="cols">{tab}{foc}</div>' if foc else tab
    texto = card("<h2>Como ler a cotação do dólar</h2>"
                 "<p>A série desta página é a <strong>cotação de venda do dólar</strong> calculada pelo Banco Central a partir do Sistema PTAX, uma por dia útil, "
                 "e é a referência usada em contratos e relatórios. O site atualiza os números quando o Banco Central os divulga.</p>"
                 "<p>Aplicativos e corretoras mostram a cotação em tempo real, que muda a cada segundo e pode ficar diferente do fechamento do Banco Central. "
                 "Variações de poucos centavos no dia fazem parte da oscilação normal do mercado.</p>"
                 "<p>As projeções são do Boletim Focus e refletem a opinião média de instituições financeiras; não são garantia do que vai acontecer. "
                 "Este portal mostra dados e não recomenda compra ou venda de moeda.</p>")
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div>{graficos}{linha}{texto}'
    return pagina(B, "/cambio/", f"Dólar hoje: R$ {nf(c['ult'], 2)} no último fechamento ({data_br(c['data'])}) e histórico",
                  f"Dólar a R$ {nf(c['ult'], 2)} no fechamento de {data_br(c['data'])}. Cotação de venda do Banco Central, variação no dia, no mês e em 12 meses, histórico desde 2016 e projeções do Boletim Focus.",
                  corpo, "/cambio/", [(None, "Câmbio")])


def pg_atividade(B: Base) -> str:
    r = B.pib_ref() if B.tem_pib else None
    i = B.ibc_stats() if B.tem_ibc else None
    lede = []
    if r:
        t = f'O PIB do Brasil <strong>{verbo_var(r["qoq"], 1)}</strong> no {rot_tri(r["t"], True)} em relação ao trimestre anterior (com ajuste sazonal)'
        if r.get("yoy") is not None:
            t += f' e {verbo_var(r["yoy"], 1, "avançou", "recuou")} na comparação com o mesmo trimestre de {int(r["t"][:4]) - 1}'
        lede.append(t + ".")
    if i:
        lede.append(f'O IBC-Br, indicador mensal do Banco Central, <strong>{verbo_var(i["mm"], 1, "subiu", "caiu")}</strong> em {mes_nome(i["mes"])} frente ao mês anterior (com ajuste sazonal).')
    hero = card('<span class="eyebrow">Atividade econômica</span><h1>PIB e IBC-Br: o ritmo da economia brasileira</h1>' f'<p class="lede">{" ".join(lede)}</p>')
    tiles = []
    if r:
        tiles.append(tile("PIB vs. trimestre anterior", sinal(r["qoq"], 1), "%", f'<span class="chg flat">● {rot_tri(r["t"])}, com ajuste sazonal</span>', "a"))
        if r.get("yoy") is not None:
            tiles.append(tile("PIB vs. mesmo trimestre", sinal(r["yoy"], 1), "%", "", "b"))
        if r.get("a4") is not None:
            tiles.append(tile("PIB em 4 trimestres", sinal(r["a4"], 1), "%", "", "k"))
    if i:
        tiles.append(tile(f"IBC-Br em {MES_CURTO[int(i['mes'][5:]) - 1]}", sinal(i["mm"], 1), "%", '<span class="chg flat">● vs. mês anterior</span>', "g"))
        if len(tiles) < 4 and i["a12"] is not None:
            tiles.append(tile("IBC-Br em 12 meses", sinal(i["a12"], 1), "%", "", "k"))
    graf = []
    if r:
        u12 = [x for x in B.pib if x.get("qoq") is not None][-12:]
        graf.append(grafico(B, "pib-trimestral", "PIB: variação sobre o trimestre anterior", F_PIB,
                            svg_barras([x["qoq"] for x in u12], [rot_tri(x["t"]) for x in u12], "Gráfico de barras da variação trimestral do PIB, com ajuste sazonal, nos últimos 12 trimestres", unidade="% sobre o trimestre anterior"),
                            ["Trimestre", "Vs. trim. anterior (%)"], [(rot_tri(x["t"], True), x["qoq"]) for x in u12], "Atividade",
                            nota='<p class="small">Em %, com ajuste sazonal, comparando cada trimestre com o anterior.</p>',
                            ultimo=f"{rot_tri(r['t'], True)}: {sinal(r['qoq'], 1)}%",
                            csv_cab=["Trimestre", "Variação sobre o trimestre anterior, com ajuste sazonal (%)", "Variação sobre o mesmo trimestre do ano anterior (%)", "Variação acumulada em 4 trimestres (%)"],
                            csv_linhas=[(chave_tri(x["t"]), x.get("qoq"), x.get("yoy"), x.get("a4")) for x in B.pib]))
    if i:
        s36 = i["sa"][-36:]
        nsa = {m: v for m, v in B.ibc["nsa"]}
        graf.append(grafico(B, "ibcbr", "IBC-Br: nível da atividade", F_IBC,
                            svg_linhas([{"vals": [v for _, v in s36], "cor": "a"}], [mes_curtinho(m) for m, _ in s36], "Gráfico do índice IBC-Br com ajuste sazonal nos últimos 36 meses", unidade="Índice, com ajuste sazonal"),
                            ["Mês", "IBC-Br (índice)"], s36, "Atividade",
                            nota='<p class="small">Índice com ajuste sazonal, nos últimos 36 meses. O IBC-Br é uma aproximação mensal do PIB; o que importa é a direção, não o valor absoluto.</p>',
                            ultimo=f"{mes_nome(i['mes'])}: {nf(s36[-1][1], 2)}",
                            csv_cab=["Mês", "IBC-Br com ajuste sazonal (índice)", "IBC-Br sem ajuste sazonal (índice)"],
                            csv_linhas=[(m, float(v), float(nsa[m]) if m in nsa else None) for m, v in i["sa"]]))
    graficos = f'<div class="cols">{"".join(graf)}</div>' if len(graf) == 2 else "".join(graf)
    tabs = []
    if r:
        rows = [[rot_tri(x["t"], True), pct_sinal(x.get("qoq")), pct_sinal(x.get("yoy")), pct_sinal(x.get("a4"))] for x in [y for y in B.pib if y.get("qoq") is not None][-8:][::-1]]
        tabs.append(card(cab("PIB por trimestre", '<span class="src">Fonte: IBGE</span>') +
                         tabela(["Trimestre", "Vs. trim. anterior", "Vs. mesmo trim.", "4 trimestres"], rows, ["l", "r", "r", "r"]) +
                         '<span class="src">Variações do PIB em volume. A primeira coluna usa série com ajuste sazonal; as demais, comparações com o mesmo período do ano anterior.</span>'))
    if i:
        rows = [[mes_nome(m), nf(v, 1), pct_sinal(vr)] for m, v, vr in i["linhas"]]
        tabs.append(card(cab("IBC-Br mês a mês", '<span class="src">Fonte: Banco Central</span>') +
                         tabela(["Mês", "Índice", "Vs. mês anterior"], rows, ["l", "r", "r"]) +
                         '<span class="src">Série com ajuste sazonal.</span>'))
    tab = f'<div class="cols">{"".join(tabs)}</div>' if len(tabs) == 2 else "".join(tabs)
    foc = ""
    anos = [a for a in (B.hoje.year, B.hoje.year + 1) if focus_item(B, "PIB Total", a)]
    if anos:
        frows = []
        for a in anos:
            it = focus_item(B, "PIB Total", a)
            frows.append([str(a), pct(it["mediana"], 2), chg(it["mediana"] - it["semana_anterior"], 2, "") if it.get("semana_anterior") is not None else "–"])
        foc = card(cab("O que o mercado espera para o PIB (Boletim Focus)") + tabela(["Ano", "Crescimento esperado", "Semana"], frows, ["l", "r", "r"]) +
                   f'<span class="src">Mediana das projeções do mercado (posição de {data_br(dt.date.fromisoformat(B.focus["data"]))}). Fonte: Banco Central.</span>')
    texto = card("<h2>Como ler os indicadores de atividade</h2>"
                 "<p>O <strong>PIB</strong> é a soma de tudo o que a economia produz, medido pelo IBGE a cada trimestre. "
                 "As variações em volume descontam a inflação, e o ajuste sazonal tira o efeito de épocas do ano em que a produção costuma subir ou cair.</p>"
                 "<p>O <strong>IBC-Br</strong> é um índice mensal do Banco Central que reúne dados de agropecuária, indústria, serviços e impostos para estimar o ritmo da economia. "
                 "Serve de termômetro antes de o PIB sair, mas não é a medida oficial e pode ser diferente do PIB do IBGE.</p>"
                 + ('<p>Os dados mensais de <a href="/industria-e-varejo/">produção industrial e vendas no varejo</a>, do IBGE, também saem antes do PIB.</p>' if B.tem_ibge else ""))
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div>{graficos}{tab}{foc}{texto}'
    if r:
        titulo = f"PIB do Brasil: {sinal(r['qoq'], 1)}% no {rot_tri(r['t'], True)} e IBC-Br atualizado"
        desc = f"PIB de {sinal(r['qoq'], 1)}% sobre o trimestre anterior no {rot_tri(r['t'], True)}" + (f" e IBC-Br de {mes_nome(i['mes'])}" if i else "") + ". Dados do IBGE e do Banco Central, com gráficos, tabelas e projeções do Focus."
    else:
        titulo = f"IBC-Br: atividade econômica em {mes_nome(i['mes'])}"
        desc = f"IBC-Br de {mes_nome(i['mes'])}: {sinal(i['mm'], 1)}% sobre o mês anterior. Dados do Banco Central, com gráfico e tabela."
    return pagina(B, "/atividade/", titulo, desc, corpo, "/atividade/", [(None, "Atividade")])


def _mensal_tabela(B: Base, linhas_meses, rot_area=None, area=None) -> str:
    rows = []
    for m in linhas_meses:
        br = B.ipca_m.get(m)
        if area is None:
            rows.append([mes_curto(m), pct(br, 2) if br is not None else "–", pct(B.ipca_12[m], 2) if m in B.ipca_12 else "–"])
        else:
            a = area["mensal"].get(m)
            dif = f"{sinal(a - br, 2)} p.p." if a is not None and br is not None else "–"
            rows.append([mes_curto(m), pct(a, 2) if a is not None else "–", pct(br, 2) if br is not None else "–", dif])
    return rows


def pg_inflacao(B: Base) -> str:
    ref = B.ref
    ms36 = B.meses_ipca(36)
    ms24 = B.meses_ipca(24)
    ms12 = B.meses_ipca(12)[::-1]
    ytd = B.ytd(B.ipca_m, ref)
    hero = card('<span class="eyebrow">Preços ao consumidor</span><h1>Inflação (IPCA) no Brasil e em 16 regiões</h1>'
                f'<p class="lede">O IPCA acumulou <strong>{pct(B.ipca_12[ref], 2)}</strong> em 12 meses até {mes_nome(ref)}, '
                f'com alta de <strong>{pct(B.ipca_m[ref], 2)}</strong> no mês. O IBGE mede os preços em 16 áreas, e cada uma tem a sua página.</p>')
    tiles = [tile("IPCA em 12 meses", nf(B.ipca_12[ref], 2), "%", "", "b"), tile(f"IPCA em {MESES[int(ref[5:]) - 1]}", nf(B.ipca_m[ref], 2), "%", "", "k")]
    if ytd is not None:
        tiles.append(tile(f"Acumulado em {ref[:4]}", nf(ytd, 2), "%", "", "a"))
    tiles.append(tile("Meta de inflação", "3,00", "% ± 1,5", "", "g"))
    g12 = grafico(B, "ipca-12-meses", "IPCA acumulado em 12 meses", F_IPCA,
                  svg_linhas([{"vals": [B.ipca_12[m] for m in ms36], "cor": "b"}], [mes_curtinho(m) for m in ms36],
                             "Gráfico do IPCA acumulado em 12 meses nos últimos 36 meses", unidade="% acumulado em 12 meses"),
                  ["Mês", "IPCA em 12 meses (%)"], [(m, B.ipca_12[m]) for m in ms36], "Inflação",
                  ultimo=f"{mes_nome(ref)}: {pct(B.ipca_12[ref], 2)}", csv_linhas=[(m, B.ipca_12[m]) for m in sorted(B.ipca_12)])
    ms24v = [m for m in ms24 if m in B.ipca_m]
    gm = grafico(B, "ipca-mensal", "IPCA mensal", F_IPCA,
                 svg_barras([B.ipca_m[m] for m in ms24v], [mes_curtinho(m) for m in ms24v], "Gráfico de barras do IPCA mensal nos últimos 24 meses", unidade="% no mês"),
                 ["Mês", "IPCA no mês (%)"], [(m, B.ipca_m[m]) for m in ms24v], "Inflação",
                 ultimo=f"{mes_nome(ref)}: {pct(B.ipca_m[ref], 2)}", csv_linhas=[(m, B.ipca_m[m]) for m in sorted(B.ipca_m)])
    rk = B.ranking()
    reg = ""
    if rk:
        linhas = [(f'<a href="/inflacao/{a["slug"]}/">{esc(a["nome"])} ({a["uf"]})</a>', a["acum12"][B.ref_areas], pct(a["acum12"][B.ref_areas], 2),
                   f'no mês: {pct(a["mensal"][B.ref_areas], 2)}' if B.ref_areas in a["mensal"] else "") for a in rk]
        reg = card(cab("Por região", f'<span class="src">12 meses até {mes_nome(B.ref_areas)}</span>') + hbarras(linhas, "IPCA acumulado em 12 meses (%)") +
                   '<span class="src">Áreas pesquisadas pelo IBGE: 10 regiões metropolitanas e os municípios de Brasília, Goiânia, Campo Grande, Rio Branco, São Luís e Aracaju. Fonte: IBGE.</span>')
    tab = card(cab("Últimos 12 meses") + tabela(["Mês", "No mês", "Em 12 meses"], _mensal_tabela(B, ms12), ["l", "r", "r"]))
    texto = card("<h2>Como ler o IPCA</h2>"
                 "<p>O IPCA (Índice Nacional de Preços ao Consumidor Amplo), calculado pelo IBGE, é a medida oficial de inflação do país. "
                 "Ele acompanha a variação dos preços de uma cesta de produtos e serviços consumida por famílias com rendimento de 1 a 40 salários mínimos.</p>"
                 "<p>A meta de inflação, definida pelo Conselho Monetário Nacional, é de 3%, com tolerância de 1,5 ponto percentual para mais ou para menos. "
                 "O Banco Central usa a taxa Selic para tentar levar o IPCA à meta.</p>")
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div><div class="cols">{g12}{gm}</div>{tab}{reg}{texto}'
    return pagina(B, "/inflacao/", f"IPCA: inflação de {pct(B.ipca_12[ref], 2)} em 12 meses ({mes_nome(ref)}) e por região",
                  f"IPCA acumulado em 12 meses: {pct(B.ipca_12[ref], 2)} até {mes_nome(ref)}. Veja a inflação por região metropolitana e capital, mês a mês, com dados do IBGE.",
                  corpo, "/inflacao/", [(None, "Inflação")])


def pg_area(B: Base, a: dict) -> str:
    ref = B.ref_areas
    rk = B.ranking()
    pos = next((i for i, x in enumerate(rk) if x["slug"] == a["slug"]), None)
    v12 = a["acum12"][ref]
    br12 = B.ipca_12.get(ref)
    vm = a["mensal"].get(ref)
    ytd = B.ytd(a["mensal"], ref)
    tipo = "município" if a["slug"] in MUNICIPIOS else "região metropolitana"
    nome_uf = f'{a["nome"]} ({a["uf"]})'
    rel = ""
    if br12 is not None:
        dif = v12 - br12
        rel = (f' A inflação local ficou {"acima" if dif > 0 else "abaixo" if dif < 0 else "igual à"} '
               + ("" if dif == 0 else f"da média nacional ({pct(br12, 2)}) em {nf(abs(dif), 2)} ponto percentual. " if True else ""))
    rank_txt = f" Foi a {ordinal_f(pos + 1)} maior inflação entre as {len(rk)} áreas pesquisadas pelo IBGE." if pos is not None else ""
    hero = card(f'<span class="eyebrow">IPCA · {tipo}</span><h1>Inflação em {esc(nome_uf)}: IPCA de {mes_nome(ref)}</h1>'
                f'<p class="lede">O IPCA em {esc(a["nome"])} acumulou <strong>{pct(v12, 2)}</strong> em 12 meses até {mes_nome(ref)}.{rel}{rank_txt}</p>')
    tiles = [tile("IPCA em 12 meses", nf(v12, 2), "%", "", "b")]
    if vm is not None:
        tiles.append(tile(f"IPCA em {MESES[int(ref[5:]) - 1]}", nf(vm, 2), "%", "", "k"))
    if ytd is not None:
        tiles.append(tile(f"Acumulado em {ref[:4]}", nf(ytd, 2), "%", "", "a"))
    if br12 is not None:
        tiles.append(tile("Brasil em 12 meses", nf(br12, 2), "%", "", "g"))
    comuns = [m for m in sorted(a["acum12"]) if m in B.ipca_12][-24:]
    series = [{"vals": [a["acum12"][m] for m in comuns], "cor": "b"}, {"vals": [B.ipca_12[m] for m in comuns], "cor": "m", "tracejada": True}]
    todos = [m for m in sorted(a["acum12"]) if m in B.ipca_12]
    graf = grafico(B, f"ipca-12m-{a['slug']}", f"IPCA em 12 meses: {esc(a['nome'])} e Brasil", F_IPCA_AREA,
                   svg_linhas(series, [mes_curtinho(m) for m in comuns], f"Gráfico do IPCA acumulado em 12 meses em {a['nome']} e no Brasil", unidade="% acumulado em 12 meses"),
                   ["Mês", f'{a["nome"]} (%)', "Brasil (%)"], [(m, a["acum12"][m], B.ipca_12[m]) for m in comuns], "Inflação por área",
                   legenda=f'<div class="leg"><span><i style="background:var(--eco2)"></i>{esc(a["nome"])}</span><span><i style="background:var(--muted)"></i>Brasil</span></div>',
                   ultimo=f"{mes_nome(ref)}: {pct(v12, 2)}",
                   csv_cab=["Mês", f"IPCA em 12 meses {a['nome']} (%)", "IPCA em 12 meses Brasil (%)"],
                   csv_linhas=[(m, a["acum12"][m], B.ipca_12[m]) for m in todos])
    ult12 = sorted(a["mensal"])[-12:][::-1]
    tab = card(cab("Mês a mês") + tabela(["Mês", esc(a["nome"]), "Brasil", "Diferença"], _mensal_tabela(B, ult12, area=a), ["l", "r", "r", "r"]))
    outras = card(cab("Outras áreas") + lista_links([(f'/inflacao/{x["slug"]}/', f'{esc(x["nome"])} ({x["uf"]})', pct(x["acum12"][ref], 2)) for x in rk if x["slug"] != a["slug"]]) +
                  '<p class="small"><a href="/inflacao/">← Inflação no Brasil e nas 16 áreas</a></p>')
    texto = card(f"<h2>O que o IPCA de {esc(a['nome'])} mede</h2>"
                 f"<p>O IBGE calcula o IPCA em 16 áreas do país. Neste caso, a área é o {tipo} de {esc(a['nome'])}: os preços são coletados nesse território e ponderados "
                 "pela estrutura de consumo das famílias de lá. Por isso a inflação local pode ficar acima ou abaixo da média do Brasil.</p>")
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div>{graf}<div class="cols">{tab}{outras}</div>{texto}'
    return pagina(B, f"/inflacao/{a['slug']}/", f"Inflação em {a['nome']} ({a['uf']}): IPCA de {pct(v12, 2)} em 12 meses",
                  f"IPCA em {a['nome']} ({a['uf']}): {pct(v12, 2)} em 12 meses até {mes_nome(ref)}, comparado ao Brasil. Série mensal e ranking entre as 16 áreas do IBGE.",
                  corpo, "/inflacao/", [("/inflacao/", "Inflação"), (None, a["nome"])])


def pg_calc(B: Base) -> str:
    dados = json.dumps([[k, v] for k, v in sorted(B.ipca_m.items())], separators=(",", ":"))
    hero = card('<span class="eyebrow">Ferramenta</span><h1>Calculadora de correção pelo IPCA</h1>'
                '<p class="lede">Descubra quanto um valor de um mês passado vale hoje, corrigido pela inflação oficial (IPCA, do IBGE).</p>'
                '<div class="calc"><div class="fields">'
                '<label>Valor (R$)<input id="valor" type="text" inputmode="decimal" value="1.000,00" autocomplete="off"></label>'
                '<label>Mês inicial<select id="ini"></select></label>'
                '<label>Mês final<select id="fim"></select></label>'
                '<button class="btn" type="button" id="calcular">Calcular</button></div>'
                '<div class="result" id="res" aria-live="polite"><span class="small">Escolha os meses e clique em Calcular.</span></div></div>')
    como = card("<h2>Como o cálculo é feito</h2>"
                "<p>O valor é corrigido multiplicando as variações mensais do IPCA, de um mês depois do inicial até o mês final (inclusive). "
                "Por exemplo, para corrigir de janeiro a março, entram as variações de fevereiro e de março. É o mesmo método do índice acumulado do IBGE.</p>"
                f"<p>Os índices vão de janeiro de 2000 até {mes_nome(B.ref)}. Fonte: IBGE, via Banco Central (série 433).</p>"
                '<div class="aviso">Uma correção pelo IPCA mostra a inflação do período; contratos, aluguéis e tributos podem usar outros índices ou regras próprias. Confira o que vale no seu caso.</div>')
    script = f'<script type="application/json" id="dados-ipca">{dados}</script><script src="/assets/calc.js" defer></script>'
    return pagina(B, "/calculadora/", "Calculadora de correção pelo IPCA: quanto vale hoje o seu dinheiro",
                  f"Corrija qualquer valor pela inflação (IPCA) de janeiro de 2000 a {mes_nome(B.ref)}. Calculadora gratuita, com índices oficiais do IBGE.",
                  hero + como + script, "/calculadora/", [(None, "Calculadora")])


def pg_sobre(B: Base) -> str:
    corpo = card("<h1>Como funciona o Economia em Números</h1>"
                 '<p class="lede">Um portal independente que reúne dados abertos da economia brasileira e os organiza para consulta. Não tem ligação com o governo nem com instituições financeiras.</p>'
                 "<h2>De onde vêm os números</h2>"
                 '<ul class="plain"><li><strong>Meta da Selic, decisões e calendário do Copom:</strong> Banco Central do Brasil (série 432 do SGS e calendário oficial).</li>'
                 "<li><strong>IPCA do Brasil:</strong> IBGE, pelas séries 433 e 13522 do Banco Central.</li>"
                 "<li><strong>IPCA por região:</strong> IBGE, Sistema IBGE de Recuperação Automática (SIDRA), tabela 7060.</li>"
                 "<li><strong>Expectativas de mercado:</strong> Boletim Focus, do Banco Central.</li>"
                 "<li><strong>Atas do Copom:</strong> documentos oficiais do Banco Central; os resumos são nossos.</li>"
                 "<li><strong>Taxa de desocupação:</strong> IBGE, PNAD Contínua (SIDRA, tabelas 4099 e 6381).</li>"
                 "<li><strong>PIB:</strong> IBGE, Contas Nacionais Trimestrais (SIDRA, tabela 5932).</li>"
                 "<li><strong>IBC-Br:</strong> Banco Central (séries 24363 e 24364 do SGS).</li>"
                 "<li><strong>Produção industrial:</strong> IBGE, Pesquisa Industrial Mensal - Produção Física (SIDRA, tabela 8888).</li>"
                 "<li><strong>Vendas no varejo:</strong> IBGE, Pesquisa Mensal de Comércio (SIDRA, tabela 8880).</li>"
                 "<li><strong>Crédito e inadimplência das famílias:</strong> Banco Central, estatísticas de crédito e endividamento das famílias (séries 20716, 20740, 21084, 21112, 29034 e 29037 do SGS).</li>"
                 "<li><strong>Dólar:</strong> cotação de venda do Banco Central, série 1 do SGS (Sistema PTAX).</li>"
                 "<li><strong>Contas públicas:</strong> Banco Central, estatísticas fiscais em % do PIB (séries 13762, 4513, 5793 e 5727 do SGS).</li>"
                 "<li><strong>Vagas formais:</strong> Novo Caged, do Ministério do Trabalho e Emprego; o saldo do mês é a variação do estoque de empregos formais (série 28763 do SGS, Banco Central).</li></ul>"
                 "<h2>Dados em CSV</h2>"
                 '<p>Cada gráfico tem fonte, data da última atualização e um botão para baixar os números em CSV. A lista completa está em <a href="/dados/">Dados em CSV</a>.</p>'
                 "<h2>Atualização</h2>"
                 "<p>Um robô confere as fontes todos os dias e republica o site quando há dado novo. A data da última atualização aparece no alto de cada página.</p>"
                 "<h2>Importante</h2>"
                 '<div class="aviso">Este site mostra dados públicos e não é recomendação de investimento, de crédito ou aconselhamento financeiro. '
                 "Antes de decidir, confira sempre a fonte original.</div>"
                 '<p class="small">Também na Família em Números: <a href="https://oleoemnumeros.com.br/">Óleo em Números</a>, '
                 '<a href="https://comexemnumeros.com.br/">Comex em Números</a> e <a href="https://vooemnumeros.com.br/">Voo em Números</a>.</p>')
    return pagina(B, "/sobre/", "Como funciona o Economia em Números: fontes e atualização",
                  "De onde vêm os dados do Economia em Números (Banco Central e IBGE), como são atualizados e o que o site não é.", corpo, "/sobre/", [(None, "Como funciona")])


def pg_404(B: Base) -> str:
    return pagina(B, "/404.html", "Página não encontrada · Economia em Números", "Esta página não existe.",
                  card('<h1>Página não encontrada</h1><p>Este endereço não existe ou mudou. <a href="/">Voltar ao início</a>, ver <a href="/juros/">Juros e Copom</a> ou a <a href="/inflacao/">inflação</a>.</p>'),
                  noindex=True)


# ------------------------------------------------------------------ saída
def escrever(saida: Path, caminho: str, conteudo: str):
    destino = saida / caminho.lstrip("/")
    if caminho.endswith("/"):
        destino = destino / "index.html"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(conteudo, encoding="utf-8")


def gerar(dados_path: Path, saida: Path, calendario_path: Path = RAIZ / "data" / "copom_calendario.json", hoje: dt.date | None = None,
          resumos_path: Path = RAIZ / "data" / "copom_resumos.json") -> list:
    dados = json.loads(dados_path.read_text(encoding="utf-8"))
    cal = json.loads(calendario_path.read_text(encoding="utf-8"))
    resumos = json.loads(resumos_path.read_text(encoding="utf-8")) if resumos_path.exists() else {}
    hoje = hoje or dt.datetime.fromisoformat(dados["gerado_em"]).date()
    B = Base(dados, cal, hoje, resumos)
    if saida.exists():
        shutil.rmtree(saida)
    saida.mkdir(parents=True)
    paginas = [("/", pg_inicio(B)), ("/juros/", pg_juros(B)), ("/inflacao/", pg_inflacao(B)), ("/calculadora/", pg_calc(B)), ("/sobre/", pg_sobre(B))]
    if B.tem_emprego:
        paginas.append(("/emprego/", pg_emprego(B)))
        for u in B.uf_lista():
            paginas.append((f"/emprego/{u['slug']}/", pg_uf(B, u)))
    if B.tem_atividade:
        paginas.append(("/atividade/", pg_atividade(B)))
    if B.tem_ibge:
        paginas.append(("/industria-e-varejo/", pg_ind_var(B)))
    if B.tem_credito:
        paginas.append(("/credito/", pg_credito(B)))
    if B.tem_cambio:
        paginas.append(("/cambio/", pg_cambio(B)))
    if B.tem_fiscal:
        paginas.append(("/contas-publicas/", pg_fiscal(B)))
    for a in B.ranking():
        paginas.append((f"/inflacao/{a['slug']}/", pg_area(B, a)))
    paginas.append(("/dados/", pg_dados(B)))  # por último: lista os CSV de todos os gráficos já montados
    for caminho, conteudo in paginas:
        escrever(saida, caminho, conteudo)
    for slug, c in B.csvs.items():
        (saida / "dados").mkdir(exist_ok=True)
        (saida / "dados" / f"{slug}.csv").write_bytes(csv_texto(c["cab"], c["linhas"]).encode("utf-8"))
    escrever(saida, "/404.html", pg_404(B))
    # arquivos estáticos
    (saida / "assets").mkdir()
    v = dados["gerado_em"][:10]
    for nome in ("estilo.css", "calc.js", "graficos.js"):
        shutil.copy(SITE / nome, saida / "assets" / nome)
    shutil.copy(SITE / "favicon.svg", saida / "favicon.svg")
    (saida / "CNAME").write_text(DOMINIO + "\n", encoding="utf-8")
    (saida / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
    prio = {"/": "1.0", "/juros/": "0.9", "/emprego/": "0.9", "/atividade/": "0.9", "/cambio/": "0.9", "/contas-publicas/": "0.9", "/credito/": "0.9", "/industria-e-varejo/": "0.9", "/inflacao/": "0.9", "/calculadora/": "0.8", "/dados/": "0.5", "/sobre/": "0.3"}
    urls = "".join(f"<url><loc>{BASE}{c}</loc><lastmod>{v}</lastmod><priority>{prio.get(c, '0.6')}</priority></url>" for c, _ in paginas)
    (saida / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>\n", encoding="utf-8")
    return [c for c, _ in paginas]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dados", default=str(RAIZ / "data" / "dados.json"))
    ap.add_argument("--saida", default=str(RAIZ / "docs"))
    ap.add_argument("--calendario", default=str(RAIZ / "data" / "copom_calendario.json"))
    a = ap.parse_args()
    caminhos = gerar(Path(a.dados), Path(a.saida), Path(a.calendario))
    print(f"{len(caminhos)} páginas geradas em {a.saida}")


if __name__ == "__main__":
    main()
