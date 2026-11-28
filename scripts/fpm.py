"""Transferências constitucionais da União para os municípios (FPM, ITR, royalties, Fundeb...), mês a mês e por decêndio,
dos arquivos mensais do Tesouro Transparente (CKAN, conjunto "Transferências Constitucionais para Municípios").

Cada arquivo traz um mês (o publicado em novembro traz outubro, por exemplo), com as colunas
  Município;UF;ANO;Mês;1º Decêndio;2º Decêndio;3º Decêndio;Item transferência;Transferência
e uma linha por município e parcela. O FPM creditado é a linha com Transferência "FPM" (ou "FPM 1%", o adicional de julho,
setembro e dezembro); "FUNDEB" com item "FPM" é o Fundeb e fica à parte.

O arquivo não traz o código do IBGE: o município é achado pelo nome e pela UF em data/municipios.json. O gov.br às vezes
derruba a conexão do GitHub; aí o robô usa a ponte do projeto (RELAY_URL + RELAY_TOKEN), se houver, ou o leitor público
r.jina.ai, que pode trocar as letras acentuadas por "�". Por isso a comparação de nomes ignora as letras não ASCII.

Saída: data/transferencias/AAAA-MM.json.gz  {"mes", "ufs": {UF: "ok"}, "mun": {código IBGE: {"Transferência/Item": [dec1, dec2, dec3, total]}}}
       data/transferencias/indice.json      arquivos já processados (o mesmo arquivo não é baixado de novo)
       data/transferencias/debug.json       o que aconteceu na última execução
Uso: python scripts/fpm.py
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import json
import os
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import quote

RAIZ = Path(__file__).resolve().parent.parent
PASTA = RAIZ / "data" / "transferencias"
MUNICIPIOS = RAIZ / "data" / "municipios.json"
CKAN = "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_show?id=af4e7c47-2132-4d9a-bd7c-34e28a210b03"
INICIO = "2023-01"
ORCAMENTO_S = int(os.environ.get("ORCAMENTO_S", "2400"))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}


def log(*a):
    print(*a, flush=True)


def baixar(url: str, timeout: int = 300) -> tuple[str, str]:
    """(texto, caminho): direto; se o gov.br recusar, pela ponte do projeto ou pelo leitor público."""
    import requests

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
                if r.status_code == 200 and r.content:
                    if nome == "leitor":
                        return r.text, nome
                    for enc in ("utf-8-sig", "latin-1"):
                        try:
                            return r.content.decode(enc), nome
                        except UnicodeDecodeError:
                            continue
                erros.append(f"{nome} HTTP {r.status_code}")
            except Exception as e:  # noqa: BLE001
                erros.append(f"{nome} {type(e).__name__}")
            time.sleep(5 * (i + 1))
    raise RuntimeError("; ".join(erros))


def chave_nome(nome: str, uf: str) -> str:
    """Nome comparável mesmo quando as letras acentuadas chegaram trocadas por '�': toda letra não ASCII vira '?'."""
    n = unicodedata.normalize("NFC", str(nome or "")).upper().strip()
    n = "".join(c if ord(c) < 128 else "?" for c in n)
    n = re.sub(r"[^A-Z0-9? ]+", " ", n.replace("'", " ").replace("-", " "))
    return f"{uf.upper().strip()}|{' '.join(n.split())}"


def num(v) -> float:
    s = str(v or "").strip()
    if not s:
        return 0.0
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def mapa_municipios() -> dict:
    d = json.loads(MUNICIPIOS.read_text(encoding="utf-8"))
    out, repetidos = {}, set()
    for cod, (nome, uf) in d["nomes"].items():
        k = chave_nome(nome, uf)
        if k in out:
            repetidos.add(k)
        out[k] = cod
    for k in repetidos:   # dois municípios com o mesmo nome na mesma UF: sem como decidir, fica de fora
        out.pop(k, None)
    # segunda chance: sem as letras não ASCII (se o leitor trocou uma letra por dois '�', ou o contrário)
    sem = Counter(k.replace("?", "") for k in out)
    out.update({"~" + k.replace("?", ""): c for k, c in list(out.items()) if sem[k.replace("?", "")] == 1})
    return out


def ler_mes(texto: str, mapa: dict, dbg: Counter) -> dict:
    """Arquivo de um mês -> {"mes", "ufs", "mun"}. As colunas são achadas pelo começo do nome (o acento pode vir trocado)."""
    i = texto.find("Munic")
    if i < 0:
        raise ValueError("cabeçalho não encontrado")
    linhas = list(csv.reader(io.StringIO(texto[i:]), delimiter=";"))
    cab = [chave_nome(c, "").split("|", 1)[1] for c in linhas[0]]

    def col(*prefixos):
        for p in prefixos:
            for k, c in enumerate(cab):
                if c.startswith(p):
                    return k
        raise ValueError(f"coluna {prefixos} não encontrada em {linhas[0]}")
    c_mun, c_uf, c_ano, c_mes = col("MUNIC"), col("UF"), col("ANO"), col("M?S", "MES")
    c_d1, c_d2, c_d3 = col("1? DEC", "1 DEC"), col("2? DEC", "2 DEC"), col("3? DEC", "3 DEC")
    c_item, c_tr = col("ITEM"), col("TRANSFER")
    mes, ufs, mun = None, set(), {}
    for l in linhas[1:]:
        if len(l) <= max(c_tr, c_d3):
            continue
        try:
            ym = f"{int(l[c_ano]):04d}-{int(l[c_mes]):02d}"
        except ValueError:
            continue
        mes = mes or ym
        if ym != mes:
            dbg["linha_de_outro_mes"] += 1
            continue
        uf = l[c_uf].strip().upper()
        k = chave_nome(l[c_mun], uf)
        cod = mapa.get(k) or mapa.get("~" + k.replace("?", ""))
        if not cod:
            dbg["municipio_nao_achado"] += 1
            dbg[f"nao_achado:{uf}|{l[c_mun]}"[:80]] += 1
            continue
        ufs.add(uf)
        parc = f"{' '.join(l[c_tr].split())}/{' '.join(l[c_item].split())}"
        d = [num(l[c_d1]), num(l[c_d2]), num(l[c_d3])]
        reg = mun.setdefault(cod, {})
        v = reg.setdefault(parc, [0.0, 0.0, 0.0, 0.0])
        for k in range(3):
            v[k] = round(v[k] + d[k], 2)
        v[3] = round(v[0] + v[1] + v[2], 2)
    if not mes:
        raise ValueError("nenhuma linha com ano e mês")
    return {"mes": mes, "ufs": {u: "ok" for u in sorted(ufs)}, "mun": mun}


def grava(arq: Path, ob: dict) -> None:
    arq.write_bytes(gzip.compress(json.dumps(ob, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode(), mtime=0))


def main() -> int:
    t0 = time.time()
    PASTA.mkdir(parents=True, exist_ok=True)
    dbg = Counter()
    debug = {"inicio": dt.datetime.now().isoformat(timespec="seconds"), "erros": [], "arquivos": []}
    idx_arq = PASTA / "indice.json"
    indice = json.loads(idx_arq.read_text(encoding="utf-8")) if idx_arq.exists() else {}
    texto, caminho = baixar(CKAN, 120)
    debug["caminho_ckan"] = caminho
    pacote = json.loads(texto[texto.find("{"):texto.rfind("}") + 1])
    recursos = []
    for r in pacote["result"]["resources"]:
        url = r.get("url") or ""
        m = re.search(r"(20\d\d)(\d\d)\.csv", url.lower())
        if not m or not url.lower().endswith(".csv"):
            continue
        # o arquivo AAAAMM traz o mês anterior: entra a partir do que cobre INICIO
        if f"{m.group(1)}-{m.group(2)}" <= INICIO:
            continue
        recursos.append((r.get("last_modified") or r.get("created") or "", r.get("id"), url))
    recursos.sort(reverse=True)  # os mais recentes primeiro
    mapa = mapa_municipios()
    for mod, rid, url in recursos:
        if indice.get(rid) == mod:
            continue
        if time.time() - t0 > ORCAMENTO_S:
            debug["pendentes"] = debug.get("pendentes", 0) + 1
            continue
        try:
            txt, caminho = baixar(url)
            ob = ler_mes(txt, mapa, dbg)
        except Exception as e:  # noqa: BLE001
            debug["erros"].append(f"{url[-50:]}: {e}"[:300])
            log(f"  ERRO {url[-50:]}: {e}")
            continue
        arq = PASTA / f"{ob['mes']}.json.gz"
        antigo = {}
        if arq.exists():
            antigo = json.loads(gzip.decompress(arq.read_bytes()))
        # dois arquivos do mesmo mês (o Tesouro às vezes republica): fica o que tem mais estados
        if len(antigo.get("ufs") or {}) > len(ob["ufs"]):
            debug["arquivos"].append({"url": url[-60:], "mes": ob["mes"], "ufs": len(ob["ufs"]), "ignorado": "outro arquivo do mês tem mais estados"})
        else:
            grava(arq, ob)
        completo = len(ob["ufs"]) >= 27
        if completo:
            indice[rid] = mod      # arquivo incompleto (ou cortado pelo leitor) é baixado de novo na próxima execução
        debug["arquivos"].append({"url": url[-60:], "mes": ob["mes"], "ufs": len(ob["ufs"]), "municipios": len(ob["mun"]), "caminho": caminho})
        log(f"  {ob['mes']}: {len(ob['ufs'])} UFs, {len(ob['mun'])} municípios ({caminho})")
    idx_arq.write_text(json.dumps(indice, indent=1, sort_keys=True), encoding="utf-8")
    debug["contagens"] = dict(dbg.most_common(60))
    debug["fim"] = dt.datetime.now().isoformat(timespec="seconds")
    (PASTA / "debug.json").write_text(json.dumps(debug, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (PASTA / "sondagem.json").unlink(missing_ok=True)
    log(f"Transferências: {len(debug['arquivos'])} arquivos, {len(debug['erros'])} erros.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
