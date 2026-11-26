"""Avisa quando sai um resumo novo em qualquer portal da família, para postar no X, no Instagram e no LinkedIn.

Roda de hora em hora (.github/workflows/avisos.yml). Para cada portal, lê o sitemap e a página /resumo/,
pega o resumo mais recente de cada tipo (semanal e mensal) e, se ainda não houver aviso para ele, abre uma
issue neste repositório com a imagem e os textos prontos, mencionando a conta do projeto (o GitHub manda
e-mail e notificação no app). O próprio histórico de issues (rótulo "resumo") é a memória: nada é gravado no repositório.
Quando sai um resumo novo do mesmo portal e tipo, o aviso anterior que ainda estiver aberto é fechado.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
import urllib.request

PORTAIS = [
    ("Óleo em Números", "https://oleoemnumeros.com.br"),
    ("Comex em Números", "https://comexemnumeros.com.br"),
    ("Voo em Números", "https://vooemnumeros.com.br"),
    ("Economia em Números", "https://economiaemnumeros.com.br"),
    ("Imóveis em Números", "https://imoveisemnumeros.com.br"),
]
MENCAO = "@oleoemnumeros"
ROTULO = "resumo"
REPO = os.environ.get("GITHUB_REPOSITORY", "oleoemnumeros/economia-em-numeros")


def baixar(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "familia-em-numeros-avisos/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def caminhos_resumo(base: str, textos: list[str]) -> set[str]:
    """Caminhos /resumo/.../ de resumos individuais (não a lista /resumo/), achados em sitemap ou HTML."""
    achados = set()
    dom = re.escape(base)
    for t in textos:
        for m in re.finditer(r'(?:' + dom + r')?(/resumo/(?:[\w-]+/)+)(?=["<\s])', t):
            achados.add(m.group(1))
    return {c for c in achados if c != "/resumo/" and re.search(r"\d{4}-\d{2}", c)}


def tipo(caminho: str) -> str:
    return "semanal" if "/semana/" in caminho else "mensal"


def mais_recentes(caminhos: set[str]) -> dict[str, str]:
    """Tipo -> caminho mais recente (a chave com data ordena como texto: 2026-11-19 > 2026-11-13)."""
    out = {}
    for c in caminhos:
        chave = re.findall(r"\d{4}-\d{2}(?:-\d{2})?", c)[-1]
        t = tipo(c)
        if t not in out or chave > out[t][0]:
            out[t] = (chave, c)
    return {t: c for t, (_, c) in out.items()}


def campo(pagina: str, ident: str) -> str:
    m = re.search(r'<textarea[^>]*id="' + ident + r'"[^>]*>(.*?)</textarea>', pagina, re.S)
    return html.unescape(m.group(1)).strip() if m else ""


def sem_hashtags(t: str) -> str:
    t = re.sub(r"(?m)^\s*(#\w+\s*)+$", "", t)          # linhas só de hashtags
    t = re.sub(r"\s#\w+", "", t)                          # hashtags soltas no texto
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def legenda_instagram(base_txt: str) -> str:
    """Mesma regra do botão do site (familia.js): link vira só o domínio e entra 'Link na bio.'"""
    t = re.sub(r"https?://(www\.)?([^/\s]+)\S*", r"\2", base_txt)
    t = re.sub(r"[ \t]+\n", "\n", t).strip()
    return t + "\n\nLink na bio."


def montar(nome: str, base: str, caminho: str, pagina: str) -> tuple[str, str]:
    url = base + caminho
    m = re.search(r"<h1[^>]*>(.*?)</h1>", pagina, re.S)
    titulo = html.unescape(re.sub(r"<[^>]+>", " ", m.group(1))).strip() if m else caminho
    titulo = re.sub(r"\s+", " ", titulo)
    post_x = sem_hashtags(campo(pagina, "post-x"))
    post = campo(pagina, "post")
    ig = legenda_instagram(post or post_x) if (post or post_x) else ""
    tem_card = 'card.png' in pagina
    tem_ig = 'card-instagram.png' in pagina
    t = tipo(caminho)
    partes = [f"{MENCAO} saiu um resumo {t} novo no **{nome}**.",
              "",
              f"**Página do resumo (tem os botões Publicar no X, Compartilhar no Instagram e Copiar texto):** {url}",
              ""]
    if tem_card:
        partes += [f"![Imagem do resumo]({url}card.png)", ""]
    partes += ["### X", "Imagem: " + (f"{url}card.png" if tem_card else "sem imagem"), "```text", post_x or "(sem texto pronto: use a página)", "```", ""]
    partes += ["### Instagram", "Imagem: " + (f"{url}card-instagram.png" if tem_ig else (f"{url}card.png" if tem_card else "sem imagem")),
               "```text", ig or "(sem texto pronto: use a página)", "```", ""]
    partes += ["### LinkedIn", "```text", post or post_x or "(sem texto pronto: use a página)", "```", "",
               "Depois de postar, feche esta issue. Se sair outro resumo do mesmo tipo antes, este aviso fecha sozinho.",
               "", f"<!-- aviso-resumo {url} -->"]
    rot = "Resumo semanal" if t == "semanal" else "Resumo mensal"
    return f"📣 {rot} · {nome}: {titulo}"[:240], "\n".join(partes)


def gh(*args: str, entrada: str | None = None) -> str:
    r = subprocess.run(["gh", *args], input=entrada, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()}")
    return r.stdout


def avisos_existentes() -> list[dict]:
    out = gh("api", "--paginate", f"repos/{REPO}/issues?labels={ROTULO}&state=all&per_page=100", "--jq", ".[]")
    return [json.loads(l) for l in out.splitlines() if l.strip()]


def main() -> int:
    seco = "--seco" in sys.argv
    existentes = [] if seco else avisos_existentes()
    ja = {}
    for i in existentes:
        m = re.search(r"<!-- aviso-resumo (\S+) -->", i.get("body") or "")
        if m:
            ja[m.group(1)] = i
    if not seco:
        try:
            gh("api", "-X", "POST", f"repos/{REPO}/labels", "-f", f"name={ROTULO}", "-f", "color=D9A514",
               "-f", "description=Aviso de resumo novo para postar nas redes")
        except RuntimeError:
            pass  # rótulo já existe
    novos = 0
    for nome, base in PORTAIS:
        textos = []
        for cam in ("/sitemap.xml", "/resumo/"):
            try:
                textos.append(baixar(base + cam))
            except Exception as e:  # noqa: BLE001
                print(f"{nome}: não li {cam} ({e})", file=sys.stderr)
        recentes = mais_recentes(caminhos_resumo(base, textos))
        if not recentes:
            print(f"{nome}: sem resumos")
            continue
        for t, caminho in sorted(recentes.items()):
            url = base + caminho
            if url in ja:
                print(f"{nome} ({t}): {caminho} já avisado")
                continue
            try:
                pagina = baixar(url)
            except Exception as e:  # noqa: BLE001
                print(f"{nome}: não abri {url} ({e})", file=sys.stderr)
                continue
            titulo, corpo = montar(nome, base, caminho, pagina)
            if seco:
                print("=" * 60, "\n", titulo, "\n", corpo)
                continue
            criado = json.loads(gh("api", "-X", "POST", f"repos/{REPO}/issues", "--input", "-",
                                   entrada=json.dumps({"title": titulo, "body": corpo, "labels": [ROTULO]})))
            novos += 1
            print(f"{nome} ({t}): aviso aberto #{criado['number']}")
            for u, i in ja.items():  # fecha o aviso anterior do mesmo portal e tipo, se ainda aberto
                if u.startswith(base + "/") and tipo(u) == t and i.get("state") == "open":
                    gh("api", "-X", "POST", f"repos/{REPO}/issues/{i['number']}/comments", "-f", f"body=Substituído pelo #{criado['number']}.")
                    gh("api", "-X", "PATCH", f"repos/{REPO}/issues/{i['number']}", "-f", "state=closed", "-f", "state_reason=not_planned")
    print(f"avisos novos: {novos}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
