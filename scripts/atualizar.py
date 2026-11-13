#!/usr/bin/env python3
"""Robô de dados do Economia em Números.

Baixa as séries públicas e grava data/dados.json:
  - Meta Selic (Banco Central, SGS 432)
  - IPCA mensal (SGS 433) e acumulado em 12 meses (SGS 13522)
  - IPCA das 16 áreas pesquisadas pelo IBGE (SIDRA, tabela 7060)
  - Expectativas do Boletim Focus (Banco Central, Olinda)

Roda no GitHub Actions (a rede do ambiente de desenvolvimento não alcança essas APIs).
Se uma fonte opcional falhar, o robô mantém o dado anterior daquela fonte e segue.
Se uma fonte essencial (Selic ou IPCA do Brasil) falhar, sai com erro e não mexe no dados.json.
"""
import datetime as dt
import json
import sys
import time
from pathlib import Path


RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "data" / "dados.json"
DEBUG = RAIZ / "data" / "debug.json"
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
        # O serviço Olinda já recusou filtros com data; tentamos do mais simples para o mais completo.
        tentativas = [
            {"$top": "600", "$format": "json", "$orderby": "Data desc", "$filter": f"Indicador eq '{ind}'"},
            {"$top": "3000", "$format": "json", "$filter": f"Indicador eq '{ind}'"},
            {"$top": "600", "$format": "json", "$orderby": "Data desc", "$filter": f"Indicador eq '{ind}' and Data ge '{desde}'"},
        ]
        for params in tentativas:
            try:
                linhas += get(url, params, tentativas=2).json().get("value", [])
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


def main():
    antigo = json.loads(DADOS.read_text(encoding="utf-8")) if DADOS.exists() else {}
    novo = dict(antigo)
    essenciais_ok = True
    for nome, fn, essencial in [("selic", selic, True), ("ipca", ipca_brasil, True), ("areas", ipca_areas, False), ("focus", focus, False)]:
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
