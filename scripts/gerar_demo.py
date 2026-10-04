#!/usr/bin/env python3
"""Gera dados FICTÍCIOS em data/demo/ para testar a interface sem acesso ao TSE."""

import gzip
import json
import math
import os
import random
import shutil
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from linha_tempo import (  # noqa: E402
    BALDE_MIN, FIM_MIN, INICIO_MIN, N_BALDES, balde_de_minuto, epoch_para_minuto, minuto_para_epoch,
)
from server import Fotos2026  # noqa: E402
from datetime import date  # noqa: E402

PASTA = os.path.join(os.path.dirname(__file__), "..", "data", "demo")
DIA = date(2026, 10, 4)
UFS = ("AC AL AM AP BA CE DF ES GO MA MG MS MT PA PB PE PI PR RJ RN RO RR RS SC SE SP TO ZZ").split()
CANDS = [("13", "CANDIDATO 13 (DEMO)", "PT"), ("22", "CANDIDATO 22 (DEMO)", "PL"),
         ("12", "CANDIDATO 12 (DEMO)", "PDT"), ("15", "CANDIDATO 15 (DEMO)", "MDB")]


def curva(minuto, atraso):
    """Fração de seções apuradas (logística) num certo minuto."""
    x = (minuto - INICIO_MIN - atraso) / 35
    return 1 / (1 + math.exp(-x))


def main():
    rnd = random.Random(2026)
    shutil.rmtree(PASTA, ignore_errors=True)
    os.makedirs(PASTA)
    abr, mun22, cidades = [], {}, []
    cd = 10000
    for uf in UFS:
        mus = []
        for i in range(rnd.randint(3, 8)):
            cd += rnd.randint(7, 90)
            nome = f"{'CAPITAL' if i == 0 else 'MUNICÍPIO ' + str(i)} {uf}"
            secoes = rnd.randint(200, 6000) if i == 0 else rnd.randint(20, 600)
            mus.append({"cd": str(cd), "nm": nome})
            cidades.append((str(cd), uf, secoes, rnd.uniform(0.3, 0.7), rnd.uniform(20, 120)))
        abr.append({"cd": uf, "ds": uf, "mu": mus})
    with open(os.path.join(PASTA, "municipios_2026.json"), "w", encoding="utf-8") as f:
        json.dump({"abr": abr}, f, ensure_ascii=False)

    # 2022: votos por balde, a partir de uma curva logística por cidade.
    for cd, uf, secoes, lado, atraso in cidades:
        baldes = {}
        for s in range(secoes):
            u = min(max(rnd.random(), 1e-6), 1 - 1e-6)
            minuto = INICIO_MIN + atraso + 35 * math.log(u / (1 - u))
            k = balde_de_minuto(max(minuto, INICIO_MIN))
            vv = rnd.randint(150, 330)
            v13 = int(vv * min(max(rnd.gauss(lado, 0.05), 0), 1))
            v22 = int((vv - v13) * 0.9)
            b = baldes.setdefault(k, [0, 0, 0, 0])
            for i, v in enumerate((1, v13, v22, vv)):
                b[i] += v
        nm = next(m["nm"] for a in abr for m in a["mu"] if m["cd"] == cd)
        mun22[cd] = {"uf": uf, "nm": nm, "s": secoes, "d": [[k, *baldes[k]] for k in sorted(baldes)]}
    meta = {"fonte": "DEMO (fictício)", "turno": 1, "data": "2022-10-02", "inicio_min": INICIO_MIN,
            "fim_min": FIM_MIN, "balde_min": BALDE_MIN, "n_baldes": N_BALDES}
    with gzip.open(os.path.join(PASTA, "linha_tempo_2022_t1.json.gz"), "wt", encoding="utf-8") as f:
        json.dump({"meta": meta, "mun": mun22}, f, ensure_ascii=False)

    # 2026: fotografias a cada 5 min até agora (ou a noite toda, fora do dia da eleição).
    agora = epoch_para_minuto(DIA, time.time())
    limite = agora if INICIO_MIN + 30 < agora < FIM_MIN else FIM_MIN
    fotos = Fotos2026(os.path.join(PASTA, "fotos_2026.sqlite"))
    for minuto in range(INICIO_MIN, int(limite) + 1, 5):
        tot = {}
        for cd, uf, secoes, lado, atraso in cidades:
            frac = curva(minuto, atraso * 0.8)
            st = int(secoes * frac)
            vv = st * 250
            pa = min(max(lado + 0.03 * math.sin(int(cd)), 0.05), 0.95)
            votos = {"13": int(vv * pa), "22": int(vv * (1 - pa) * 0.85), "12": int(vv * (1 - pa) * 0.1)}
            votos["15"] = vv - sum(votos.values())
            dados = {"st": st, "s": secoes, "vv": vv, "hg": f"{minuto // 60 % 24:02d}:{minuto % 60:02d}:00",
                     "cand": [{"n": n, "nm": nm, "cc": cc, "vap": votos[n]} for n, nm, cc in CANDS]}
            ts = minuto_para_epoch(DIA, minuto)
            fotos.registrar(cd, ts, dados)
            for chave in (uf.lower(), "br"):
                t = tot.setdefault(chave, {"st": 0, "s": 0, "vv": 0, "v": dict.fromkeys(votos, 0)})
                t["st"] += st
                t["s"] += secoes
                t["vv"] += vv
                for n in votos:
                    t["v"][n] += votos[n]
        for chave, t in tot.items():
            dados = {"st": t["st"], "s": t["s"], "vv": t["vv"],
                     "hg": f"{minuto // 60 % 24:02d}:{minuto % 60:02d}:00",
                     "cand": [{"n": n, "nm": nm, "cc": cc, "vap": t["v"][n]} for n, nm, cc in CANDS]}
            fotos.registrar(chave, minuto_para_epoch(DIA, minuto), dados)
    fotos.commit()
    print(f"Demo gerada em {os.path.normpath(PASTA)}: {len(cidades)} municípios fictícios")


if __name__ == "__main__":
    main()
