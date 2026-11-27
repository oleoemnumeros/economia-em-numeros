"""Salário de quem foi contratado, por profissão (CBO 2002) e por cidade: últimos 12 meses de admissões
nos microdados do Novo Caged (Ministério do Trabalho e Emprego, FTP do PDET).

Entram só admissões com salário mensal, jornada de 30 horas ou mais, sem trabalho intermitente, parcial ou
aprendiz. É o salário de contratação, não a média de quem já trabalha.

Na mesma passada sai o emprego formal por município e setor (admissões e desligamentos de todas as
movimentações, mais as declarações fora do prazo e menos as exclusões, como faz o Ministério).

Saída: data/salarios.json e data/emprego_mun.json
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
SAIDA_EMP = RAIZ / "data" / "emprego_mun.json"
HOST, BASE = "ftp.mtps.gov.br", "/pdet/microdados/NOVO CAGED"
COLS = ["uf", "município", "saldomovimentação", "cbo2002ocupação", "horascontratuais", "salário", "unidadesaláriocódigo",
        "indtrabintermitente", "indtrabparcial", "indicadoraprendiz", "tipomovimentação", "seção"]
COLS_AJ = ["competênciamov", "uf", "município", "seção", "saldomovimentação"]
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


TROCA = {"garcom": "garçom", "garcons": "garçons", "ti": "TI", "sus": "SUS", "cnc": "CNC", "clt": "CLT"}


def limpador_de_nomes():
    """A tabela da CBO no arquivo do Caged vem sem acento e com Cada Palavra Maiúscula ('Tecnico de Enfermagem').
    Devolve uma função que deixa 'Técnico de enfermagem': acentos pelo dicionário de português do pyspellchecker
    (só troca quando a forma sem acento é rara ou não existe) e '(Desativado em 2010)' sai do nome."""
    import re
    import unicodedata
    from spellchecker import SpellChecker
    wf = SpellChecker(language="pt").word_frequency
    sa = lambda t: "".join(ch for ch in unicodedata.normalize("NFD", t) if unicodedata.category(ch) != "Mn")
    melhor = {}
    for w, f in wf.items():
        k = sa(w)
        if k != w and (k not in melhor or f > melhor[k][1]):
            melhor[k] = (w, f)

    def palavra(w):
        lw = w.lower()
        if lw in TROCA:
            return TROCA[lw]
        if w.isupper() and len(w) > 1 and sa(w) == w and lw not in wf:
            return w  # sigla
        if lw in melhor and (wf[lw] if lw in wf else 0) < 0.1 * melhor[lw][1]:
            return melhor[lw][0]
        return lw

    def limpa(n):
        n = re.sub(r"\s*\(desativad[oa][^)]*\)", "", str(n), flags=re.I).strip()
        partes = re.findall(r"[^\W\d_]+|[\W\d_]+", n)
        t = "".join(palavra(x) if re.match(r"[^\W\d_]", x) else x for x in partes)
        return t[:1].upper() + t[1:]
    return limpa


def baixar_txt(ym: str, tipo: str, pasta: Path) -> Path:
    """Baixa e descompacta CAGED{tipo}{ym}.7z (tipo MOV, FOR ou EXC); devolve o .txt."""
    for tentativa in range(3):
        try:
            ftp = conectar()
            arq = f"{BASE}/{ym[:4]}/{ym}/CAGED{tipo}{ym}.7z"
            z = pasta / f"{tipo}{ym}.7z"
            with open(z, "wb") as fh:
                ftp.retrbinary(f"RETR {arq}", fh.write)
            ftp.quit()
            break
        except Exception as e:  # noqa: BLE001
            log(f"  {tipo}{ym}: falhou o download ({e!r}), tentando de novo")
            time.sleep(20 * (tentativa + 1))
    else:
        raise RuntimeError(f"não consegui baixar {tipo}{ym}")
    subprocess.run(["7z", "x", "-y", f"-o{pasta / (tipo + ym)}", str(z)], check=True, capture_output=True)
    z.unlink()
    return next(p for p in (pasta / (tipo + ym)).rglob("*.txt"))


def ler_ajuste(ym: str, tipo: str, pasta: Path):
    """Declarações fora do prazo (FOR) ou exclusões (EXC) informadas no mês: contagem por competência, município,
    setor e sentido (+1 admissão, -1 desligamento). None se o arquivo não vier."""
    import pandas as pd
    try:
        txt = baixar_txt(ym, tipo, pasta)
    except Exception as e:  # noqa: BLE001
        log(f"  aviso: sem {tipo}{ym} ({e!r})")
        return None
    df = pd.read_csv(txt, sep=";", usecols=lambda c: c in COLS_AJ, dtype={"seção": str}, encoding="utf-8", low_memory=False)
    shutil.rmtree(pasta / (tipo + ym))
    if set(df.columns) != set(COLS_AJ):
        log(f"  aviso: colunas inesperadas em {tipo}{ym}: {list(df.columns)}")
        return None
    df = df.rename(columns={"competênciamov": "ym", "município": "mun", "seção": "sec", "saldomovimentação": "saldo"})
    df["ym"] = df["ym"].astype(str).str[:6]
    return df.groupby(["ym", "uf", "mun", "sec", "saldo"]).size().rename("n").reset_index()


def ler_mes(ym: str, pasta: Path):
    """Baixa e lê um mês. Devolve (admissões que entram na conta do salário, contagem de movimentações por
    município, setor e sentido)."""
    import pandas as pd
    txt = baixar_txt(ym, "MOV", pasta)
    df = pd.read_csv(txt, sep=";", decimal=",", usecols=COLS, dtype={"cbo2002ocupação": str, "seção": str}, encoding="utf-8", low_memory=False)
    shutil.rmtree(pasta / ("MOV" + ym))
    # o pandas devolve as colunas na ordem do arquivo, não na de COLS: renomeia pelo nome
    df = df.rename(columns=dict(zip(COLS, ["uf", "mun", "saldo", "cbo", "horas", "sal", "unid", "interm", "parcial", "aprendiz", "tipomov", "sec"])))
    mov = df.groupby(["uf", "mun", "sec", "saldo"]).size().rename("n").reset_index()
    mov["ym"] = ym
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
    return df, mov


SECOES = {
    "A": "Agropecuária, pesca e produção florestal", "B": "Indústrias extrativas (petróleo e mineração)", "C": "Indústria de transformação",
    "D": "Eletricidade e gás", "E": "Água, esgoto e resíduos", "F": "Construção", "G": "Comércio e reparação de veículos",
    "H": "Transporte, armazenagem e correio", "I": "Hotéis, bares e restaurantes", "J": "Informação e comunicação",
    "K": "Bancos, seguros e finanças", "L": "Atividades imobiliárias", "M": "Serviços profissionais, científicos e técnicos",
    "N": "Serviços administrativos (limpeza, vigilância, call center)", "O": "Administração pública", "P": "Educação",
    "Q": "Saúde e assistência social", "R": "Cultura, esporte e lazer", "S": "Outros serviços", "T": "Serviços domésticos",
    "U": "Organismos internacionais"}


def emprego(mv, meses: list[str]) -> None:
    """Admissões e desligamentos por mês (12 meses) e por setor (soma dos 12 meses), para o Brasil, cada estado e cada município."""
    mv = mv[mv.ym.isin(meses)].copy()
    mv["n"] = mv["n"] * mv["sinal"]
    mv["tipo"] = mv["saldo"].map({1: "a", -1: "d"})
    import pandas as pd
    for c in ("mun", "uf"):
        mv[c] = pd.to_numeric(mv[c], errors="coerce")
    mv = mv.dropna(subset=["tipo", "mun", "uf"])
    mv["mun"] = mv["mun"].astype(int).astype(str)
    mv["uf"] = mv["uf"].astype(int).astype(str)
    mv["sec"] = mv["sec"].astype(str).str.strip().str.upper()
    idx = {m: i for i, m in enumerate(meses)}

    def bloco(g):
        m = [[0, 0] for _ in meses]
        for (ym, tp), n in g.groupby(["ym", "tipo"]).n.sum().items():
            m[idx[ym]][0 if tp == "a" else 1] += int(n)
        s = {}
        for (sec, tp), n in g.groupby(["sec", "tipo"]).n.sum().items():
            if sec in SECOES:
                s.setdefault(sec, [0, 0])[0 if tp == "a" else 1] += int(n)
        return {"m": m, "s": s}

    br = bloco(mv)
    ufs = {u: bloco(g) for u, g in mv[mv.uf != "99"].groupby("uf")}
    mun = {}
    for k, g in mv[~mv.mun.isin(["999999", "9999999"])].groupby("mun"):
        b = bloco(g)
        if sum(a + d for a, d in b["m"]) >= 20:
            mun[k] = b
    tot_a, tot_d = sum(a for a, _ in br["m"]), sum(d for _, d in br["m"])
    log(f"Emprego: {tot_a:,} admissões, {tot_d:,} desligamentos, saldo {tot_a - tot_d:+,} em 12 meses; {len(mun)} municípios")
    log("  saldo por mês (Brasil):", [a - d for a, d in br["m"]])
    if not mun or tot_a == 0:
        raise SystemExit("Emprego por município vazio: nada foi salvo.")
    SAIDA_EMP.write_text(json.dumps({"fonte": "Ministério do Trabalho e Emprego, Novo Caged (movimentações, fora do prazo e exclusões)",
                                     "gerado_em": dt.date.today().isoformat(), "meses": meses, "secoes": SECOES,
                                     "br": br, "uf": ufs, "mun": mun}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"Salvo: {SAIDA_EMP.name}, {SAIDA_EMP.stat().st_size / 1e6:.1f} MB")


def main():
    forcar = "--forcar" in sys.argv
    ftp = conectar()
    import os
    meses = meses_disponiveis(ftp)[-int(os.environ.get("MESES", "12")):]
    antigo = json.loads(SAIDA.read_text(encoding="utf-8")) if SAIDA.exists() else {}
    if not forcar and antigo.get("meses") == meses and SAIDA_EMP.exists():
        log("Sem mês novo no Novo Caged:", meses[-1])
        return 0
    cbo = nomes_cbo(ftp)
    ftp.quit()
    try:
        limpa = limpador_de_nomes()
        cbo = {c: limpa(n) for c, n in cbo.items()}
    except Exception as e:  # noqa: BLE001 - sem o dicionário, fica o nome original
        log("  aviso: não consegui acentuar os nomes:", repr(e)[:200])
    log("Meses:", meses[0], "a", meses[-1], "| profissões na tabela:", len(cbo))
    import pandas as pd
    partes, movs = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for ym in meses:
            t0 = time.time()
            d, mv = ler_mes(ym, Path(tmp))
            partes.append(d)
            movs.append(mv.assign(sinal=1))
            for tipo, sinal in (("FOR", 1), ("EXC", -1)):
                aj = ler_ajuste(ym, tipo, Path(tmp))
                if aj is not None:
                    movs.append(aj.assign(sinal=sinal))
            log(f"  {ym}: {len(d):,} admissões ({time.time() - t0:.0f}s)")
    emprego(pd.concat(movs, ignore_index=True), meses)
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
