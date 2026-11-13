#!/usr/bin/env python3
"""Robô de dados do Economia em Números.

Baixa as séries públicas e grava data/dados.json:
  - Meta Selic (Banco Central, SGS 432)
  - IPCA mensal (SGS 433) e acumulado em 12 meses (SGS 13522)
  - IPCA das 16 áreas pesquisadas pelo IBGE (SIDRA, tabela 7060)
  - Expectativas do Boletim Focus (Banco Central, Olinda)
  - Atas do Copom: confere no site do Banco Central se o PDF de cada ata já existe
  - Desocupação (PNAD Contínua, SIDRA 4099 por UF e 6381 trimestre móvel) e saldo de vagas formais (Novo Caged, SGS 28763)
  - Contas públicas (Banco Central): dívida bruta (SGS 13762), dívida líquida (4513), resultado primário (5793) e nominal (5727), em % do PIB

Roda no GitHub Actions (a rede do ambiente de desenvolvimento não alcança essas APIs).
Se uma fonte opcional falhar, o robô mantém o dado anterior daquela fonte e segue.
Se uma fonte essencial (Selic ou IPCA do Brasil) falhar, sai com erro e não mexe no dados.json.
"""
import datetime as dt
import json
import sys
import time
from urllib.parse import quote
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data" / "dados.json"
DEBUG = RAIZ / "data" / "debug.json"
CALENDARIO = RAIZ / "data" / "copom_calendario.json"
ATAS_URL = "https://www.bcb.gov.br/content/copom/atascopom/"
NUM_PRIMEIRA_REUNIAO = 260  # 30–31/01/2024; conferido com as atas 266 (06/11/2024), 268, 274, 276 a 281
ORCAMENTO_S = 480  # depois disso, as fontes não essenciais que faltam são puladas e o site sai com o dado anterior
UA = {"User-Agent": "EconomiaEmNumeros/1.0 (+https://economiaemnumeros.com.br)", "Cache-Control": "no-cache"}
HOJE = dt.date.today()

# código IBGE da área -> (identificador do endereço, nome, sigla da UF)
# 10 regiões metropolitanas (nível n7 do SIDRA) e 6 municípios (nível n6)
AREAS = {
    "1501": ("belem", "Belém", "PA"), "2301": ("fortaleza", "Fortaleza", "CE"), "2601": ("recife", "Recife", "PE"),
    "2901": ("salvador", "Salvador", "BA"), "3101": ("belo-horizonte", "Belo Horizonte", "MG"),
    "3201": ("grande-vitoria", "Grande Vitória", "ES"), "3301": ("rio-de-janeiro", "Rio de Janeiro", "RJ"),
    "3501": ("sao-paulo", "São Paulo", "SP"), "4101": ("curitiba", "Curitiba", "PR"), "4301": ("porto-alegre", "Porto Alegre", "RS"),
    "1200401": ("rio-branco", "Rio Branco", "AC"), "2111300": ("sao-luis", "São Luís", "MA"),
    "2800308": ("aracaju", "Aracaju", "SE"), "5002704": ("campo-grande", "Campo Grande", "MS"),
    "5208707": ("goiania", "Goiânia", "GO"), "5300108": ("brasilia", "Brasília", "DF"),
}

debug = {"inicio": dt.datetime.now().isoformat(timespec="seconds"), "avisos": [], "erros": []}


def get(url, params=None, tentativas=4, timeout=90):
    import requests  # importado aqui para os testes não dependerem dele

    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=timeout)
            if r.status_code == 200:
                return r
            ultimo = f"HTTP {r.status_code}: {r.text[:200]}"
        except requests.RequestException as e:
            ultimo = repr(e)
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"{url} falhou: {ultimo}")


def consulta(url: str, params: dict) -> str:
    """Monta a URL com espaços como %20. O Olinda (Banco Central) não entende o '+' que o requests usa em `params`."""
    return url + "?" + "&".join(f"{k}={quote(str(v), safe=chr(39))}" for k, v in params.items())


def janelas(inicio: dt.date, fim: dt.date, anos: int = 9):
    """Quebra [inicio, fim] em janelas de até `anos` anos: o SGS só aceita 10 anos por consulta em séries diárias."""
    out, a = [], inicio
    while a <= fim:
        limite = dt.date(a.year + anos, a.month, min(a.day, 28)) - dt.timedelta(days=1)
        b = min(fim, limite)
        out.append((a, b))
        a = b + dt.timedelta(days=1)
    return out


def sgs(codigo, inicio):
    """Série do SGS do Banco Central: lista de (data, valor)."""
    valores = {}
    for a, b in janelas(inicio, HOJE):
        r = get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados",
                {"formato": "json", "dataInicial": a.strftime("%d/%m/%Y"), "dataFinal": b.strftime("%d/%m/%Y")})
        for x in r.json():
            if x.get("valor") in (None, ""):
                continue
            valores[dt.datetime.strptime(x["data"], "%d/%m/%Y").date()] = float(x["valor"])
    if not valores:
        raise RuntimeError(f"SGS {codigo} veio vazia")
    return sorted(valores.items())


def selic():
    serie = sgs(432, dt.date(2016, 1, 1))
    mudancas = []
    for d, v in serie:
        if not mudancas or v != mudancas[-1][1]:
            mudancas.append([d.isoformat(), v])
    return {"meta": mudancas, "ultima_data_serie": serie[-1][0].isoformat()}


def ipca_brasil():
    mensal = sgs(433, dt.date(2000, 1, 1))
    acum12 = sgs(13522, dt.date(2000, 1, 1))
    return {"mensal": [[d.strftime("%Y-%m"), v] for d, v in mensal],
            "acum12": [[d.strftime("%Y-%m"), v] for d, v in acum12]}


def ipca_areas():
    """IPCA mensal e em 12 meses por área (SIDRA 7060, índice geral)."""
    url = "https://apisidra.ibge.gov.br/values/t/7060/n1/all/n6/all/n7/all/v/63,2265/p/last%2026/c315/7169"
    linhas = get(url).json()
    cab, dados = linhas[0], linhas[1:]
    chave_var = next(k for k, v in cab.items() if str(v).startswith("Variável") and k.endswith("C"))
    chave_mes = next(k for k, v in cab.items() if str(v).startswith("Mês") and k.endswith("C"))
    out = {}
    achados = set()
    for x in dados:
        cod = str(x.get("D1C"))
        achados.add(cod)
        if cod not in AREAS:
            continue
        v = x.get("V")
        try:
            val = float(v)
        except (TypeError, ValueError):
            continue
        mes = str(x[chave_mes])
        mes = f"{mes[:4]}-{mes[4:6]}"
        var = "mensal" if str(x[chave_var]) == "63" else "acum12"
        slug, nome, uf = AREAS[cod]
        a = out.setdefault(slug, {"nome": nome, "uf": uf, "mensal": {}, "acum12": {}})
        a[var][mes] = val
    faltam = [AREAS[c][1] for c in AREAS if AREAS[c][0] not in out]
    if faltam:
        debug["avisos"].append(f"IPCA por área: sem dados para {faltam}; códigos encontrados: {sorted(achados)[:40]}")
    if len(out) < 10:
        raise RuntimeError(f"IPCA por área: só {len(out)} áreas reconhecidas")
    for a in out.values():
        a["mensal"] = sorted([k, v] for k, v in a["mensal"].items())
        a["acum12"] = sorted([k, v] for k, v in a["acum12"].items())
    return out


FOCUS_IND = ("Selic", "IPCA", "PIB Total", "Câmbio", "Resultado primário", "Resultado nominal",
             "Dívida líquida do setor público", "Dívida bruta do governo geral")


def focus():
    """Medianas anuais do Boletim Focus (Selic, IPCA, PIB, câmbio e indicadores fiscais) e variação na semana.
    Se um indicador fiscal não existir com esse nome na API, ele só não aparece: os demais seguem."""
    url = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"
    desde = (HOJE - dt.timedelta(days=24)).isoformat()
    linhas, falhas = [], []
    for ind in FOCUS_IND:
        # Tentamos do filtro mais simples para o mais completo.
        tentativas = [
            {"$top": "600", "$format": "json", "$orderby": "Data desc", "$filter": f"Indicador eq '{ind}'"},
            {"$top": "600", "$format": "json", "$orderby": "Data desc", "$filter": f"Indicador eq '{ind}' and Data ge '{desde}'"},
        ]
        for params in tentativas:
            try:
                linhas += get(consulta(url, params), tentativas=2).json().get("value", [])
                break
            except Exception as e:  # noqa: BLE001
                falhas.append(f"{ind} {params.get('$filter')}: {str(e)[:160]}")
        else:
            falhas.append(f"{ind}: nenhuma tentativa funcionou")
    if falhas:
        debug["avisos"].append("Focus: " + " | ".join(falhas))
    linhas = [x for x in linhas if str(x.get("Data", "")) >= desde]
    base0 = [x for x in linhas if x.get("baseCalculo") in (0, "0", False)]  # base: últimos 30 dias
    linhas = base0 or linhas
    anos = {str(HOJE.year), str(HOJE.year + 1)}
    linhas = [x for x in linhas if str(x.get("DataReferencia")) in anos and x.get("Mediana") is not None]
    if not linhas:
        raise RuntimeError("Focus veio vazio")
    datas = sorted({x["Data"] for x in linhas}, reverse=True)
    ultima = datas[0]
    anterior = next((d for d in datas if (dt.date.fromisoformat(ultima) - dt.date.fromisoformat(d)).days >= 5), None)
    itens = []
    for ind in FOCUS_IND:
        for ano in sorted(anos):
            atual = next((x["Mediana"] for x in linhas if x["Indicador"] == ind and str(x["DataReferencia"]) == ano and x["Data"] == ultima), None)
            antes = next((x["Mediana"] for x in linhas if x["Indicador"] == ind and str(x["DataReferencia"]) == ano and x["Data"] == anterior), None)
            if atual is not None:
                itens.append({"indicador": ind, "ano": int(ano), "mediana": atual, "semana_anterior": antes})
    return {"data": ultima, "itens": itens}


def arquivo_pdf_existe(url):
    """True se o PDF existe, False se não, None se não deu para verificar (rede, bloqueio)."""
    import requests

    achou_erro = False
    for metodo in ("head", "get"):
        try:
            r = requests.request(metodo, url, headers=UA, timeout=30, allow_redirects=True, stream=(metodo == "get"))
            status, tipo = r.status_code, r.headers.get("content-type", "").lower()
            r.close()
        except requests.RequestException:
            achou_erro = True
            continue
        if status == 200 and "pdf" in tipo:
            return True
        if status in (404, 410) or (status == 200 and "pdf" not in tipo):
            return False
        achou_erro = True  # 403/405/5xx: tenta o outro método
    return None if achou_erro else False


def ata_depois(fim: dt.date) -> dt.date:
    return fim + dt.timedelta(days=(1 - fim.weekday()) % 7 or 7)  # primeira terça-feira depois da reunião


def atas():
    """Links dos PDFs das atas do Copom já publicadas (o endereço segue um padrão; só guardamos os que existem)."""
    cal = json.loads(CALENDARIO.read_text(encoding="utf-8"))["reunioes"]
    antigo = (json.loads(DADOS.read_text(encoding="utf-8")) if DADOS.exists() else {}).get("atas") or {}
    out = {}
    for idx, (_, fim) in enumerate(cal):
        f = dt.date.fromisoformat(fim)
        if ata_depois(f) > HOJE:
            continue
        n = NUM_PRIMEIRA_REUNIAO + idx
        if (antigo.get(str(n)) or {}).get("pdf"):
            out[str(n)] = antigo[str(n)]
            continue
        url = f"{ATAS_URL}Copom{n}-not{f:%Y%m%d}{n}.pdf"
        ok = arquivo_pdf_existe(url)
        if ok:
            out[str(n)] = {"pdf": url}
        else:
            debug["avisos"].append(f"Ata {n}: {'PDF não encontrado' if ok is False else 'não deu para verificar'} em {url}")
    return out


def sidra_linhas(url):
    linhas = get(url).json()
    cab, dados = linhas[0], linhas[1:]
    chave_per = next(k for k, v in cab.items() if k.startswith("D") and k.endswith("C") and str(v).lower().startswith(("trimestre", "mês")))
    chave_ter = next((k for k, v in cab.items() if k.startswith("D") and k.endswith("C") and any(t in str(v) for t in ("Brasil", "Unidade da Federa", "Territ"))), "D1C")
    chave_nome = chave_ter[:-1] + "N"
    return cab, dados, chave_per, chave_ter, chave_nome


def desocupacao():
    """Taxa de desocupação (PNAD Contínua, IBGE): trimestral por UF (tabela 4099) e trimestre móvel do Brasil (tabela 6381)."""
    cab, dados, k_per, k_ter, k_nome = sidra_linhas("https://apisidra.ibge.gov.br/values/t/4099/n1/all/n3/all/v/4099/p/last%2013")
    tri = {}
    for x in dados:
        try:
            v = float(x.get("V"))
        except (TypeError, ValueError):
            continue
        cod = str(x[k_ter])
        t = tri.setdefault(cod, {"nome": x.get(k_nome, cod), "serie": {}})
        t["serie"][str(x[k_per])] = [str(x[k_per]), str(x.get(k_per[:-1] + "N", "")), v]
    for t in tri.values():
        t["serie"] = [t["serie"][c] for c in sorted(t["serie"])]
    if "1" not in tri or len(tri) < 20:
        raise RuntimeError(f"Desocupação por UF: só {len(tri)} territórios; códigos: {sorted(tri)[:30]}; cabeçalho: {cab}")
    cab2, dados2, k_per2, k_ter2, _ = sidra_linhas("https://apisidra.ibge.gov.br/values/t/6381/n1/all/v/4099/p/last%2036")
    movel = {}
    for x in dados2:
        try:
            movel[str(x[k_per2])] = [str(x[k_per2]), str(x.get(k_per2[:-1] + "N", "")), float(x.get("V"))]
        except (TypeError, ValueError):
            continue
    if len(movel) < 12:
        raise RuntimeError(f"Desocupação (trimestre móvel): só {len(movel)} períodos; cabeçalho: {cab2}")
    debug["avisos"].append(f"Desocupação: último trimestre {tri['1']['serie'][-1]}; último trimestre móvel {movel[max(movel)]}")
    return {"trimestral": tri, "movel": [movel[c] for c in sorted(movel)]}


def caged():
    """Saldo mensal de vagas formais (Novo Caged). A série 28763 do SGS é o ESTOQUE de empregos formais (~48 milhões);
    o saldo do mês é a variação do estoque (conferido: set/2026 = 48.359.577 − 48.238.272 = +121.305)."""
    serie = sgs(28763, dt.date(2019, 12, 1))
    debug["avisos"].append(f"Caged SGS 28763 (estoque): últimas leituras {[(d.isoformat(), v) for d, v in serie[-3:]]}")
    if len(serie) < 14:
        raise RuntimeError("SGS 28763 com poucos meses")
    if min(v for _, v in serie) < 10_000_000:
        raise RuntimeError("SGS 28763 não parece um estoque de empregos (esperado: dezenas de milhões); conferir a série")
    saldo = [[d.strftime("%Y-%m"), round(v - antes)] for (_, antes), (d, v) in zip(serie, serie[1:])]
    if any(abs(v) > 1_500_000 for _, v in saldo):
        raise RuntimeError("Variação mensal do estoque fora do esperado (>1,5 milhão); conferir a série 28763")
    debug["avisos"].append(f"Caged: saldo calculado, últimos meses {saldo[-3:]}")
    return {"saldo": [x for x in saldo if x[0] >= "2020-01"]}


def cambio():
    """Dólar americano (venda), série diária 1 do SGS (Sistema PTAX, Banco Central)."""
    serie = sgs(1, dt.date(2016, 1, 1))
    debug["avisos"].append(f"Câmbio SGS 1: últimas leituras {[(d.isoformat(), v) for d, v in serie[-3:]]}")
    if len(serie) < 500:
        raise RuntimeError(f"SGS 1 com poucos dias ({len(serie)})")
    if not all(1.0 < v < 15.0 for _, v in serie):
        raise RuntimeError("SGS 1 com cotação fora da faixa esperada (R$ 1 a R$ 15 por dólar); conferir a série")
    por_mes = {}
    for d, v in serie:
        por_mes.setdefault(d.strftime("%Y-%m"), []).append(v)
    mensal = [[m, round(sum(vs) / len(vs), 4), vs[-1]] for m, vs in sorted(por_mes.items())]
    corte = serie[-1][0] - dt.timedelta(days=400)
    return {"diario": [[d.isoformat(), v] for d, v in serie if d >= corte], "mensal": mensal}


def ibcbr():
    """IBC-Br (Banco Central): série com ajuste sazonal (24364) e sem ajuste (24363)."""
    out = {}
    for chave, cod in (("sa", 24364), ("nsa", 24363)):
        serie = sgs(cod, dt.date(2022, 1, 1))
        if len(serie) < 30 or not all(50 < v < 400 for _, v in serie):
            raise RuntimeError(f"SGS {cod} fora do esperado (índice entre 50 e 400, pelo menos 30 meses); conferir a série")
        out[chave] = [[d.strftime("%Y-%m"), v] for d, v in serie]
    debug["avisos"].append(f"IBC-Br: últimas leituras com ajuste {out['sa'][-3:]}; sem ajuste {out['nsa'][-2:]}")
    return out


def pib():
    """PIB trimestral (IBGE, Contas Nacionais, tabela 5932): contra igual trimestre do ano anterior (6561),
    acumulado em quatro trimestres (6563) e contra o trimestre anterior com ajuste sazonal (6564)."""
    linhas = get("https://apisidra.ibge.gov.br/values/t/5932/n1/all/v/6561,6563,6564/p/last%2016/c11255/90707").json()
    cab, dados = linhas[0], linhas[1:]
    k_var = next((k for k, v in cab.items() if k.startswith("D") and k.endswith("C") and str(v).lower().startswith("variável")), None)
    k_per = next((k for k, v in cab.items() if k.startswith("D") and k.endswith("C") and str(v).lower().startswith("trimestre")), None)
    if not k_var or not k_per:
        raise RuntimeError(f"PIB: colunas de variável/trimestre não encontradas; cabeçalho: {cab}")
    por = {}
    for x in dados:
        try:
            v = float(x.get("V"))
        except (TypeError, ValueError):
            continue
        por.setdefault(str(x[k_per]), {})[str(x[k_var])] = v
    vistas = {c for d in por.values() for c in d}
    if not {"6561", "6564"} <= vistas:
        raise RuntimeError(f"PIB: variáveis esperadas 6561/6563/6564, vieram {sorted(vistas)}; cabeçalho: {cab}")
    saida = [{"t": t, "yoy": d.get("6561"), "a4": d.get("6563"), "qoq": d.get("6564")} for t, d in sorted(por.items())]
    if len(saida) < 8 or any(abs(v) > 25 for r in saida for k, v in r.items() if k != "t" and v is not None):
        raise RuntimeError(f"PIB fora do esperado: {len(saida)} trimestres; últimos: {saida[-2:]}")
    debug["avisos"].append(f"PIB: últimos trimestres {saida[-2:]}")
    return {"trimestral": saida}


FISCAL = (  # chave, código SGS, faixa plausível (% do PIB), descrição
    ("dbgg", 13762, (30, 150), "dívida bruta do governo geral, % do PIB"),
    ("dlsp", 4513, (10, 120), "dívida líquida do setor público, % do PIB"),
    ("primario", 5793, (-15, 15), "NFSP, resultado primário, fluxo em 12 meses, % do PIB"),
    ("nominal", 5727, (-25, 25), "NFSP, resultado nominal, fluxo em 12 meses, % do PIB"),
)


def fiscal():
    """Contas públicas (Banco Central, setor público consolidado e governo geral), séries mensais em % do PIB.
    Os dados de NFSP vêm como 'necessidade de financiamento': o gerador do site decide o sinal exibido
    (ver NFSP_POSITIVO_E_DEFICIT em gerar_site.py), conferindo as últimas leituras registradas no debug."""
    out = {}
    for chave, cod, (lo, hi), desc in FISCAL:
        serie = sgs(cod, dt.date(2015, 1, 1))
        if len(serie) < 36 or not all(lo <= v <= hi for _, v in serie):
            raise RuntimeError(f"SGS {cod} ({desc}) fora do esperado ({len(serie)} meses, faixa {lo} a {hi}); últimas leituras: {[(d.isoformat(), v) for d, v in serie[-3:]]}")
        out[chave] = [[d.strftime("%Y-%m"), v] for d, v in serie]
        debug["avisos"].append(f"Fiscal {chave} (SGS {cod}, {desc}): últimas leituras {out[chave][-3:]}")
    return out


CREDITO = (  # chave, código SGS, faixa plausível, descrição
    ("inad_pf", 21084, (0, 20), "inadimplência (atraso acima de 90 dias) da carteira das pessoas físicas, % da carteira"),
    ("inad_livre_pf", 21112, (0, 30), "inadimplência do crédito livre às pessoas físicas, % da carteira"),
    ("juros_pf", 20716, (10, 100), "taxa média de juros do crédito às pessoas físicas, % ao ano"),
    ("juros_livre_pf", 20740, (20, 150), "taxa média de juros do crédito livre às pessoas físicas, % ao ano"),
    ("endividamento", 29037, (20, 90), "endividamento das famílias com o sistema financeiro, % da renda de 12 meses (com ajuste sazonal)"),
    ("comprometimento", 29034, (10, 50), "comprometimento da renda das famílias com o serviço da dívida, % da renda mensal (com ajuste sazonal)"),
)


def credito():
    """Crédito às famílias (Banco Central): juros, inadimplência, endividamento e comprometimento de renda, séries mensais do SGS.
    As relações abaixo (crédito livre > total; dívida > serviço da dívida) pegam código trocado, que a faixa de valores sozinha não pega."""
    out = {}
    for chave, cod, (lo, hi), desc in CREDITO:
        serie = sgs(cod, dt.date(2016, 1, 1))
        if len(serie) < 36 or not all(lo <= v <= hi for _, v in serie):
            raise RuntimeError(f"SGS {cod} ({desc}) fora do esperado ({len(serie)} meses, faixa {lo} a {hi}); últimas leituras: {[(d.isoformat(), v) for d, v in serie[-3:]]}")
        out[chave] = [[d.strftime("%Y-%m"), v] for d, v in serie]
        debug["avisos"].append(f"Crédito {chave} (SGS {cod}, {desc}): últimas leituras {out[chave][-3:]}")
    for maior, menor in (("inad_livre_pf", "inad_pf"), ("juros_livre_pf", "juros_pf"), ("endividamento", "comprometimento")):
        if out[maior][-1][1] <= out[menor][-1][1]:
            raise RuntimeError(f"Crédito: {maior} ({out[maior][-1]}) deveria ser maior que {menor} ({out[menor][-1]}); conferir os códigos do SGS")
    return out


def _limpo(nome):
    """Nome de categoria do SIDRA sem número na frente ('1 Indústria geral' -> 'indústria geral')."""
    return str(nome).lower().strip().lstrip("0123456789. ").strip()


def sidra_tabela(tabela, ultimos, classes):
    """Tabela mensal do SIDRA (IBGE) para o Brasil, com todas as variáveis, nos últimos `ultimos` meses; `classes` = '/c544/all' etc.
    (a consulta sem classificação devolve só '..'). Devolve linhas {dims: nomes da variável e das categorias, unid, per: 'AAAAMM', v},
    sem as células sem número. O servidor de metadados do IBGE (servicodados) não responde a partir do GitHub Actions, por isso os ids são fixos."""
    url = f"https://apisidra.ibge.gov.br/values/t/{tabela}/n1/all/v/all/p/last%20{ultimos}{classes}"
    linhas = get(url, tentativas=3, timeout=60).json()
    cab, dados = linhas[0], linhas[1:]
    chaves = [k for k in cab if k.startswith("D") and k.endswith("C")]
    k_per = next((k for k in chaves if str(cab[k]).lower().startswith("mês")), None)
    k_ter = next((k for k in chaves if any(t in str(cab[k]) for t in ("Brasil", "Territ"))), None)
    if not k_per or not k_ter:
        raise RuntimeError(f"SIDRA {tabela}: colunas de mês/território não encontradas; cabeçalho: {cab}")
    out = []
    for x in dados:
        try:
            v = float(x.get("V"))
        except (TypeError, ValueError):
            continue
        out.append({"dims": [str(x.get(k[:-1] + "N", x.get(k, ""))) for k in chaves if k not in (k_per, k_ter)],
                    "unid": str(x.get("MN", "")), "per": str(x[k_per]), "v": v})
    debug["avisos"].append(f"SIDRA {tabela}: {len(dados)} linhas, {len(out)} com número, em {url}; amostra {dados[:1]}")
    if not out:
        raise RuntimeError(f"SIDRA {tabela}: nenhuma linha numérica ({len(dados)} linhas); amostra {dados[:3]}; cabeçalho: {cab}")
    return out


def medida_ibge(texto, unid):
    """Reconhece o tipo de número de uma linha do SIDRA pelos nomes das dimensões e pela unidade:
    sa/idx = número-índice com/sem ajuste sazonal; mm = variação sobre o mês anterior (com ajuste); yoy = contra o mesmo mês do ano anterior;
    a12 = acumulada em 12 meses. Receita nominal e acumulado no ano não interessam (None)."""
    t = texto.lower()
    if "receita" in t:
        return None
    if "%" in unid or "variação" in t:
        if "12 meses" in t:
            return "a12"
        if "ano anterior" in t or "mesmo mês" in t or "igual" in t:
            return "yoy"
        if "no ano" in t:
            return None
        if "sazonal" in t:
            return "mm"
        return None
    if "índice" in t or "indice" in t:
        return "sa" if "sazonal" in t else "idx"
    return None


def _desloca(per, n):
    """Soma n meses a um período 'AAAAMM'."""
    m = int(per[:4]) * 12 + int(per[4:6]) - 1 + n
    return f"{m // 12:04d}{m % 12 + 1:02d}"


def _completa(med):
    """Variações que o IBGE não devolveu são calculadas dos números-índice (e registradas no debug)."""
    derivadas = []
    sa, idx = med.get("sa", {}), med.get("idx", {})
    if "mm" not in med and sa:
        med["mm"] = {p: round((v / sa[_desloca(p, -1)] - 1) * 100, 1) for p, v in sa.items() if _desloca(p, -1) in sa}
        derivadas.append("mm")
    if "yoy" not in med and idx:
        med["yoy"] = {p: round((v / idx[_desloca(p, -12)] - 1) * 100, 1) for p, v in idx.items() if _desloca(p, -12) in idx}
        derivadas.append("yoy")
    if "a12" not in med and idx:
        med["a12"] = {}
        for p in idx:
            atual = [_desloca(p, -k) for k in range(12)]
            antes = [_desloca(p, -k) for k in range(12, 24)]
            if all(q in idx for q in atual + antes):
                med["a12"][p] = round((sum(idx[q] for q in atual) / sum(idx[q] for q in antes) - 1) * 100, 1)
        derivadas.append("a12")
    return derivadas


def indicador_ibge(tabela, ultimos, classes, filtro, nome):
    """Série mensal do IBGE. `filtro(dims)` escolhe as linhas da atividade/tipo de índice que interessa.
    Devolve {sa, idx, mm, yoy, a12: [[AAAA-MM, valor], ...]}."""
    med, soltas, vistas = {}, set(), set()
    for ln in sidra_tabela(tabela, ultimos, classes):
        texto = " | ".join(ln["dims"])
        vistas.add(texto)
        if not filtro(ln["dims"]):
            continue
        m = medida_ibge(texto, ln["unid"])
        if m is None:
            soltas.add(f"{texto} [{ln['unid']}]")
            continue
        med.setdefault(m, {})[ln["per"]] = ln["v"]
    if soltas:
        debug["avisos"].append(f"{nome}: linhas ignoradas {sorted(soltas)[:12]}")
    if "sa" not in med:
        raise RuntimeError(f"{nome}: sem número-índice com ajuste sazonal (medidas achadas: {sorted(med)}; textos vistos: {sorted(vistas)[:10]})")
    derivadas = _completa(med)
    sa = med["sa"]
    if len(sa) < 30 or not all(50 < v < 160 for v in sa.values()):
        raise RuntimeError(f"{nome}: índice com ajuste sazonal fora do esperado ({len(sa)} meses; últimos {sorted(sa.items())[-3:]})")
    if any(abs(v) > 15 for v in med["mm"].values()) or any(abs(v) > 40 for v in med["yoy"].values()):
        raise RuntimeError(f"{nome}: variação fora do esperado (mm {sorted(med['mm'].items())[-3:]}, yoy {sorted(med['yoy'].items())[-3:]})")
    saida = {m: [[f"{p[:4]}-{p[4:6]}", v] for p, v in sorted(d.items())] for m, d in med.items() if m in ("sa", "idx", "mm", "yoy", "a12")}
    debug["avisos"].append(f"{nome}: último mês {saida['sa'][-1][0]}; sa {saida['sa'][-1][1]}, mm {saida['mm'][-1]}, yoy {saida['yoy'][-1]}, "
                           f"a12 {(saida.get('a12') or [None])[-1]}; calculadas aqui: {derivadas or 'nenhuma'}")
    return saida


def producao_industrial():
    """Produção industrial (IBGE, PIM-PF, tabela 8888, base 2022=100): indústria geral (categoria 129314 da classificação 544)."""
    return indicador_ibge(8888, 62, "/c544/all", lambda dims: any(_limpo(d) == "indústria geral" for d in dims), "Indústria")


def varejo():
    """Volume de vendas do comércio varejista (IBGE, PMC, base 2022=100): restrito (tabela 8880) e ampliado (8881).
    Em cada tabela, a classificação 11046 separa 'receita nominal' de 'volume de vendas'; só o volume interessa."""
    volume = lambda dims: any("volume" in d.lower() for d in dims)
    out = {"restrito": indicador_ibge(8880, 62, "/c11046/all", volume, "Varejo")}
    try:
        out["ampliado"] = indicador_ibge(8881, 62, "/c11046/all", volume, "Varejo ampliado")
    except Exception as e:  # noqa: BLE001 - o ampliado é um complemento: sem ele, o restrito segue
        debug["avisos"].append(f"Varejo ampliado indisponível: {e}")
    return out


def main():
    antigo = json.loads(DADOS.read_text(encoding="utf-8")) if DADOS.exists() else {}
    novo = dict(antigo)
    essenciais_ok = True
    t0 = time.time()
    for nome, fn, essencial in [("selic", selic, True), ("ipca", ipca_brasil, True), ("areas", ipca_areas, False), ("focus", focus, False),
                             ("atas", atas, False), ("desocupacao", desocupacao, False), ("caged", caged, False),
                             ("cambio", cambio, False), ("ibc", ibcbr, False), ("pib", pib, False), ("fiscal", fiscal, False),
                             ("credito", credito, False), ("industria", producao_industrial, False), ("varejo", varejo, False)]:
        if not essencial and time.time() - t0 > ORCAMENTO_S:
            debug["erros"].append(f"{nome}: pulada, o robô já passou de {ORCAMENTO_S // 60} minutos (mantém o dado anterior)")
            print(f"PULADA {nome}: orçamento de tempo esgotado", file=sys.stderr, flush=True)
            continue
        t1 = time.time()
        try:
            novo[nome] = fn()
            print(f"ok: {nome} ({time.time() - t1:.0f}s)", flush=True)
        except Exception as e:  # noqa: BLE001 - queremos registrar qualquer falha e seguir
            debug["erros"].append(f"{nome}: {e}")
            print(f"FALHA em {nome} ({time.time() - t1:.0f}s): {e}", file=sys.stderr, flush=True)
            if essencial and nome not in antigo:
                essenciais_ok = False
        debug.setdefault("tempos", {})[nome] = round(time.time() - t1, 1)
        DEBUG.write_text(json.dumps(debug, ensure_ascii=False, indent=1), encoding="utf-8")  # já grava aqui: se algo travar, o diagnóstico fica
    DEBUG.write_text(json.dumps(debug, ensure_ascii=False, indent=1), encoding="utf-8")
    if not essenciais_ok:
        print("Fonte essencial indisponível e sem dado anterior: nada foi gravado.", file=sys.stderr)
        sys.exit(1)
    novo["gerado_em"] = dt.datetime.now().isoformat(timespec="seconds")
    DADOS.write_text(json.dumps(novo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if debug["erros"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
