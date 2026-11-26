"""Salário de quem foi contratado, por profissão (CBO 2002) e por cidade: últimos 12 meses de admissões
nos microdados do Novo Caged (Ministério do Trabalho e Emprego, FTP do PDET).

Entram só admissões com salário mensal, jornada de 30 horas ou mais, sem trabalho intermitente, parcial ou
aprendiz. É o salário de contratação, não a média de quem já trabalha.

Saída: data/salarios.json
  {"meses": [AAAAMM...], "cbo": {codigo: nome}, "br": {cbo: [n, p25, p50, p75]}, "uf": {cbo: {uf: [n, p50]}},
   "mun": {mun6: {"t": [n, p50], "c": {cbo: [n, p50]}}}}
Uso: python scripts/salarios.py [--forcar]
"""
from __future__ import annotations

import datetime as dt
import ftplib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "data" / "salarios.json"
HOST, BASE = "ftp.mtps.gov.br", "/pdet/microdados/NOVO CAGED"
COLS = ["uf", "município", "saldomovimentação", "cbo2002ocupação", "horascontratuais", "salário", "unidadesaláriocódigo",
        "indtrabintermitente", "indtrabparcial", "indicadoraprendiz", "tipomovimentação"]
MIN_BR, MIN_UF, MIN_MUN, TOP_MUN = 30, 20, 10, 40


def log(*a):
    print(*a, flush=True)


def conectar():
    ftp = ftplib.FTP(HOST, timeout=180, encoding="latin-1")
    ftp.login()
    return ftp


def meses_disponiveis(ftp) -> list[str]:
    out = []
    for ano in ftp.nlst(BASE):
        a = ano.rsplit("/", 1)[-1]
        if a.isdigit() and int(a) >= 2020:
            out += [m.rsplit("/", 1)[-1] for m in ftp.nlst(ano) if m.rsplit("/", 1)[-1].isdigit()]
    return sorted(out)


def nomes_cbo(ftp) -> dict:
    import openpyxl
    arq = next(x for x in ftp.nlst(BASE) if "layout" in x.lower() and "movimenta" in x.lower())
    b = io.BytesIO()
    ftp.retrbinary(f"RETR {arq}", b.write)
    wb = openpyxl.load_workbook(b, read_only=True)
    ws = next(wb[n] for n in wb.sheetnames if "cbo" in n.lower())
    out = {}
    for cod, nome, *_ in ws.iter_rows(min_row=2, values_only=True):
        if cod is not None and nome:
            out[str(int(cod)).zfill(6)] = str(nome).strip()
    return out


def ler_mes(ym: str, pasta: Path):
    """Baixa e lê um mês; devolve um DataFrame só com as admissões que entram na conta."""
    import pandas as pd
    for tentativa in range(3):
        try:
            ftp = conectar()
            arq = f"{BASE}/{ym[:4]}/{ym}/CAGEDMOV{ym}.7z"
            z = pasta / f"{ym}.7z"
            with open(z, "wb") as fh:
                ftp.retrbinary(f"RETR {arq}", fh.write)
            ftp.quit()
            break
        except Exception as e:  # noqa: BLE001
            log(f"  {ym}: falhou o download ({e!r}), tentando de novo")
            time.sleep(20 * (tentativa + 1))
    else:
        raise RuntimeError(f"não consegui baixar {ym}")
    subprocess.run(["7z", "x", "-y", f"-o{pasta / ym}", str(z)], check=True, capture_output=True)
    z.unlink()
    txt = next(p for p in (pasta / ym).rglob("*.txt"))
    df = pd.read_csv(txt, sep=";", decimal=",", usecols=COLS, dtype={"cbo2002ocupação": str}, encoding="utf-8", low_memory=False)
    shutil.rmtree(pasta / ym)
    df.columns = ["uf", "mun", "saldo", "cbo", "horas", "sal", "unid", "interm", "parcial", "aprendiz", "tipomov"]
    for c in ("horas", "sal"):
        if df[c].dtype == object:
            df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", "."), errors="coerce")
    if not getattr(ler_mes, "_mostrou", False):  # diagnóstico do primeiro mês
        ler_mes._mostrou = True
        log("  tipos:", dict(df.dtypes.astype(str)))
        for c in ("saldo", "unid", "interm", "parcial", "aprendiz", "tipomov"):
            log(f"  {c}:", df[c].value_counts().head(6).to_dict())
        log("  horas:", df.horas.describe().round(1).to_dict(), "| sal:", df.sal.describe().round(0).to_dict())
    ok = ((df.saldo == 1) & (df.unid == 5) & (df.interm == 0) & (df.parcial == 0) & (df.aprendiz == 0)
          & (~df.tipomov.isin([35, 70])) & (df.horas >= 30) & (df.sal >= 800) & (df.sal <= 200000))
    df = df.loc[ok, ["uf", "mun", "cbo", "sal"]].copy()
    df["cbo"] = df["cbo"].str.strip().str.zfill(6)
    df["sal"] = df["sal"].astype("float32")
    return df


def main():
    forcar = "--forcar" in sys.argv
    ftp = conectar()
    import os
    meses = meses_disponiveis(ftp)[-int(os.environ.get("MESES", "12")):]
    antigo = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {}
    if not forcar and antigo.get("meses") == meses:
        log("Sem mês novo no Novo Caged:", meses[-1])
        return 0
    cbo = nomes_cbo(ftp)
    ftp.quit()
    log("Meses:", meses[0], "a", meses[-1], "| profissões na tabela:", len(cbo))
    import pandas as pd
    partes = []
    with tempfile.TemporaryDirectory() as tmp:
        for ym in meses:
            t0 = time.time()
            d = ler_mes(ym, Path(tmp))
            partes.append(d)
            log(f"  {ym}: {len(d):,} admissões ({time.time() - t0:.0f}s)")
    df = pd.concat(partes, ignore_index=True)
    del partes
    log("Total:", f"{len(df):,}")

    r = lambda v: int(round(float(v)))
    br = df.groupby("cbo").sal.agg(n="size", p50="median")
    br = br[br.n >= MIN_BR]
    qs = df[df.cbo.isin(br.index)].groupby("cbo").sal.quantile([0.25, 0.75]).unstack()
    out_br = {c: [int(br.at[c, "n"]), r(qs.at[c, 0.25]), r(br.at[c, "p50"]), r(qs.at[c, 0.75])] for c in br.index}
    uf = df.groupby(["cbo", "uf"]).sal.agg(n="size", p50="median").reset_index()
    out_uf = {}
    for t in uf[uf.n >= MIN_UF].itertuples(index=False):
        out_uf.setdefault(t.cbo, {})[str(int(t.uf))] = [int(t.n), r(t.p50)]
    mt = df.groupby("mun").sal.agg(n="size", p50="median").reset_index()
    out_mun = {str(int(t.mun)): {"t": [int(t.n), r(t.p50)], "c": {}} for t in mt[mt.n >= MIN_MUN].itertuples(index=False)}
    mc = df.groupby(["mun", "cbo"]).sal.agg(n="size", p50="median").reset_index()
    mc = mc[mc.n >= MIN_MUN].sort_values(["mun", "n"], ascending=[True, False])
    mc = mc.groupby("mun").head(TOP_MUN)
    for t in mc.itertuples(index=False):
        k = str(int(t.mun))
        if k in out_mun:
            out_mun[k]["c"][t.cbo] = [int(t.n), r(t.p50)]
    if not out_br:
        raise SystemExit("Nenhuma profissão calculada: algo mudou no arquivo do Caged (veja o diagnóstico acima). Nada foi salvo.")
    usados = set(out_br) | {c for v in out_mun.values() for c in v["c"]}
    saida = {"fonte": "Ministério do Trabalho e Emprego, Novo Caged (microdados de movimentação)",
             "gerado_em": dt.date.today().isoformat(), "meses": meses, "total": int(len(df)),
             "cbo": {c: cbo.get(c, c) for c in sorted(usados)}, "br": out_br, "uf": out_uf, "mun": out_mun}
    SAIDA.write_text(json.dumps(saida, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"Salvo: {len(out_br)} profissões no Brasil, {len(out_mun)} municípios, {SAIDA.stat().st_size / 1e6:.1f} MB")
    exemplos = sorted(out_br.items(), key=lambda kv: -kv[1][0])[:10]
    for c, v in exemplos:
        log("  ", c, cbo.get(c), v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
