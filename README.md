# Economia em Números

Portal independente com dados públicos da economia brasileira: meta da Selic e reuniões do Copom, IPCA (Brasil e 16 áreas do IBGE), expectativas do Boletim Focus e calculadora de correção pelo IPCA.
Site: https://economiaemnumeros.com.br · parte da **Família em Números** (Óleo, Comex, Voo e Economia).

## Como funciona

```
scripts/atualizar.py   robô: baixa Banco Central e IBGE  ->  data/dados.json
scripts/gerar_site.py  gerador: data/*.json + site/       ->  docs/ (não fica no repositório)
.github/workflows/     roda todo dia, gera o site e publica no GitHub Pages
```

- **Fontes:** SGS do Banco Central (Selic 432, IPCA 433 e 13522), SIDRA/IBGE (tabela 7060, IPCA por área) e Olinda/Banco Central (Boletim Focus).
- **Calendário do Copom:** `data/copom_calendario.json`, conferido com o calendário oficial do Banco Central. O BC publica o do ano seguinte em junho: acrescentar as datas ali.
- Se uma fonte falhar, o robô mantém o dado anterior daquela fonte, grava o motivo em `data/debug.json` e o workflow termina com erro (o site é publicado mesmo assim, com o último dado bom).
- A rede do ambiente de desenvolvimento não alcança as APIs do governo: o robô só roda no GitHub Actions.

## Testes e execução local

```
python -m unittest discover -s tests -v          # usa dados sintéticos (tests/exemplo.py)
python scripts/gerar_site.py                     # precisa de data/dados.json (feito pelo robô)
```

## Configuração única no GitHub

1. Settings → Pages → Source: **GitHub Actions**; Custom domain: `economiaemnumeros.com.br`.
2. Actions → "Atualizar dados e publicar o site" → Run workflow (primeira carga de dados).
3. GoatCounter: criar o site `economiaemnumeros` em goatcounter.com (contador sem cookies).

## Próximas etapas

Municípios (IBGE, Bolsa Família, Novo Caged), atas do Copom resumidas, mais indicadores. Ver o roadmap do projeto.
