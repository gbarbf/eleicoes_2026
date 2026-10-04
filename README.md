# Apuração 2026 x 2022

App local para acompanhar a apuração da eleição presidencial de hoje (04/10/2026)
e comparar, **hora a hora e cidade a cidade**, com a apuração de 2022:
quantos votos Lula e Bolsonaro tinham *naquele horário* em 2022 e quantos os
candidatos 13 e 22 (ou quaisquer outros que você escolher) têm agora.

Só precisa de Python 3.9+ (sem dependências externas).

## Como rodar

```bash
# 1) (uma vez) monta a linha do tempo de 2022 a partir dos boletins de urna do TSE
#    baixa ~28 zips (alguns GB no total); dá para usar zips já baixados com --dir
python3 scripts/montar_2022.py

# 2) sobe o servidor: ele consulta o TSE a cada 3 min e grava o histórico de 2026
python3 server.py
# abra http://localhost:8026
```

Quer só ver a interface? `python3 server.py --demo` (números fictícios).

Opções úteis do servidor:

| opção | para quê |
|---|---|
| `--intervalo 120` | segundos entre coletas (padrão 180) |
| `--ufs SP,RJ,MG` | coletar só alguns estados (menos requisições) |
| `--eleicao 619` | código da eleição no TSE, se a descoberta automática falhar |
| `--sem-coleta` | só exibir o que já foi gravado em `data/fotos_2026.sqlite` |

**Deixe o servidor rodando desde o início da apuração (17h):** a curva de 2026
é formada pelas coletas que ele grava. Se você ligar às 20h, a curva de 2026
começa às 20h (mas a comparação "agora x 2022 no mesmo horário" funciona).

## O que a página mostra

- **Situação agora**: % de seções apuradas no Brasil e votos de cada candidato.
- **Comparação** num horário escolhido (agora, 17:10, 17:20… ou final), para
  Brasil, um estado ou uma cidade: votos de 2022 até aquele horário x 2026,
  % apurado, % dos válidos e a diferença.
- **Hora a hora**: gráfico com as quatro curvas (2022 tracejado, 2026 contínuo)
  em votos, % dos válidos ou % apurado.
- **Tabela estado a estado / cidade a cidade**, ordenável e com busca. Clique
  numa linha para ver o gráfico dela; clique de novo num estado para abrir as cidades.

"Lado Lula" e "lado Bolsonaro" em 2026 são, por padrão, os números **13** e
**22** — dá para trocar por qualquer candidato nos seletores.

## De onde vêm os dados (e as limitações)

- **2026**: arquivos públicos do site de resultados do TSE
  (`resultados.tse.jus.br/oficial/ele2026/<código>/dados-simplificados/...`).
  O código da eleição é descoberto em `comum/config/ele-c.json` pela data.
- **2022**: o TSE não guarda o histórico da divulgação minuto a minuto, então a
  curva é **reconstruída a partir dos boletins de urna** (dados abertos): cada
  seção entra no horário registrado no boletim (`DT_EMISSAO_BU` ou `DT_BU`),
  convertido para o horário de Brasília (o fuso de cada UF é detectado
  automaticamente). É uma aproximação: a totalização no TSE acontecia alguns
  minutos depois da emissão do boletim. Granularidade de 10 minutos.
- Horários depois de 02:00 entram em "final".

## Arquivos

- `server.py` — coleta no TSE, guarda em SQLite e serve a API e a página.
- `scripts/montar_2022.py` — gera `data/linha_tempo_2022_t1.json.gz`.
- `scripts/gerar_demo.py` — dados fictícios para `--demo`.
- `web/` — página (HTML/CSS/JS + Chart.js embutido).
