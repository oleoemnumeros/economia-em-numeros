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
  - Setor externo: conta corrente (SGS 22701, 24419, 23079), investimento direto no país (22885), reservas internacionais (13982) e balança comercial (Secex/MDIC, pelo Comex em Números)
  - Bolsa Família por município (MDS, API MI Social + população do IBGE), gravado à parte em data/bolsa_familia.json

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


EXTERNO = (  # chave, código SGS, faixa plausível, descrição
    ("ca_mensal", 22701, (-40000, 25000), "saldo mensal da conta corrente, US$ milhões"),
    ("ca_12m", 24419, (-150000, 100000), "saldo da conta corrente acumulado em 12 meses, US$ milhões"),
    ("ca_pib", 23079, (-8, 4), "saldo da conta corrente acumulado em 12 meses, % do PIB"),
    ("idp_mensal", 22885, (-20000, 40000), "investimento direto no país (IDP), fluxo líquido mensal, US$ milhões"),
)
RESERVAS_SGS = 13982  # reservas internacionais, conceito liquidez, diária, US$ milhões
BALANCA_URL = "https://raw.githubusercontent.com/oleoemnumeros/comex-em-numeros/main/data/dados.json"


def setor_externo():
    """Setor externo (Banco Central): conta corrente (mensal, 12 meses e % do PIB), investimento direto no país e reservas internacionais.
    A soma de 12 meses da série mensal tem de bater com a série acumulada, e o sinal do % do PIB com o do saldo: pega código trocado."""
    out = {}
    for chave, cod, (lo, hi), desc in EXTERNO:
        serie = sgs(cod, dt.date(2015, 1, 1))
        if len(serie) < 60 or not all(lo <= v <= hi for _, v in serie):
            raise RuntimeError(f"SGS {cod} ({desc}) fora do esperado ({len(serie)} meses, faixa {lo} a {hi}); últimas leituras: {[(d.isoformat(), v) for d, v in serie[-3:]]}")
        out[chave] = [[d.strftime("%Y-%m"), v] for d, v in serie]
        debug["avisos"].append(f"Setor externo {chave} (SGS {cod}, {desc}): últimas leituras {out[chave][-3:]}")
    mensal = dict(out["ca_mensal"])
    m12, v12 = out["ca_12m"][-1]
    meses = []
    a, mm = int(m12[:4]), int(m12[5:])
    for _ in range(12):
        meses.append(f"{a}-{mm:02d}")
        mm -= 1
        if mm == 0:
            a, mm = a - 1, 12
    if not all(m in mensal for m in meses):
        raise RuntimeError(f"Conta corrente: faltam meses na série mensal para somar 12 meses até {m12}")
    soma = sum(mensal[m] for m in meses)
    if abs(soma - v12) > max(2000.0, 0.04 * abs(v12)):
        raise RuntimeError(f"Conta corrente: a soma dos 12 meses da série mensal ({soma:.0f}) não bate com a série acumulada ({v12:.0f}) em {m12}; conferir SGS 22701 e 24419")
    pib = dict(out["ca_pib"])
    if m12 in pib and abs(v12) > 3000 and (pib[m12] > 0) != (v12 > 0):
        raise RuntimeError(f"Conta corrente: o sinal do % do PIB ({pib[m12]}) não bate com o do saldo em 12 meses ({v12}) em {m12}")
    idp12 = sum(v for _, v in out["idp_mensal"][-12:])
    if not 15000 <= idp12 <= 200000:
        raise RuntimeError(f"IDP: soma dos últimos 12 meses ({idp12:.0f} US$ milhões) fora do esperado; conferir SGS 22885")
    debug["avisos"].append(f"Setor externo: conta corrente em 12 meses {v12:.0f} US$ milhões ({m12}); soma mensal {soma:.0f}; IDP em 12 meses {idp12:.0f}")

    diaria = sgs(RESERVAS_SGS, dt.date(2015, 1, 1))
    if len(diaria) < 500 or not all(150000 <= v <= 600000 for _, v in diaria):
        raise RuntimeError(f"Reservas (SGS {RESERVAS_SGS}) fora do esperado ({len(diaria)} dias, faixa 150 a 600 bilhões); últimas leituras: {[(d.isoformat(), v) for d, v in diaria[-3:]]}")
    ult_dia, ult_v = diaria[-1]
    if (HOJE - ult_dia).days > 30:
        raise RuntimeError(f"Reservas: último dado é de {ult_dia}, mais de 30 dias atrás")
    fim_mes = {}
    for d, v in diaria:
        fim_mes[d.strftime("%Y-%m")] = v
    out["reservas"] = [[m, v] for m, v in sorted(fim_mes.items())]
    out["reservas_ultima"] = [ult_dia.isoformat(), ult_v]
    debug["avisos"].append(f"Reservas (SGS {RESERVAS_SGS}): {len(diaria)} dias; última leitura {out['reservas_ultima']}; fim de mês {out['reservas'][-3:]}")
    return out


def balanca():
    """Balança comercial mensal (Secex/MDIC, Comex Stat), lida do arquivo de dados do Comex em Números (mesma família, já validado lá).
    Valores em US$ milhões (FOB). Se o BCB 22707 (balanço de pagamentos) responder, só registra a diferença no diagnóstico."""
    d = get(BALANCA_URL, tentativas=3, timeout=120).json()
    mensal = d.get("mensal") or {}
    exp = {x["mes"]: round(float(x["fob"]) / 1e6, 1) for x in mensal.get("export") or []}
    imp = {x["mes"]: round(float(x["fob"]) / 1e6, 1) for x in mensal.get("import") or []}
    meses = sorted(set(exp) & set(imp))
    if len(meses) < 60:
        raise RuntimeError(f"Balança: só {len(meses)} meses em comum entre exportação e importação")
    if not all(5000 <= exp[m] <= 80000 and 5000 <= imp[m] <= 70000 for m in meses):
        raise RuntimeError(f"Balança: valores fora de US$ 5 a 80 bilhões por mês; últimos: {[(m, exp[m], imp[m]) for m in meses[-3:]]}")
    ult = dt.date(int(meses[-1][:4]), int(meses[-1][5:]), 1)
    if (HOJE - ult).days > 150:
        raise RuntimeError(f"Balança: último mês ({meses[-1]}) tem mais de 5 meses")
    out = {"mes": meses[-1], "export": [[m, exp[m]] for m in meses], "import": [[m, imp[m]] for m in meses]}
    debug["avisos"].append(f"Balança (MDIC): {len(meses)} meses; último {meses[-1]}: exportação {exp[meses[-1]]}, importação {imp[meses[-1]]}")
    try:
        bp = dict((d.strftime("%Y-%m"), v) for d, v in sgs(22707, dt.date(2025, 1, 1)))
        comuns = [m for m in meses[-12:] if m in bp]
        if comuns:
            dif = sum(bp[m] - (exp[m] - imp[m]) for m in comuns)
            debug["avisos"].append(f"Balança: saldo do balanço de pagamentos (SGS 22707) menos saldo MDIC, soma de {len(comuns)} meses: {dif:.0f} US$ milhões")
    except Exception as e:  # noqa: BLE001 - só diagnóstico
        debug["avisos"].append(f"Balança: conferência com o SGS 22707 não feita ({e})")
    return out



# ---------------------------------------------------------------- Bolsa Família por município
BF_ARQ = RAIZ / "data" / "bolsa_familia.json"
BF_URL = "https://aplicacoes.mds.gov.br/sagi/servicos/misocial"  # API MI Social (MDS/SAGI), sem chave
BF_CAMPOS = ("ibge:codigo_ibge,anomes:anomes_s,f:qtd_familias_beneficiarias_bolsa_familia_i,"
             "p:qtd_pessoas_beneficiarias_bolsa_familia_i,v:valor_repassado_bolsa_familia_f")
BF_INICIO = "2023-03"  # mês em que o novo Bolsa Família substituiu o Auxílio Brasil
BF_MAX_MESES = 48
BF_LINHAS = 10000      # linhas por página da consulta (o Brasil tem ~5,6 mil municípios)
BF_ORCAMENTO_S = 600   # tempo máximo da coleta do Bolsa Família; o que faltar entra na próxima execução


class RespostaNaoJson(RuntimeError):
    """O servidor respondeu com uma página (aviso, bloqueio, manutenção) em vez de JSON."""


def bf_sonda():
    """Diagnóstico para quando o MI Social responde com uma página em vez de JSON: testa algumas variações do pedido e registra o resultado."""
    import requests
    navegador = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
                 "Accept": "application/json,text/plain,*/*", "Accept-Language": "pt-BR,pt;q=0.9"}
    simples = {"q": "*:*", "wt": "json", "rows": "1"}
    real = {"q": "*", "fq": ["anomes_s:202609", "tipo_s:mes_mu"], "wt": "json", "omitHeader": "true", "fl": BF_CAMPOS, "rows": "2", "sort": "codigo_ibge asc"}
    testes = [("GET simples (agente do robô)", "GET", BF_URL, UA, simples, True),
              ("GET simples (agente de navegador)", "GET", BF_URL, navegador, simples, True),
              ("GET consulta real (agente de navegador)", "GET", BF_URL, navegador, real, True),
              ("GET simples sem seguir redirecionamento", "GET", BF_URL, UA, simples, False),
              ("GET com barra final", "GET", BF_URL + "/", navegador, simples, True),
              ("POST consulta real", "POST", BF_URL, navegador, real, True),
              ("GET host antigo (cidadania)", "GET", BF_URL.replace("mds.gov.br", "cidadania.gov.br"), navegador, simples, False)]
    for rotulo, metodo, url, hdr, params, seguir in testes:
        try:
            r = (requests.post(url, data=params, headers=hdr, timeout=30, allow_redirects=seguir) if metodo == "POST"
                 else requests.get(url, params=params, headers=hdr, timeout=30, allow_redirects=seguir))
            hist = [(h.status_code, h.headers.get("location", "")[:120]) for h in r.history]
            debug["avisos"].append(f"Sonda MI Social, {rotulo}: HTTP {r.status_code}, {r.headers.get('content-type')}, {len(r.content)} bytes, "
                                   f"histórico {hist}, local {r.headers.get('location', '')[:150]!r}, início {r.text[:100]!r}")
        except Exception as e:  # noqa: BLE001
            debug["avisos"].append(f"Sonda MI Social, {rotulo}: erro {e!r}")


def bf_meses_candidatos(hoje=None):
    """Meses AAAA-MM de BF_INICIO até o mês atual (no máximo BF_MAX_MESES, os mais recentes)."""
    hoje = hoje or HOJE
    a, m = int(BF_INICIO[:4]), int(BF_INICIO[5:])
    out = []
    while (a, m) <= (hoje.year, hoje.month):
        out.append(f"{a}-{m:02d}")
        m += 1
        if m == 13:
            a, m = a + 1, 1
    return out[-BF_MAX_MESES:]


def bf_baixa_mes(ym):
    """Todas as linhas município x mês do Bolsa Família no mês `ym` (AAAA-MM): {ibge de 6 dígitos: [famílias, pessoas, R$ repassados]}."""
    out, inicio, total = {}, 0, None
    while True:
        r = get(BF_URL, {"q": "*", "fq": [f"anomes_s:{ym.replace('-', '')}", "tipo_s:mes_mu"], "wt": "json", "omitHeader": "true",
                         "fl": BF_CAMPOS, "rows": str(BF_LINHAS), "start": str(inicio), "sort": "codigo_ibge asc"}, tentativas=3, timeout=120)
        try:
            corpo = r.json()
        except ValueError:
            raise RespostaNaoJson(f"MI Social não devolveu JSON (HTTP {r.status_code}, {r.headers.get('content-type')}, {len(r.content)} bytes, "
                               f"endereço final {r.url[:300]}): {r.text[:300]!r}") from None
        resp = (corpo or {}).get("response") or {}
        docs = resp.get("docs") or []
        total = resp.get("numFound", len(docs)) if total is None else total
        for d in docs:
            cod = str(d.get("ibge", "")).strip()
            if len(cod) == 7 and cod.isdigit():
                cod = cod[:6]
            if len(cod) != 6 or not cod.isdigit():
                continue
            try:
                f, p, v = (float(d[k]) if d.get(k) not in (None, "") else 0.0 for k in ("f", "p", "v"))
            except (TypeError, ValueError):
                continue
            out[cod] = [int(round(f)), int(round(p)), round(v, 2)]
        inicio += len(docs)
        if not docs or inicio >= total:
            break
    if len(out) < len(docs) and not out:
        debug["avisos"].append(f"Bolsa Família {ym}: nenhuma linha utilizável; amostra {docs[:2]}")
    return out


def bf_confere_mes(ym, mes, anterior):
    """Recusa um mês que não parece a folha do Bolsa Família (município faltando, mês ainda não publicado, unidade errada)."""
    tf = sum(x[0] for x in mes.values())
    tp = sum(x[1] for x in mes.values())
    tv = sum(x[2] for x in mes.values())
    if len(mes) < 5000:
        return f"só {len(mes)} municípios (esperado mais de 5.000)"
    if not 5e6 <= tf <= 3e7:
        return f"{tf:.0f} famílias no total, fora de 5 a 30 milhões"
    if not tf <= tp <= 6 * tf:
        return f"{tp:.0f} pessoas para {tf:.0f} famílias, relação absurda"
    if not 100 <= tv / tf <= 2500:
        return f"benefício médio de R$ {tv / tf:.0f}, fora de R$ 100 a R$ 2.500"
    if anterior and tf < 0.6 * anterior:
        return f"{tf:.0f} famílias, menos de 60% do mês anterior ({anterior:.0f}); publicação provavelmente incompleta"
    return None


def bf_populacao():
    """População residente estimada por município (IBGE, SIDRA 6579): {ibge de 6 dígitos: [nome, sigla da UF]}, {ibge: população}, ano."""
    linhas = get("https://apisidra.ibge.gov.br/values/t/6579/n6/all/v/9324/p/last%201", tentativas=3, timeout=120).json()
    cab, dados = linhas[0], linhas[1:]
    nomes, pop, anos = {}, {}, set()
    for x in dados:
        try:
            v = int(float(x.get("V")))
        except (TypeError, ValueError):
            continue
        cod = str(x.get("D1C", ""))[:6]
        nome, _, uf = str(x.get("D1N", "")).rpartition(" - ")
        if len(cod) != 6 or not cod.isdigit() or not nome or len(uf) != 2:
            continue
        nomes[cod], pop[cod] = [nome.strip(), uf], v
        anos.add(str(x.get("D3C", "")))
    if len(pop) < 5400 or not 190e6 <= sum(pop.values()) <= 260e6:
        raise RuntimeError(f"População (SIDRA 6579): {len(pop)} municípios, soma {sum(pop.values())}; cabeçalho {cab}")
    ano = max(anos) if anos else ""
    debug["avisos"].append(f"População: {len(pop)} municípios, soma {sum(pop.values())}, ano {ano}")
    return nomes, pop, ano


def bolsa_familia():
    """Bolsa Família por município e mês (famílias, pessoas, R$ repassados). Guarda tudo em data/bolsa_familia.json:
    baixa os meses que faltam (do mais novo ao mais antigo, dentro de um orçamento de tempo) e refaz o último mês guardado,
    que pode ser revisado. O arquivo é determinístico (sem data de geração) para não gerar commit à toa."""
    antigo = json.loads(BF_ARQ.read_text(encoding="utf-8")) if BF_ARQ.exists() else {}
    meses = dict(antigo.get("meses") or {})
    nomes, pop, ano = antigo.get("nomes"), antigo.get("pop"), antigo.get("pop_ano", "")
    if not nomes or not pop:
        nomes, pop, ano = bf_populacao()
    t0 = time.time()
    candidatos = bf_meses_candidatos()
    faltam = [m for m in reversed(candidatos) if m not in meses]
    refazer = [max(meses)] if meses else []
    seguidas = 0
    novos = 0
    sondou = False
    for ym in refazer + faltam:
        if time.time() - t0 > BF_ORCAMENTO_S:
            debug["avisos"].append(f"Bolsa Família: orçamento de {BF_ORCAMENTO_S}s esgotado; faltam {[m for m in faltam if m not in meses][:6]}... para a próxima execução")
            break
        try:
            mes = bf_baixa_mes(ym)
        except Exception as e:  # noqa: BLE001
            seguidas += 1
            debug["avisos"].append(f"Bolsa Família {ym}: falhou ({e})")
            if isinstance(e, RespostaNaoJson) and not sondou:
                sondou = True
                bf_sonda()
            if seguidas >= 2:
                raise RuntimeError(f"Bolsa Família: duas falhas seguidas, última em {ym}: {e}") from e
            continue
        seguidas = 0
        if not mes or sum(x[0] for x in mes.values()) == 0:
            debug["avisos"].append(f"Bolsa Família {ym}: sem dados (mês ainda não publicado), {len(mes)} linhas")
            continue
        vizinho = [m for m in sorted(meses) if m < ym]
        anterior = sum(x[0] for x in meses[vizinho[-1]].values()) if vizinho else None
        motivo = bf_confere_mes(ym, mes, anterior)
        if motivo:
            # com histórico guardado, um mês recusado costuma ser a folha do mês corrente ainda incompleta: só avisa
            (debug["avisos"] if meses else debug["erros"]).append(f"Bolsa Família {ym}: recusado, {motivo}")
            continue
        meses[ym] = {c: x for c, x in sorted(mes.items()) if c in nomes}
        novos += 1
        tf, tp, tv = (sum(x[i] for x in meses[ym].values()) for i in range(3))
        debug["avisos"].append(f"Bolsa Família {ym}: {len(mes)} municípios, {tf:,} famílias, {tp:,} pessoas, R$ {tv:,.0f}; amostra {list(meses[ym].items())[:2]}")
    if not meses:
        raise RuntimeError("Bolsa Família: nenhum mês foi baixado")
    meses = {m: meses[m] for m in sorted(meses)[-BF_MAX_MESES:]}
    anterior_ok = None
    for ym in sorted(meses):  # a verificação mês a mês só vê o vizinho já guardado; aqui o conjunto final é conferido em ordem
        tf = sum(x[0] for x in meses[ym].values())
        if anterior_ok and tf < 0.6 * anterior_ok:
            (debug["avisos"] if antigo.get("meses") else debug["erros"]).append(
                f"Bolsa Família {ym}: recusado, {tf:.0f} famílias, menos de 60% do mês anterior ({anterior_ok:.0f}); publicação provavelmente incompleta")
            del meses[ym]
            continue
        anterior_ok = tf
    BF_ARQ.write_text(json.dumps({"fonte": "MDS/SAGI (MI Social); população: IBGE (SIDRA 6579)", "pop_ano": ano, "nomes": nomes, "pop": pop, "meses": meses},
                                 ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    debug["avisos"].append(f"Bolsa Família: {len(meses)} meses guardados ({min(meses)} a {max(meses)}), {novos} baixados agora")
    return {"meses": len(meses), "ultimo": max(meses)}


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
    a12 = acumulada em 12 meses. Receita nominal e qualquer outro acumulado (no ano) não interessam (None).
    Atenção: 'acumulada no ano' vem escrita 'em relação ao mesmo período do ano anterior', por isso 'acumulad' é testado antes de 'ano anterior'."""
    t = texto.lower()
    if "receita" in t:
        return None
    if "%" in unid or "variação" in t:
        if "acumulad" in t:
            return "a12" if "12 meses" in t else None
        if "12 meses" in t:
            return "a12"
        if "mesmo mês" in t or "ano anterior" in t or "igual" in t:
            return "yoy"
        if "sazonal" in t and "trimest" not in t:
            return "mm"
        return None
    if "índice" in t or "indice" in t:
        return "sa" if "sazonal" in t else "idx"
    return None


def _desloca(per, n):
    """Soma n meses a um período 'AAAAMM'."""
    m = int(per[:4]) * 12 + int(per[4:6]) - 1 + n
    return f"{m // 12:04d}{m % 12 + 1:02d}"


def _calcula(med):
    """Variações calculadas dos números-índice: mm (do índice com ajuste), yoy e a12 (do índice sem ajuste)."""
    sa, idx = med.get("sa", {}), med.get("idx", {})
    out = {}
    if sa:
        out["mm"] = {p: round((v / sa[_desloca(p, -1)] - 1) * 100, 1) for p, v in sa.items() if _desloca(p, -1) in sa}
    if idx:
        out["yoy"] = {p: round((v / idx[_desloca(p, -12)] - 1) * 100, 1) for p, v in idx.items() if _desloca(p, -12) in idx}
        a12 = {}
        for p in idx:
            atual, antes = [_desloca(p, -k) for k in range(12)], [_desloca(p, -k) for k in range(12, 24)]
            if all(q in idx for q in atual + antes):
                a12[p] = round((sum(idx[q] for q in atual) / sum(idx[q] for q in antes) - 1) * 100, 1)
        out["a12"] = a12
    return out


def _completa(med, calc):
    """Variações que o IBGE não devolveu entram calculadas (e ficam registradas no debug)."""
    derivadas = []
    for k, v in calc.items():
        if k not in med:
            med[k] = v
            derivadas.append(k)
    return derivadas


def _confere(nome, med, calc, oficiais, tol=0.3):
    """Compara a variação oficial dos últimos 6 meses com a calculada do índice: pega coluna trocada (ex.: acumulado no ano no lugar de mês/mesmo mês)."""
    for k in oficiais:
        comuns = sorted(set(med[k]) & set(calc.get(k, {})))[-6:]
        ruins = [(p, med[k][p], calc[k][p]) for p in comuns if abs(med[k][p] - calc[k][p]) > tol]
        if ruins:
            raise RuntimeError(f"{nome}: a variação '{k}' do IBGE não confere com a calculada do índice (período, oficial, calculada): {ruins[:3]}")


def indicador_ibge(tabela, ultimos, classes, filtro, nome):
    """Série mensal do IBGE. `filtro(dims)` escolhe as linhas da atividade/tipo de índice que interessa.
    Devolve {sa, idx, mm, yoy, a12: [[AAAA-MM, valor], ...]}."""
    med, soltas, vistas, nomes = {}, set(), set(), {}
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
        nomes.setdefault(m, set()).add(texto)
    debug["avisos"].append(f"{nome}: medida -> variável usada {({m: sorted(v) for m, v in nomes.items()})}")
    if soltas:
        debug["avisos"].append(f"{nome}: linhas ignoradas {sorted(soltas)[:12]}")
    if "sa" not in med:
        raise RuntimeError(f"{nome}: sem número-índice com ajuste sazonal (medidas achadas: {sorted(med)}; textos vistos: {sorted(vistas)[:10]})")
    calc = _calcula(med)
    _confere(nome, med, calc, [k for k in ("mm", "yoy", "a12") if k in med])
    derivadas = _completa(med, calc)
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
                             ("credito", credito, False), ("industria", producao_industrial, False), ("varejo", varejo, False),
                             ("externo", setor_externo, False), ("balanca", balanca, False)]:
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
    t1 = time.time()
    try:  # Bolsa Família fica em arquivo próprio (data/bolsa_familia.json); falha aqui não mexe no resto
        bolsa_familia()
        print(f"ok: bolsa_familia ({time.time() - t1:.0f}s)", flush=True)
    except Exception as e:  # noqa: BLE001
        debug["erros"].append(f"bolsa_familia: {e}")
        print(f"FALHA em bolsa_familia ({time.time() - t1:.0f}s): {e}", file=sys.stderr, flush=True)
    debug.setdefault("tempos", {})["bolsa_familia"] = round(time.time() - t1, 1)
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
