"""Transferências constitucionais da União para os municípios, mês a mês e por decêndio (FPM, ITR, royalties etc.):
API de Transferências Constitucionais do Tesouro Nacional (apiapex.tesouro.gov.br, sem chave).

Uma consulta por estado e mês no endpoint de detalhe, que traz os três decêndios (repasses dos dias 10, 20 e 30)
de cada município e de cada parcela ("FPM", "FUNDEB/FPM", "Royalties/ANP"...). Um estado inteiro num mês tem
cerca de 3 mil linhas e leva uns 10 segundos.

Saída: data/transferencias/AAAA-MM.json.gz
  {"mes": "AAAA-MM", "ufs": {"BA": "2026-11-27T12:00:00"}, "mun": {"<código IBGE>": {"<parcela>": [dec1, dec2, dec3, total]}}}
  data/transferencias/debug.json: parcelas encontradas, erros e o que ficou para a próxima execução.

Meses fechados são baixados uma vez só; o mês atual e o anterior, de novo a cada execução (o Tesouro completa os
repasses e às vezes corrige). A carga inicial (desde INICIO) não cabe numa execução: o robô respeita o
ORCAMENTO_S, começa pelos meses mais recentes e continua de onde parou na execução seguinte.
Uso: python scripts/fpm.py
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import time
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "data" / "transferencias"
BASE = "https://apiapex.tesouro.gov.br/aria/v1/transferencias_constitucionais/custom"
INICIO = "2023-01"
ORCAMENTO_S = int(os.environ.get("ORCAMENTO_S", "2400"))
# Accept "*/*", como faz o pacote tesouropy: o gateway do Tesouro (APEX) responde "Serviço não encontrado" para algumas combinações de cabeçalho
CABECALHOS = ({"Accept": "*/*"}, {"Accept": "*/*", "User-Agent": "EconomiaEmNumeros/1.0 (+https://economiaemnumeros.com.br)"},
              {"Accept": "application/json"})

UF_SIGLA = {  # nome do estado sem acento e em minúsculas -> sigla
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
    "espirito santo": "ES", "goias": "GO", "maranhao": "MA", "mato grosso": "MT", "mato grosso do sul": "MS",
    "minas gerais": "MG", "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI",
    "rio de janeiro": "RJ", "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}


def log(*a):
    print(*a, flush=True)


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode().lower().strip()
    return " ".join(t.split())


def num(v) -> float:
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def itens(resp) -> list:
    """A API devolve {"registros": [...]} (ou {"items": [...]}); aceita também a lista pura."""
    if isinstance(resp, list):
        return resp
    if isinstance(resp, dict):
        for k in ("registros", "items", "itens", "data"):
            if isinstance(resp.get(k), list):
                return resp[k]
    return []


_JEITO = {}   # cabeçalho e forma do endereço que funcionaram na primeira consulta


def get(caminho: str, params: dict | None = None, tentativas: int = 4, timeout: int = 150):
    import requests

    ultimo, tentou = None, []
    jeitos = [_JEITO["j"]] if _JEITO else [(h, barra) for h in CABECALHOS for barra in ("", "/")]
    for i in range(tentativas):
        for cab_, barra in jeitos:
            try:
                r = requests.get(f"{BASE}/{caminho}{barra}", params=params, headers=cab_, timeout=timeout)
                if r.status_code == 200:
                    _JEITO["j"] = (cab_, barra)
                    return r.json()
                ultimo = f"HTTP {r.status_code}: {r.text[:200]}"
                tentou.append(f"{cab_} '{barra}': {r.status_code}")
                if r.status_code in (429, 500, 502, 503, 504):
                    break
            except Exception as e:  # noqa: BLE001
                ultimo = repr(e)[:300]
                break
        time.sleep(15 * (i + 1))
    raise RuntimeError(f"{caminho} {params}: {ultimo} | tentativas: {'; '.join(tentou[:6])}")


def meses(inicio: str, hoje: dt.date) -> list[str]:
    a, m = int(inicio[:4]), int(inicio[5:])
    out = []
    while (a, m) <= (hoje.year, hoje.month):
        out.append(f"{a}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return out


def le(arq: Path) -> dict:
    try:
        return json.loads(gzip.decompress(arq.read_bytes()))
    except Exception:  # noqa: BLE001
        return {}


def grava(arq: Path, ob: dict) -> None:
    arq.write_bytes(gzip.compress(json.dumps(ob, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(), mtime=0))


def main() -> int:
    t0 = time.time()
    hoje = dt.date.today()
    PASTA.mkdir(parents=True, exist_ok=True)
    debug = {"inicio": dt.datetime.now().isoformat(timespec="seconds"), "erros": [], "parcelas": {}, "pendentes": 0}
    estados = {}
    try:
        lista_estados = itens(get("estados"))
    except Exception as e:  # noqa: BLE001
        debug["erros"].append(f"estados: {e}")
        (PASTA / "debug.json").write_text(json.dumps(debug, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        log(f"ERRO: lista de estados: {e}")
        return 1
    for e in lista_estados:
        sigla = UF_SIGLA.get(norm(e.get("nome")))
        if sigla and e.get("codigo") is not None:
            estados[sigla] = e["codigo"]
    log(f"Estados na API: {len(estados)}")
    if len(estados) < 27:
        debug["erros"].append(f"só {len(estados)} estados reconhecidos na API")
    todos = meses(INICIO, hoje)
    recentes = set(todos[-2:])          # mês atual e anterior: o Tesouro ainda completa e corrige
    feitos = 0
    for ym in reversed(todos):          # dos mais recentes para os mais antigos
        arq = PASTA / f"{ym}.json.gz"
        ob = le(arq) or {"mes": ym, "ufs": {}, "mun": {}}
        faltam = [s for s in sorted(estados) if ym in recentes or s not in ob["ufs"]]
        if not faltam:
            continue
        mudou = False
        for sigla in faltam:
            if time.time() - t0 > ORCAMENTO_S:
                debug["pendentes"] += 1
                continue
            try:
                linhas = itens(get("por_estado_municipio_detalhe", {"P_ESTADO": estados[sigla], "P_ANO": int(ym[:4]), "P_MES": int(ym[5:])}))
            except Exception as e:  # noqa: BLE001
                debug["erros"].append(f"{ym} {sigla}: {e}")
                log(f"  ERRO {ym} {sigla}: {e}")
                continue
            if not linhas:
                continue  # mês ainda sem repasse publicado para o estado: tenta de novo na próxima execução
            # tira o estado do mês antes de regravar (o mês recente é baixado de novo inteiro)
            for cod in [c for c, v in ob["mun"].items() if v.get("_uf") == sigla]:
                del ob["mun"][cod]
            for l in linhas:
                cod = "".join(ch for ch in str(l.get("co_ibge") or "") if ch.isdigit())
                parc = " ".join(str(l.get("sg_detalhe") or "").split())
                if not cod or not parc:
                    continue
                reg = ob["mun"].setdefault(cod, {"_uf": sigla})
                v = reg.setdefault(parc, [0.0, 0.0, 0.0, 0.0])
                for k, campo in enumerate(("va_primeiro_dec", "va_segundo_dec", "va_terceiro_dec", "total")):
                    v[k] = round(v[k] + num(l.get(campo)), 2)
                debug["parcelas"][parc] = debug["parcelas"].get(parc, 0) + 1
            if not debug.get("exemplo"):
                debug["exemplo"] = linhas[0]
            ob["ufs"][sigla] = dt.datetime.now().isoformat(timespec="seconds")
            mudou = True
            feitos += 1
            log(f"  {ym} {sigla}: {len(linhas)} linhas")
        if mudou:
            grava(arq, ob)
    debug["consultas"] = feitos
    debug["fim"] = dt.datetime.now().isoformat(timespec="seconds")
    (PASTA / "debug.json").write_text(json.dumps(debug, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    log(f"Transferências: {feitos} consultas, {debug['pendentes']} para a próxima execução, {len(debug['erros'])} erros.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
