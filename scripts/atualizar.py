#!/usr/bin/env python3
"""Robô de dados do Economia em Números.

Baixa as séries públicas e grava data/dados.json:
  - Meta Selic (Banco Central, SGS 432)
  - IPCA mensal (SGS 433) e acumulado em 12 meses (SGS 13522)
  - IPCA das 16 áreas pesquisadas pelo IBGE (SIDRA, tabela 7060)
  - Expectativas do Boletim Focus (Banco Central, Olinda)
  - Atas do Copom: confere no site do Banco Central se o PDF de cada ata já existe
  - Desocupação (PNAD Contínua, SIDRA 4099 por UF e 6381 trimestre móvel) e saldo de vagas formais (Novo Caged, SGS 28763)

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
UA = {"User-Agent": "EconomiaEmNumeros/1.0 (+https://economiaemnumeros.com.br)"}
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


def get(url, params=None, tentativas=4):
    import requests  # importado aqui para os testes não dependerem dele

    ultimo = None
    for i in range(tentativas):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=90)
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


def focus():
    """Medianas anuais do Boletim Focus (Selic, IPCA, PIB e câmbio) e variação na semana."""
    url = "https://olinda.bcb.gov.br/olinda/servico/Expectativas/versao/v1/odata/ExpectativasMercadoAnuais"
    desde = (HOJE - dt.timedelta(days=24)).isoformat()
    linhas, falhas = [], []
    for ind in ("Selic", "IPCA", "PIB Total", "Câmbio"):
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
    for ind in ("Selic", "IPCA", "PIB Total", "Câmbio"):
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


def main():
    antigo = json.loads(DADOS.read_text(encoding="utf-8")) if DADOS.exists() else {}
    novo = dict(antigo)
    essenciais_ok = True
    for nome, fn, essencial in [("selic", selic, True), ("ipca", ipca_brasil, True), ("areas", ipca_areas, False), ("focus", focus, False),
                             ("atas", atas, False), ("desocupacao", desocupacao, False), ("caged", caged, False),
                             ("cambio", cambio, False), ("ibc", ibcbr, False), ("pib", pib, False)]:
        try:
            novo[nome] = fn()
            print(f"ok: {nome}")
        except Exception as e:  # noqa: BLE001 - queremos registrar qualquer falha e seguir
            debug["erros"].append(f"{nome}: {e}")
            print(f"FALHA em {nome}: {e}", file=sys.stderr)
            if essencial and nome not in antigo:
                essenciais_ok = False
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
