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

    # Atas, emprego ----------------------------------------------------------
    def ata_pdf(self, n: int):
        return (self.resumos.get(str(n)) or {}).get("pdf") or (self.atas.get(str(n)) or {}).get("pdf")

    @property
    def tem_emprego(self) -> bool:
        return bool(self.des and "1" in (self.des.get("trimestral") or {}) and self.des.get("movel"))

    def nav(self) -> list:
        itens = list(NAV)
        if self.tem_emprego:
            itens.insert(1, ("/emprego/", "Emprego"))
        return itens

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


def hbarras(linhas) -> str:
    """linhas: (rótulo html, valor, valor formatado, meta html)"""
    mx = max((abs(v) for _, v, _, _ in linhas), default=1) or 1
    out = []
    for rot, v, fmt, meta in linhas:
        w = max(2, int(abs(v) / mx * 100))
        m = f'<span class="meta">{meta}</span>' if meta else ""
        out.append(f'<div class="hbar"><span class="t">{rot}</span><span class="v">{fmt}</span>'
                   f'<span class="track"><span style="width:{w}%;background:var(--eco)"></span></span>{m}</div>')
    return f'<div class="hbars">{"".join(out)}</div>'


def lista_links(itens) -> str:
    return '<ul class="list">' + "".join(f'<li><a href="{h}"><span>{t}</span><span>{d}</span></a></li>' for h, t, d in itens) + "</ul>"


# ------------------------------------------------------------------ gráficos SVG (estáticos)
W, H, PL, PR, PT, PB = 640, 240, 52, 16, 14, 34


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


def _grade(lo, hi, marcas, d) -> str:
    y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
    g = ""
    for t in marcas:
        g += (f'<line x1="{PL}" x2="{W - PR}" y1="{y(t):.1f}" y2="{y(t):.1f}" style="stroke:var(--line)"/>'
              f'<text x="{PL - 6}" y="{y(t) + 4:.1f}" text-anchor="end">{nf(t, d)}</text>')
    return g


def _rotulos_x(rotulos, x) -> str:
    n = len(rotulos)
    passo = math.ceil(n / 5)
    pos = [k for k in range(0, n, passo) if (n - 1 - k) >= passo * 0.7] + [n - 1]
    g = ""
    for k in pos:
        ancora = "start" if k == 0 else "end" if k == n - 1 else "middle"
        g += f'<text x="{x(k):.1f}" y="{H - 8}" text-anchor="{ancora}">{rotulos[k]}</text>'
    return g


def svg_linhas(series, rotulos, aria) -> str:
    """series: lista de dicts {vals, cor ('a'|'b'|'m'), tracejada}; todas com o mesmo tamanho que rotulos."""
    lo, hi, marcas, d = _eixo([v for s in series for v in s["vals"]])
    n = len(rotulos)
    x = lambda i: PL + (W - PL - PR) * (i / (n - 1) if n > 1 else 0.5)
    y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
    g = _grade(lo, hi, marcas, d) + _rotulos_x(rotulos, x)
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


def svg_degraus(pontos, ate: dt.date, aria) -> str:
    """Gráfico em degraus no tempo. pontos: [(data, valor)] ordenados, o valor vale até o próximo ponto."""
    lo, hi, marcas, d = _eixo([v for _, v in pontos], zero=True)
    t0, t1 = pontos[0][0].toordinal(), ate.toordinal()
    x = lambda dia: PL + (W - PL - PR) * (dia.toordinal() - t0) / max(1, t1 - t0)
    y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
    g = _grade(lo, hi, marcas, d)
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


def svg_barras(vals, rotulos, aria) -> str:
    lo, hi, marcas, d = _eixo(vals, zero=True, margem=0.08)
    y = lambda v: PT + (H - PT - PB) * (1 - (v - lo) / (hi - lo))
    n = len(vals)
    bw = (W - PL - PR) / n
    x = lambda k: PL + bw * k + bw / 2
    g = _grade(lo, hi, marcas, d) + _rotulos_x(rotulos, x)
    for k, v in enumerate(vals):
        y0, y1 = y(max(v, 0)), y(min(v, 0))
        cor = "var(--eco2)" if v < 0 else "var(--eco)"
        g += f'<rect x="{PL + bw * k + bw * 0.15:.1f}" y="{y0:.1f}" width="{bw * 0.7:.1f}" height="{max(1.0, y1 - y0):.1f}" rx="2" style="fill:{cor}"/>'
    return f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{esc(aria)}">{g}</svg>'


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
    emprego_link = '<a href="/emprego/">Emprego</a> · ' if B.tem_emprego else ""
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
<span><a href="/juros/">Juros e Copom</a> · {emprego_link}<a href="/inflacao/">Inflação</a> · <a href="/calculadora/">Calculadora</a> · <a href="/sobre/">Como funciona</a></span>
</div>{familia_html()}</footer>
{GOAT}
</body>
</html>
"""


# ------------------------------------------------------------------ páginas
def blocos_focus(B: Base) -> str:
    f = B.focus
    if not f or not f.get("itens"):
        return ""
    por = {}
    for it in f["itens"]:
        por.setdefault(it["indicador"], {})[it["ano"]] = it
    anos = sorted({it["ano"] for it in f["itens"]})
    nomes = {"Selic": ("Selic ao fim do ano", lambda v: pct(v, 2)), "IPCA": ("IPCA (inflação)", lambda v: pct(v, 2)),
             "PIB Total": ("PIB (crescimento)", lambda v: pct(v, 2)), "Câmbio": ("Câmbio (R$ por US$)", lambda v: nf(v, 2))}
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
    return card(cab("Expectativas do mercado (Boletim Focus)") +
                tabela(["Indicador"] + [str(a) for a in anos] + ["Semana"], linhas, ["l"] + ["r"] * (len(anos) + 1)) +
                f'<span class="src">Mediana das projeções do mercado, Boletim Focus (posição de {dia}). \"Semana\" é a variação da projeção para {anos[0]} desde o boletim anterior. Fonte: Banco Central do Brasil.</span>')


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
    selic = card(cab("Meta da Selic desde 2019", '<span class="src">Fonte: Banco Central</span>') +
                 '<div class="chart">' + svg_degraus([(d, v) for d, v in B.mud if d >= dt.date(2019, 1, 1)] or B.mud, B.hoje,
                                                    "Gráfico em degraus da meta da taxa Selic desde 2019") + "</div>"
                 '<p class="small">Meta da taxa Selic definida pelo Copom, em % ao ano. Cada degrau é uma decisão do comitê.</p>')
    rk = B.ranking()
    infl = card(cab("Inflação por região", '<a class="small" href="/inflacao/">ver as 16 áreas →</a>') +
                hbarras([(f'<a href="/inflacao/{a["slug"]}/">{esc(a["nome"])}</a>', a["acum12"][B.ref_areas], pct(a["acum12"][B.ref_areas], 2), "") for a in rk[:8]]) +
                f'<span class="src">IPCA acumulado em 12 meses até {mes_nome(B.ref_areas)}. As 8 maiores de 16 áreas. Fonte: IBGE.</span>') if rk else ""
    focus = blocos_focus(B)
    linha2 = f'<div class="cols">{infl}{focus}</div>' if infl and focus else (infl or focus)
    calc = card('<span class="eyebrow">Ferramenta</span><h2>Calculadora de correção pelo IPCA</h2>'
                '<p class="small">Quanto R$ 1.000 de alguns anos atrás valem hoje? Corrija qualquer valor pela inflação oficial, mês a mês, desde 2000.</p>'
                '<p><a href="/calculadora/">Abrir a calculadora →</a></p>')
    corpo = f'{hero}<div class="tiles">{"".join(tiles)}</div><div class="two">{selic}{card_copom(B)}</div>{linha2}{card_emprego_inicio(B)}{calc}'
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
    graf = card(cab("Meta da Selic desde 2016", '<span class="src">Fonte: Banco Central</span>') + '<div class="chart">' +
                svg_degraus(B.mud, B.hoje, "Gráfico em degraus da meta da taxa Selic desde 2016") + "</div>")
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
        linhas.append([f'{periodo_reuniao(u["ini"], u["fim"])} de {u["fim"].year}', sel, pct(u["depois"], 2), " · ".join(links) or "–"])
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
    g1 = card(cab("Taxa de desocupação", '<span class="src">Fonte: IBGE (PNAD Contínua)</span>') + '<div class="chart">' +
              svg_linhas([{"vals": [x[2] for x in ult36], "cor": "a"}], [mes_curtinho(f"{x[0][:4]}-{x[0][4:]}") for x in ult36],
                         "Gráfico da taxa de desocupação no Brasil, em trimestres móveis, nos últimos 36 meses") + "</div>"
              '<p class="small">Pessoas de 14 anos ou mais sem trabalho que procuraram emprego, em % da força de trabalho. Cada ponto é um trimestre móvel, identificado pelo mês final.</p>')
    g2 = ""
    if cg:
        c24 = cg[-24:]
        g2 = card(cab("Saldo mensal de vagas formais", '<span class="src">Fonte: Novo Caged (MTE), via Banco Central</span>') + '<div class="chart">' +
                  svg_barras([v / 1000 for _, v in c24], [mes_curtinho(m) for m, _ in c24], "Gráfico de barras do saldo mensal de vagas formais do Novo Caged nos últimos 24 meses, em milhares") + "</div>"
                  '<p class="small">Em milhares de vagas. Admissões menos desligamentos de empregos com carteira assinada. Dezembro costuma ter saldo negativo.</p>')
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
    graf = card(cab(f"Taxa de desocupação: {esc(u['nome'])} e Brasil", '<span class="src">Fonte: IBGE (PNAD Contínua)</span>') +
                '<div class="chart">' + svg_linhas(series, [rot_tri(c) for c in comuns], f"Gráfico da taxa de desocupação em {u['nome']} e no Brasil") + "</div>"
                f'<div class="leg"><span><i style="background:var(--eco2)"></i>{esc(u["nome"])}</span><span><i style="background:var(--muted)"></i>Brasil</span></div>')
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
    g12 = card(cab("IPCA acumulado em 12 meses", '<span class="src">Fonte: IBGE</span>') + '<div class="chart">' +
               svg_linhas([{"vals": [B.ipca_12[m] for m in ms36], "cor": "b"}], [mes_curtinho(m) for m in ms36],
                          "Gráfico do IPCA acumulado em 12 meses nos últimos 36 meses") + "</div>")
    gm = card(cab("IPCA mensal", '<span class="src">Fonte: IBGE</span>') + '<div class="chart">' +
              svg_barras([B.ipca_m[m] for m in ms24 if m in B.ipca_m], [mes_curtinho(m) for m in ms24 if m in B.ipca_m],
                         "Gráfico de barras do IPCA mensal nos últimos 24 meses") + "</div>")
    rk = B.ranking()
    reg = ""
    if rk:
        linhas = [(f'<a href="/inflacao/{a["slug"]}/">{esc(a["nome"])} ({a["uf"]})</a>', a["acum12"][B.ref_areas], pct(a["acum12"][B.ref_areas], 2),
                   f'no mês: {pct(a["mensal"][B.ref_areas], 2)}' if B.ref_areas in a["mensal"] else "") for a in rk]
        reg = card(cab("Por região", f'<span class="src">12 meses até {mes_nome(B.ref_areas)}</span>') + hbarras(linhas) +
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
    graf = card(cab(f"IPCA em 12 meses: {esc(a['nome'])} e Brasil", '<span class="src">Fonte: IBGE</span>') +
                '<div class="chart">' + svg_linhas(series, [mes_curtinho(m) for m in comuns], f"Gráfico do IPCA acumulado em 12 meses em {a['nome']} e no Brasil") + "</div>"
                f'<div class="leg"><span><i style="background:var(--eco2)"></i>{esc(a["nome"])}</span><span><i style="background:var(--muted)"></i>Brasil</span></div>')
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
                 "<li><strong>Vagas formais:</strong> Novo Caged, do Ministério do Trabalho e Emprego, pela série 28763 do SGS do Banco Central.</li></ul>"
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
    for a in B.ranking():
        paginas.append((f"/inflacao/{a['slug']}/", pg_area(B, a)))
    for caminho, conteudo in paginas:
        escrever(saida, caminho, conteudo)
    escrever(saida, "/404.html", pg_404(B))
    # arquivos estáticos
    (saida / "assets").mkdir()
    v = dados["gerado_em"][:10]
    for nome in ("estilo.css", "calc.js"):
        shutil.copy(SITE / nome, saida / "assets" / nome)
    shutil.copy(SITE / "favicon.svg", saida / "favicon.svg")
    (saida / "CNAME").write_text(DOMINIO + "\n", encoding="utf-8")
    (saida / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}/sitemap.xml\n", encoding="utf-8")
    prio = {"/": "1.0", "/juros/": "0.9", "/emprego/": "0.9", "/inflacao/": "0.9", "/calculadora/": "0.8", "/sobre/": "0.3"}
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
