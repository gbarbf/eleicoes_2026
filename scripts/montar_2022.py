#!/usr/bin/env python3
"""Monta a linha do tempo da apuração de 2022 (presidente), cidade a cidade.

O TSE não publica o histórico minuto a minuto da divulgação de 2022, então a
curva é reconstruída a partir dos Boletins de Urna (dados abertos do TSE):
cada seção entra na apuração no horário registrado no seu boletim. O
resultado é uma boa aproximação do ritmo real da totalização (que chegava ao
TSE poucos minutos depois da emissão do boletim).

Uso:
    python3 scripts/montar_2022.py                 # baixa os 28 zips do TSE
    python3 scripts/montar_2022.py --dir ~/bweb    # usa zips já baixados
    python3 scripts/montar_2022.py --turno 2 --dir ~/bweb_2t

Saída: data/linha_tempo_2022_t{turno}.json.gz
"""

import argparse
import csv
import glob
import gzip
import io
import json
import os
import statistics
import sys
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from linha_tempo import (  # noqa: E402
    BALDE_MIN, FIM_MIN, INICIO_MIN, N_BALDES, NUM_BOLSONARO, NUM_LULA, balde_de_minuto,
)

UFS = ("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO ZZ").split()
URL_MODELO_T1 = "https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2022/buweb/bweb_1t_{uf}_051020221321.zip"
DATAS = {1: date(2022, 10, 2), 2: date(2022, 10, 30)}
# Ordem de preferência da coluna de horário do boletim.
COLUNAS_HORA = ("DT_EMISSAO_BU", "DT_BU", "DT_ENCERRAMENTO")

csv.field_size_limit(10**9)


def abrir_zip(uf, args):
    if args.dir:
        achados = glob.glob(os.path.join(os.path.expanduser(args.dir), f"*_{uf}_*.zip"))
        if not achados:
            print(f"  [{uf}] zip não encontrado em {args.dir}, pulando")
            return None
        return zipfile.ZipFile(achados[0])
    url = args.url_modelo.format(uf=uf)
    cache = os.path.join(args.cache, os.path.basename(url))
    if not os.path.exists(cache):
        os.makedirs(args.cache, exist_ok=True)
        print(f"  [{uf}] baixando {url}")
        req = urllib.request.Request(url, headers={"User-Agent": "apuracao-2026-comparador"})
        with urllib.request.urlopen(req, timeout=600) as r, open(cache + ".part", "wb") as f:
            while bloco := r.read(1 << 20):
                f.write(bloco)
        os.replace(cache + ".part", cache)
    return zipfile.ZipFile(cache)


def minuto_do_dia(texto, dia):
    texto = (texto or "").strip()
    for fmt in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"):
        try:
            dt = datetime.strptime(texto, fmt)
            return (dt.date() - dia).days * 1440 + dt.hour * 60 + dt.minute + dt.second / 60
        except ValueError:
            continue
    return None


def ler_uf(uf, args, dia):
    """Retorna {(mun, zona, secao): [minuto, v13, v22, vv]} e nomes dos municípios."""
    zf = abrir_zip(uf, args)
    if zf is None:
        return {}, {}, None
    nome_csv = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
    secoes, nomes, coluna = {}, {}, None
    with zf.open(nome_csv) as bruto:
        leitor = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";")
        coluna = args.coluna or next((c for c in COLUNAS_HORA if c in leitor.fieldnames), None)
        if coluna is None:
            sys.exit(f"Nenhuma coluna de horário encontrada. Colunas: {leitor.fieldnames}")
        for lin in leitor:
            if lin["CD_CARGO_PERGUNTA"].strip() != "1":  # 1 = Presidente
                continue
            mun = lin["CD_MUNICIPIO"].strip().zfill(5)
            chave = (mun, lin["NR_ZONA"].strip(), lin["NR_SECAO"].strip())
            reg = secoes.get(chave)
            if reg is None:
                reg = secoes[chave] = [minuto_do_dia(lin[coluna], dia), 0, 0, 0]
                nomes[mun] = lin["NM_MUNICIPIO"].strip()
            votos = int(lin["QT_VOTOS"] or 0)
            nr = lin["NR_VOTAVEL"].strip()
            if nr == NUM_LULA:
                reg[1] += votos
            elif nr == NUM_BOLSONARO:
                reg[2] += votos
            if lin["DS_TIPO_VOTAVEL"].strip().lower() in ("nominal", "legenda"):
                reg[3] += votos
    return secoes, nomes, coluna


def percentil(valores, p):
    valores = sorted(v for v in valores if v is not None)
    return valores[int(len(valores) * p)] if valores else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--turno", type=int, default=1, choices=(1, 2))
    ap.add_argument("--dir", help="pasta com os zips bweb_*_{UF}_*.zip já baixados")
    ap.add_argument("--url-modelo", default=URL_MODELO_T1, help="URL com {uf} (padrão: 1º turno 2022)")
    ap.add_argument("--cache", default=os.path.join("data", "bweb_2022"))
    ap.add_argument("--coluna", help=f"coluna de horário (padrão: primeira de {COLUNAS_HORA})")
    ap.add_argument("--sem-ajuste-fuso", action="store_true",
                    help="não converter horários locais das urnas para o horário de Brasília")
    ap.add_argument("--saida")
    args = ap.parse_args()
    if args.turno == 2 and not args.dir and args.url_modelo == URL_MODELO_T1:
        sys.exit("Para o 2º turno informe --dir ou --url-modelo com os zips do 2º turno.")

    dia = DATAS[args.turno]
    por_uf, nomes, colunas = {}, {}, set()
    for uf in UFS:
        secoes, nm, col = ler_uf(uf, args, dia)
        if secoes:
            por_uf[uf] = secoes
            nomes.update({(uf, k): v for k, v in nm.items()})
            colunas.add(col)
            print(f"  [{uf}] {len(secoes):>7} seções  ({col})")

    # As urnas registram o horário local. Em 2022 todas fecharam às 17h de
    # Brasília, então a diferença entre o 10º percentil de cada UF e a mediana
    # nacional revela o fuso (AM/MT/MS/RO/RR: 1h, AC: 2h).
    p10 = {uf: percentil([s[0] for s in secoes.values()], 0.10) for uf, secoes in por_uf.items()}
    ref = statistics.median(v for uf, v in p10.items() if v is not None and uf != "ZZ")
    ajuste = {}
    for uf, v in p10.items():
        if args.sem_ajuste_fuso or uf == "ZZ" or v is None:
            ajuste[uf] = 0
        else:
            ajuste[uf] = max(0, min(3, round((ref - v) / 60))) * 60
    print("Ajuste de fuso (min):", {uf: a for uf, a in ajuste.items() if a})

    mun = {}
    for uf, secoes in por_uf.items():
        agreg = defaultdict(lambda: defaultdict(lambda: [0, 0, 0, 0]))
        total_secoes = defaultdict(int)
        for (cd, _z, _s), (minuto, v13, v22, vv) in secoes.items():
            total_secoes[cd] += 1
            k = N_BALDES if minuto is None else balde_de_minuto(minuto + ajuste[uf])
            b = agreg[cd][k]
            b[0] += 1
            b[1] += v13
            b[2] += v22
            b[3] += vv
        for cd, baldes in agreg.items():
            mun[cd] = {
                "uf": uf,
                "nm": nomes[(uf, cd)],
                "s": total_secoes[cd],
                "d": [[k, *baldes[k]] for k in sorted(baldes)],
            }

    saida = args.saida or os.path.join("data", f"linha_tempo_2022_t{args.turno}.json.gz")
    os.makedirs(os.path.dirname(saida), exist_ok=True)
    meta = {
        "fonte": "TSE - Boletins de Urna 2022 (dados abertos)",
        "turno": args.turno,
        "data": dia.isoformat(),
        "coluna_hora": sorted(colunas),
        "ajuste_fuso_min": ajuste,
        "inicio_min": INICIO_MIN,
        "fim_min": FIM_MIN,
        "balde_min": BALDE_MIN,
        "n_baldes": N_BALDES,
        "formato_d": "[balde, secoes, votos_13, votos_22, votos_validos]",
    }
    with gzip.open(saida, "wt", encoding="utf-8") as f:
        json.dump({"meta": meta, "mun": mun}, f, ensure_ascii=False, separators=(",", ":"))
    tot = [sum(b[i] for m in mun.values() for b in m["d"]) for i in (2, 3, 4)]
    print(f"OK: {saida}  municípios={len(mun)}  Lula={tot[0]:,}  Bolsonaro={tot[1]:,}  válidos={tot[2]:,}")


if __name__ == "__main__":
    main()
