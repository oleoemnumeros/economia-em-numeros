"""SONDAGEM temporária: arquivos de transferências constitucionais por município do Tesouro Transparente (CKAN).

Lista os recursos do conjunto de dados, baixa o mais recente e um de 2024 e grava em data/transferencias/sondagem.json
o cabeçalho, as primeiras linhas, o total de linhas e os valores distintos das colunas com poucos valores.
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path

import os
import time
from urllib.parse import quote

import requests

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "data" / "transferencias"
CKAN = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=af4e7c47-2132-4d9a-bd7c-34e28a210b03"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


CAMINHOS = []


def baixar(url, timeout=300):
    """O gov.br às vezes derruba a conexão do GitHub: tenta direto, depois a ponte do projeto (RELAY), depois o leitor r.jina.ai."""
    relay, token = os.environ.get("RELAY_URL", "").strip(), os.environ.get("RELAY_TOKEN", "").strip()
    tentativas = [("direto", lambda: requests.get(url, headers=UA, timeout=timeout))]
    if relay and token:
        tentativas.append(("ponte", lambda: requests.get(f"{relay.rstrip('/')}/?url={quote(url, safe='')}", headers={"X-Token": token}, timeout=timeout)))
    tentativas.append(("leitor", lambda: requests.get("https://r.jina.ai/" + url, headers={"X-Return-Format": "text", "Accept": "text/plain"}, timeout=timeout)))
    erros = []
    for nome, f in tentativas:
        for i in range(2):
            try:
                r = f()
                if r.status_code == 200:
                    CAMINHOS.append(f"{nome}: {url[-60:]}")
                    return r
                erros.append(f"{nome} HTTP {r.status_code}")
            except requests.RequestException as e:
                erros.append(f"{nome} {type(e).__name__}")
            time.sleep(5 * (i + 1))
    raise RuntimeError("; ".join(erros))


def amostra(url):
    try:
        r = baixar(url)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "erro": str(e)}
    out = {"url": url, "http": r.status_code, "bytes": len(r.content)}
    if r.status_code != 200:
        out["texto"] = r.text[:300]
        return out
    for enc in ("utf-8-sig", "latin-1"):
        try:
            txt = r.content.decode(enc)
            out["encoding"] = enc
            break
        except UnicodeDecodeError:
            continue
    try:
        sep = csv.Sniffer().sniff(txt[:5000], delimiters=";,|\t").delimiter
    except csv.Error:
        sep = ";"
    out["sep"] = sep
    out["primeiras_linhas_brutas"] = txt.splitlines()[:12]
    linhas = list(csv.reader(io.StringIO(txt), delimiter=sep))
    out["n_linhas"] = len(linhas)
    if linhas:
        cab = linhas[0]
        out["cabecalho"] = cab
        dist = {}
        for i, c in enumerate(cab):
            vals = Counter(l[i] for l in linhas[1:] if i < len(l))
            dist[c] = {"n_distintos": len(vals), "mais_comuns": vals.most_common(40 if len(vals) < 80 else 5)}
        out["colunas"] = dist
    return out


def main():
    PASTA.mkdir(parents=True, exist_ok=True)
    res = {}
    res["ponte_configurada"] = bool(os.environ.get("RELAY_URL"))
    r = baixar(CKAN, 120)
    try:
        j = r.json()
    except ValueError:
        t = r.text
        j = json.loads(t[t.find("{"):t.rfind("}") + 1])
    recs = j["result"]["resources"]
    res["recursos"] = [{"nome": r.get("name"), "url": r.get("url"), "mod": r.get("last_modified") or r.get("created")} for r in recs]
    csvs = [r for r in recs if (r.get("url") or "").lower().endswith(".csv")]
    csvs.sort(key=lambda r: r.get("last_modified") or r.get("created") or "")
    alvo = csvs[-2:] + [r for r in csvs if "2024" in (r.get("name") or "")][:1]
    res["amostras"] = [amostra(r["url"]) for r in alvo]
    res["caminhos"] = CAMINHOS
    (PASTA / "sondagem.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok", [a.get("n_linhas") for a in res["amostras"]])


if __name__ == "__main__":
    main()
