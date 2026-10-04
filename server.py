#!/usr/bin/env python3
"""Apuração 2026 x 2022 — servidor local (apenas biblioteca padrão do Python).

- Lê periodicamente os resultados oficiais do TSE (Brasil, UFs e municípios)
  e grava cada mudança em SQLite, formando a curva hora a hora de 2026.
- Carrega a linha do tempo de 2022 (gerada por scripts/montar_2022.py).
- Serve a página em web/ e uma pequena API JSON para compará-las.

Uso:
    python3 server.py                  # http://localhost:8026
    python3 server.py --demo           # dados fictícios para ver a interface
    python3 server.py --eleicao 620    # força o código da eleição no TSE
"""

import argparse
import bisect
import gzip
import json
import os
import sqlite3
import threading
import time
import traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from linha_tempo import (
    BRT, N_BALDES, NUM_BOLSONARO, NUM_LULA, epoch_para_minuto, fim_do_balde,
    minuto_para_epoch, minuto_para_hhmm, ultimo_balde_completo,
)

RAIZ = os.path.dirname(os.path.abspath(__file__))
TSE = "https://resultados.tse.jus.br/oficial"
UA = {"User-Agent": "Mozilla/5.0 (apuracao-2026-comparador)"}


def inteiro(v):
    if v in (None, ""):
        return 0
    return int(str(v).replace(".", "").split(",")[0])


def baixar_json(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------- 2022

class Linha2022:
    """Votos acumulados de 2022 por balde de tempo, para município, UF e Brasil."""

    def __init__(self, caminho):
        self.ok = os.path.exists(caminho)
        self.meta, self.nomes, self.uf_de, self.acum, self.total_secoes = {}, {}, {}, {}, {}
        if not self.ok:
            return
        with gzip.open(caminho, "rt", encoding="utf-8") as f:
            dados = json.load(f)
        self.meta = dados["meta"]
        brutos = {}
        for cd, m in dados["mun"].items():
            self.nomes[cd], self.uf_de[cd] = m["nm"], m["uf"]
            serie = [[0, 0, 0, 0] for _ in range(N_BALDES + 1)]
            for k, *vals in m["d"]:
                serie[k] = vals
            brutos[cd] = serie
            for chave in ("br", m["uf"].lower()):
                agg = brutos.setdefault(chave, [[0, 0, 0, 0] for _ in range(N_BALDES + 1)])
                for k, *vals in m["d"]:
                    agg[k] = [a + b for a, b in zip(agg[k], vals)]
                self.total_secoes[chave] = self.total_secoes.get(chave, 0) + m["s"]
            self.total_secoes[cd] = m["s"]
        for chave, serie in brutos.items():
            acc, cum = [0, 0, 0, 0], []
            for vals in serie:
                acc = [a + b for a, b in zip(acc, vals)]
                cum.append(tuple(acc))
            self.acum[chave] = cum

    def em(self, chave, balde):
        """(secoes, lula, bolsonaro, validos, total_secoes) até o balde informado."""
        if chave not in self.acum:
            return None
        sec, a, b, vv = (0, 0, 0, 0) if balde < 0 else self.acum[chave][balde]
        return {"secoes": sec, "total": self.total_secoes[chave], "a": a, "b": b, "vv": vv}


# --------------------------------------------------------------------------- 2026

class Fotos2026:
    """Fotografias (snapshots) dos resultados de 2026, em memória e em SQLite."""

    def __init__(self, caminho):
        self.lock = threading.Lock()
        self.db = sqlite3.connect(caminho, check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS foto (k TEXT, ts REAL, st INTEGER, s INTEGER,
                vv INTEGER, hg TEXT, c TEXT);
            CREATE INDEX IF NOT EXISTS foto_k_ts ON foto (k, ts);
            CREATE TABLE IF NOT EXISTS cand (n TEXT PRIMARY KEY, nm TEXT, cc TEXT);
            """
        )
        self.series, self.cands = {}, {}
        for k, ts, st, s, vv, hg, c in self.db.execute("SELECT * FROM foto ORDER BY ts"):
            self._anexar(k, (ts, st, s, vv, hg, json.loads(c)))
        for n, nm, cc in self.db.execute("SELECT * FROM cand"):
            self.cands[n] = {"n": n, "nm": nm, "cc": cc}

    def _anexar(self, k, reg):
        serie = self.series.setdefault(k, ([], []))
        serie[0].append(reg[0])
        serie[1].append(reg)

    def registrar(self, k, ts, dados):
        votos = {str(c["n"]): inteiro(c.get("vap")) for c in dados.get("cand", [])}
        reg = (ts, inteiro(dados.get("st")), inteiro(dados.get("s")), inteiro(dados.get("vv")),
               f'{dados.get("dg", "")} {dados.get("hg", "")}'.strip(), votos)
        with self.lock:
            ult = self.series.get(k, ([], []))[1][-1:] or [None]
            if ult[0] and ult[0][1:4] == reg[1:4] and ult[0][5] == votos:
                return False
            self._anexar(k, reg)
            self.db.execute("INSERT INTO foto VALUES (?,?,?,?,?,?,?)", (k, *reg[:5], json.dumps(votos)))
            novos = [c for c in dados.get("cand", []) if str(c["n"]) not in self.cands]
            for c in novos:
                n = str(c["n"])
                self.cands[n] = {"n": n, "nm": c.get("nm", n), "cc": c.get("cc", "")}
                self.db.execute("INSERT OR REPLACE INTO cand VALUES (?,?,?)", (n, c.get("nm", n), c.get("cc", "")))
            return True

    def commit(self):
        with self.lock:
            self.db.commit()

    def em(self, k, epoch=None):
        serie = self.series.get(k)
        if not serie:
            return None
        i = len(serie[0]) if epoch is None else bisect.bisect_right(serie[0], epoch)
        return serie[1][i - 1] if i else None


# --------------------------------------------------------------------------- coleta

class Coletor(threading.Thread):
    def __init__(self, app, intervalo, ufs_filtro):
        super().__init__(daemon=True)
        self.app, self.intervalo, self.ufs_filtro = app, intervalo, ufs_filtro
        self.estado = {"ultima": None, "erro": None, "duracao_s": None, "alteracoes": 0, "falhas": 0}

    def descobrir(self):
        app = self.app
        if not app.cod_eleicao:
            cfg = baixar_json(f"{TSE}/comum/config/ele-c.json")
            alvo = app.data_eleicao.strftime("%d/%m/%Y")
            for pl in cfg.get("pl", []):
                if pl.get("dt") != alvo:
                    continue
                eles = pl.get("e", [])
                fed = [e for e in eles if "federal" in e.get("nm", "").lower()] or eles
                if fed:
                    app.cod_eleicao = str(fed[0]["cd"])
                    print(f"Eleição encontrada: {fed[0].get('nm')} (código {app.cod_eleicao})")
                    break
            if not app.cod_eleicao:
                raise RuntimeError(f"Eleição de {alvo} não encontrada em ele-c.json; use --eleicao")
        if not app.municipios:
            cfg = baixar_json(f"{app.base}/config/mun-e{app.cod6}-cm.json")
            app.definir_municipios(cfg)
            with open(app.caminho_mun, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)

    def url(self, abr, cd=""):
        a = self.app
        return f"{a.base}/dados-simplificados/{abr}/{abr}{cd}-c0001-e{a.cod6}-r.json"

    def rodada(self):
        self.descobrir()
        inicio = time.time()
        alvos = [("br", self.url("br"))]
        for uf, cds in self.app.mun_por_uf.items():
            if self.ufs_filtro and uf.upper() not in self.ufs_filtro:
                continue
            alvos.append((uf, self.url(uf)))
            alvos += [(cd, self.url(uf, cd)) for cd in cds]

        def buscar(alvo):
            try:
                return alvo[0], baixar_json(alvo[1])
            except Exception as e:  # noqa: BLE001
                return alvo[0], e

        alteracoes = falhas = 0
        with ThreadPoolExecutor(max_workers=16) as pool:
            for k, res in pool.map(buscar, alvos):
                if isinstance(res, Exception):
                    falhas += 1
                    if k == "br":
                        raise res
                    continue
                alteracoes += self.app.fotos.registrar(k, time.time(), res)
        self.app.fotos.commit()
        self.estado.update(ultima=time.time(), erro=None, duracao_s=round(time.time() - inicio, 1),
                           alteracoes=alteracoes, falhas=falhas)
        print(f"[{datetime.now(BRT):%H:%M:%S}] coleta: {len(alvos)} arquivos, "
              f"{alteracoes} alterados, {falhas} falhas, {self.estado['duracao_s']}s")

    def run(self):
        while True:
            try:
                self.rodada()
            except Exception as e:  # noqa: BLE001
                self.estado["erro"] = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            time.sleep(self.intervalo)


# --------------------------------------------------------------------------- app

class App:
    def __init__(self, args):
        self.demo = args.demo
        pasta = os.path.join(RAIZ, "data", "demo") if args.demo else os.path.join(RAIZ, "data")
        os.makedirs(pasta, exist_ok=True)
        self.data_eleicao = date.fromisoformat(args.data)
        self.cod_eleicao = args.eleicao
        self.ciclo = args.ciclo
        self.caminho_mun = os.path.join(pasta, "municipios_2026.json")
        self.municipios, self.mun_por_uf = {}, {}
        if os.path.exists(self.caminho_mun):
            with open(self.caminho_mun, encoding="utf-8") as f:
                self.definir_municipios(json.load(f))
        arq_2022 = args.arquivo_2022 or os.path.join(pasta, f"linha_tempo_2022_t{args.turno}.json.gz")
        self.l22 = Linha2022(arq_2022)
        self.fotos = Fotos2026(os.path.join(pasta, "fotos_2026.sqlite"))
        self.coletor = None
        if not args.demo and not args.sem_coleta:
            self.coletor = Coletor(self, args.intervalo, {u.upper() for u in args.ufs.split(",") if u})
            self.coletor.start()

    @property
    def cod6(self):
        return str(self.cod_eleicao).zfill(6)

    @property
    def base(self):
        return f"{TSE}/{self.ciclo}/{self.cod_eleicao}"

    def definir_municipios(self, cfg):
        for abr in cfg.get("abr", []):
            uf = abr["cd"].lower()
            self.mun_por_uf[uf] = [m["cd"] for m in abr.get("mu", [])]
            for m in abr.get("mu", []):
                self.municipios[m["cd"]] = {"nm": m["nm"], "uf": uf.upper()}

    # ---- utilidades de tempo
    def minuto_agora(self):
        return epoch_para_minuto(self.data_eleicao, time.time())

    def resolver_t(self, t):
        """Converte o parâmetro t ('agora', 'final' ou 'HH:MM') em minuto do dia."""
        agora = self.minuto_agora()
        if t in (None, "", "agora"):
            return agora, True
        if t == "final":
            return 10**6, False
        h, m = (int(x) for x in t.split(":"))
        minuto = h * 60 + m + (1440 if h < 12 else 0)  # 00:00–11:59 = madrugada seguinte
        return minuto, minuto >= agora

    def nome(self, k):
        if k == "br":
            return "Brasil"
        if len(k) == 2:
            return "Exterior" if k == "zz" else k.upper()
        m = self.municipios.get(k)
        return m["nm"] if m else self.l22.nomes.get(k, k)

    def uf_de(self, k):
        m = self.municipios.get(k)
        return m["uf"] if m else self.l22.uf_de.get(k, "")

    # ---- montagem das respostas
    def linha(self, k, minuto, ao_vivo, a, b):
        r22 = self.l22.em(k, ultimo_balde_completo(minuto)) if self.l22.ok else None
        if ao_vivo:
            f = self.fotos.em(k)
        else:
            f = self.fotos.em(k, minuto_para_epoch(self.data_eleicao, minuto))
        r26 = None
        if f:
            r26 = {"secoes": f[1], "total": f[2], "vv": f[3], "a": f[5].get(a, 0), "b": f[5].get(b, 0),
                   "hora_tse": f[4], "coletado": datetime.fromtimestamp(f[0], BRT).strftime("%H:%M")}
        return {"k": k, "nm": self.nome(k), "uf": self.uf_de(k), "y22": r22, "y26": r26}

    def api_estado(self, _q):
        br = self.fotos.em("br")
        cands = []
        if br:
            tot = br[3] or 1
            for n, v in sorted(br[5].items(), key=lambda x: -x[1]):
                c = self.fotos.cands.get(n, {"n": n, "nm": n, "cc": ""})
                cands.append({**c, "v": v, "p": round(100 * v / tot, 2)})
        return {
            "demo": self.demo,
            "eleicao": {"ciclo": self.ciclo, "codigo": self.cod_eleicao, "data": self.data_eleicao.isoformat()},
            "coleta": self.coletor.estado if self.coletor else None,
            "tem_2022": self.l22.ok,
            "meta_2022": self.l22.meta,
            "agora": minuto_para_hhmm(self.minuto_agora()) if 0 <= self.minuto_agora() < 2880 else None,
            "br": None if not br else {"secoes": br[1], "total": br[2], "vv": br[3], "hora_tse": br[4],
                                       "coletado": datetime.fromtimestamp(br[0], BRT).strftime("%H:%M:%S")},
            "candidatos": cands,
            "padrao": {"a": NUM_LULA, "b": NUM_BOLSONARO},
            "ufs": sorted(set(self.mun_por_uf) | {u.lower() for u in self.l22.uf_de.values()}),
        }

    def api_comparar(self, q):
        k = q.get("k", "br").lower()
        a, b = q.get("a", NUM_LULA), q.get("b", NUM_BOLSONARO)
        minuto, ao_vivo = self.resolver_t(q.get("t"))
        if k == "br":
            filhos = self.api_estado({})["ufs"]
        elif k == "todas":
            filhos = sorted(set(self.municipios) | set(self.l22.nomes))
        else:
            filhos = sorted({cd for cd, m in self.municipios.items() if m["uf"].lower() == k}
                            | {cd for cd, uf in self.l22.uf_de.items() if uf.lower() == k})
        return {
            "t": "final" if minuto >= 10**6 else minuto_para_hhmm(min(minuto, 2879)),
            "ao_vivo": ao_vivo,
            "escopo": self.linha(k, minuto, ao_vivo, a, b) if k != "todas" else None,
            "linhas": [self.linha(f, minuto, ao_vivo, a, b) for f in filhos],
        }

    def api_serie(self, q):
        k = q.get("k", "br").lower()
        a, b = q.get("a", NUM_LULA), q.get("b", NUM_BOLSONARO)
        agora = self.minuto_agora()
        pontos = []
        for balde in range(N_BALDES + 1):
            minuto = fim_do_balde(balde)
            rot = "final" if balde == N_BALDES else minuto_para_hhmm(minuto)
            p = self.linha(k, minuto if balde < N_BALDES else 10**6, False, a, b)
            if minuto > agora + 10:  # 2026 ainda não chegou neste horário
                p["y26"] = None
            p.pop("nm"), p.pop("uf"), p.pop("k")
            pontos.append({"t": rot, **p})
        return {"k": k, "nm": self.nome(k), "uf": self.uf_de(k), "pontos": pontos}


def criar_handler(app):
    rotas = {"/api/estado": app.api_estado, "/api/comparar": app.api_comparar, "/api/serie": app.api_serie}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=os.path.join(RAIZ, "web"), **kw)

        def log_message(self, *_):
            pass

        def do_GET(self):
            u = urlparse(self.path)
            rota = rotas.get(u.path)
            if not rota:
                return super().do_GET()
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                corpo, status = json.dumps(rota(q), ensure_ascii=False).encode(), 200
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                corpo, status = json.dumps({"erro": str(e)}).encode(), 500
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", type=int, default=8026)
    ap.add_argument("--data", default="2026-10-04", help="data da eleição (AAAA-MM-DD)")
    ap.add_argument("--eleicao", help="código da eleição no TSE (padrão: descobre sozinho)")
    ap.add_argument("--ciclo", default="ele2026")
    ap.add_argument("--turno", type=int, default=1, help="turno de 2022 usado na comparação")
    ap.add_argument("--arquivo-2022", help="linha do tempo de 2022 (.json.gz)")
    ap.add_argument("--intervalo", type=int, default=180, help="segundos entre coletas no TSE")
    ap.add_argument("--ufs", default="", help="coletar só estas UFs (ex.: SP,RJ,MG)")
    ap.add_argument("--sem-coleta", action="store_true", help="não consultar o TSE (só ver o que já foi gravado)")
    ap.add_argument("--demo", action="store_true", help="usar dados fictícios de data/demo")
    args = ap.parse_args()

    if args.demo and not os.path.exists(os.path.join(RAIZ, "data", "demo", "fotos_2026.sqlite")):
        import subprocess
        import sys
        subprocess.run([sys.executable, os.path.join(RAIZ, "scripts", "gerar_demo.py")], check=True)

    app = App(args)
    if not app.l22.ok:
        print("AVISO: linha do tempo de 2022 não encontrada. Rode: python3 scripts/montar_2022.py")
    srv = ThreadingHTTPServer(("0.0.0.0", args.porta), criar_handler(app))
    print(f"Abra http://localhost:{args.porta}" + ("  (MODO DEMO — dados fictícios)" if args.demo else ""))
    srv.serve_forever()


if __name__ == "__main__":
    main()
