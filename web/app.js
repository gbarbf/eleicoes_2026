"use strict";

const UF_NOMES = {
  ac: "Acre", al: "Alagoas", am: "Amazonas", ap: "Amapá", ba: "Bahia", ce: "Ceará", df: "Distrito Federal",
  es: "Espírito Santo", go: "Goiás", ma: "Maranhão", mg: "Minas Gerais", ms: "Mato Grosso do Sul",
  mt: "Mato Grosso", pa: "Pará", pb: "Paraíba", pe: "Pernambuco", pi: "Piauí", pr: "Paraná", rj: "Rio de Janeiro",
  rn: "Rio Grande do Norte", ro: "Rondônia", rr: "Roraima", rs: "Rio Grande do Sul", sc: "Santa Catarina",
  se: "Sergipe", sp: "São Paulo", to: "Tocantins", zz: "Exterior",
};

const st = {
  estado: null, escopo: "br", hora: "agora", a: "13", b: "22", metrica: "votos",
  sel: null, dados: null, serie: null, ordem: { col: null, desc: true }, busca: "",
};
let grafico = null;

const $ = (id) => document.getElementById(id);
const nf = new Intl.NumberFormat("pt-BR");
const fmt = (v) => (v == null ? "—" : nf.format(v));
const pct = (v, d = 1) => (v == null || !isFinite(v) ? "—" : v.toFixed(d).replace(".", ",") + "%");
const sinal = (v) => (v == null ? "—" : (v > 0 ? "+" : "") + nf.format(v));
const cls = (v) => (v > 0 ? "pos" : v < 0 ? "neg" : "");
const apur = (y) => (y && y.total ? (100 * y.secoes) / y.total : null);
const pv = (y, c) => (y && y.vv ? (100 * y[c]) / y.vv : null);
const nomeEscopo = (k, nm) => (k === "br" ? "Brasil" : k.length === 2 ? UF_NOMES[k] || k.toUpperCase() : nm);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

async function api(caminho) {
  const r = await fetch(caminho, { cache: "no-store" });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).erro || r.statusText);
  return r.json();
}

function nomeCand(n) {
  const c = (st.estado?.candidatos || []).find((x) => x.n === n);
  return c ? c.nm : `nº ${n}`;
}

// ---------------------------------------------------------------- situação atual
function renderEstado() {
  const e = st.estado;
  $("aviso-demo").hidden = !e.demo;
  $("aviso-2022").hidden = e.tem_2022;
  const erro = e.coleta?.erro;
  $("aviso-erro").hidden = !erro;
  if (erro) $("aviso-erro").textContent = `Falha ao consultar o TSE: ${erro}. Tentando de novo a cada coleta.`;

  const br = e.br;
  const p = br ? (100 * br.secoes) / br.total : 0;
  $("br-apurado").textContent = br ? `· ${pct(p, 2)} das seções apuradas (${fmt(br.secoes)} de ${fmt(br.total)})` : "· aguardando dados";
  $("br-barra").style.width = `${p}%`;
  $("status").innerHTML = br
    ? `TSE: ${br.hora_tse || "—"}<br>coletado às ${br.coletado}`
    : e.coleta ? "aguardando a primeira coleta…" : "sem dados";

  const max = Math.max(1, ...e.candidatos.map((c) => c.p));
  $("candidatos").innerHTML = e.candidatos.length
    ? e.candidatos.map((c) => `
      <div class="cand ${c.n === st.a ? "a" : c.n === st.b ? "b" : ""}">
        <div class="nm" title="${c.nm}">${c.nm} <small>${c.cc || ""} · ${c.n}</small></div>
        <div class="trilho"><div style="width:${(100 * c.p) / max}%"></div></div>
        <div class="val"><b>${pct(c.p, 2)}</b> · ${fmt(c.v)}</div>
      </div>`).join("")
    : `<p class="nota">Nenhum resultado ainda. A divulgação começa às 17h (Brasília).</p>`;
}

function preencherFiltros() {
  const e = st.estado;
  $("f-escopo").innerHTML = [`<option value="br">Brasil (por estado)</option>`]
    .concat(e.ufs.map((u) => `<option value="${u}">${UF_NOMES[u] || u.toUpperCase()} (por cidade)</option>`))
    .concat([`<option value="todas">Todas as cidades do país</option>`]).join("");
  $("f-escopo").value = st.escopo;

  const horas = [`<option value="agora">Agora${e.agora ? ` (${e.agora})` : ""}</option>`];
  for (let m = 17 * 60 + 10; m <= 26 * 60; m += 10) {
    const h = `${String(Math.floor(m / 60) % 24).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
    horas.push(`<option value="${h}">${h}</option>`);
  }
  horas.push(`<option value="final">Resultado final</option>`);
  $("f-hora").innerHTML = horas.join("");
  $("f-hora").value = st.hora;

  const cands = e.candidatos.length ? e.candidatos : [{ n: "13", nm: "nº 13" }, { n: "22", nm: "nº 22" }];
  const opts = cands.map((c) => `<option value="${c.n}">${c.nm} (${c.n})</option>`).join("");
  for (const [id, v] of [["f-a", st.a], ["f-b", st.b]]) {
    const sel = $(id);
    if (sel.dataset.n !== String(cands.length)) {
      sel.innerHTML = opts;
      sel.dataset.n = String(cands.length);
    }
    sel.value = v;
  }
}

// ---------------------------------------------------------------- comparação
function blocoAno(titulo, y, nomeA, nomeB, extra = "") {
  if (!y) return `<div class="ano"><h3>${titulo}</h3><p class="nota">Sem dados para este horário.</p></div>`;
  const m = y.a - y.b;
  return `<div class="ano"><h3>${titulo}</h3>
    <div class="linha"><span>Seções apuradas</span><span>${pct(apur(y), 2)}</span></div>
    <div class="linha"><span><span class="chip lado-a"></span>${nomeA}</span><span class="grande">${fmt(y.a)}</span></div>
    <div class="linha"><span></span><span>${pct(pv(y, "a"), 2)} dos válidos</span></div>
    <div class="linha"><span><span class="chip lado-b"></span>${nomeB}</span><span class="grande">${fmt(y.b)}</span></div>
    <div class="linha"><span></span><span>${pct(pv(y, "b"), 2)} dos válidos</span></div>
    <div class="linha"><span>Vantagem do lado Lula</span><span class="${cls(m)}">${sinal(m)}</span></div>
    ${extra}</div>`;
}

function renderComparacao() {
  const d = st.dados;
  const e = d.escopo;
  const nm = st.escopo === "todas" ? "Todas as cidades" : nomeEscopo(st.escopo, e?.nm);
  $("titulo-comp").textContent = `${nm} · ${d.ao_vivo && st.hora === "agora" ? `agora (${d.t})` : d.t === "final" ? "resultado final" : `às ${d.t}`}`;
  $("nota-comp").textContent = st.hora !== "agora" && d.ao_vivo
    ? "Esse horário ainda não chegou em 2026: mostrando o dado mais recente de 2026."
    : `2022 mostra o acumulado até o mesmo horário na noite de 02/10/2022.`;
  if (!e) { $("comparacao").innerHTML = ""; return; }
  const y22 = e.y22, y26 = e.y26;
  let dif = "";
  if (y22 && y26) {
    const da = y26.a - y22.a, db = y26.b - y22.b;
    dif = `<div class="ano"><h3>2026 − 2022 no mesmo horário</h3>
      <div class="linha"><span>Seções apuradas</span><span class="${cls(apur(y26) - apur(y22))}">${sinal(+(apur(y26) - apur(y22)).toFixed(1))} p.p.</span></div>
      <div class="linha"><span><span class="chip lado-a"></span>Lado Lula</span><span class="grande ${cls(da)}">${sinal(da)}</span></div>
      <div class="linha"><span></span><span>${sinal(+(pv(y26, "a") - pv(y22, "a")).toFixed(2))} p.p. dos válidos</span></div>
      <div class="linha"><span><span class="chip lado-b"></span>Lado Bolsonaro</span><span class="grande ${cls(db)}">${sinal(db)}</span></div>
      <div class="linha"><span></span><span>${sinal(+(pv(y26, "b") - pv(y22, "b")).toFixed(2))} p.p. dos válidos</span></div>
      <div class="linha"><span>Variação da vantagem</span><span class="${cls(da - db)}">${sinal(da - db)}</span></div>
    </div>`;
  }
  $("comparacao").innerHTML =
    blocoAno("2022", y22, "Lula", "Bolsonaro") +
    blocoAno("2026" + (y26?.coletado ? ` · coletado ${y26.coletado}` : ""), y26, nomeCand(st.a), nomeCand(st.b)) + dif;
}

// ---------------------------------------------------------------- gráfico
function valor(y, campo) {
  if (!y) return null;
  if (st.metrica === "votos") return y[campo];
  if (st.metrica === "pct") return pv(y, campo);
  return apur(y);
}

function renderGrafico() {
  const s = st.serie;
  if (!s) return;
  const nm = nomeEscopo(s.k, s.nm) + (s.uf && s.k.length > 2 ? ` (${s.uf})` : "");
  $("titulo-graf").textContent = `Hora a hora · ${nm}`;
  const cA = css("--lado-a"), cB = css("--lado-b");
  const labels = s.pontos.map((p) => (p.t === "final" ? "final" : p.t));
  const linhas = st.metrica === "apur"
    ? [
        { nome: "2022", cor: css("--muted"), tr: true, dados: s.pontos.map((p) => valor(p.y22)) },
        { nome: "2026", cor: css("--text"), tr: false, dados: s.pontos.map((p) => valor(p.y26)) },
      ]
    : [
        { nome: "Lula 2022", cor: cA, tr: true, dados: s.pontos.map((p) => valor(p.y22, "a")) },
        { nome: "Bolsonaro 2022", cor: cB, tr: true, dados: s.pontos.map((p) => valor(p.y22, "b")) },
        { nome: `${nomeCand(st.a)} 2026`, cor: cA, tr: false, dados: s.pontos.map((p) => valor(p.y26, "a")) },
        { nome: `${nomeCand(st.b)} 2026`, cor: cB, tr: false, dados: s.pontos.map((p) => valor(p.y26, "b")) },
      ];
  $("legenda").innerHTML = linhas
    .map((l) => `<span><i class="${l.tr ? "tr" : ""}" style="border-color:${l.cor}"></i>${l.nome}</span>`).join("");

  const fmtY = (v) => (st.metrica === "votos" ? fmt(Math.round(v)) : pct(v, 1));
  const datasets = linhas.map((l) => ({
    label: l.nome, data: l.dados, borderColor: l.cor, backgroundColor: l.cor, borderWidth: 2,
    borderDash: l.tr ? [6, 4] : [], pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 2,
    pointHoverBorderColor: css("--surface"), tension: 0.2, spanGaps: false,
  }));
  const opcoes = {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${c.raw == null ? "—" : fmtY(c.raw)}` } },
    },
    scales: {
      x: { grid: { display: false }, ticks: { color: css("--text-2"), maxRotation: 0, autoSkipPadding: 14 } },
      y: {
        beginAtZero: true, grid: { color: css("--grid") }, border: { display: false },
        ticks: { color: css("--text-2"), callback: (v) => (st.metrica === "votos" ? new Intl.NumberFormat("pt-BR", { notation: "compact" }).format(v) : v + "%") },
        ...(st.metrica === "apur" ? { max: 100 } : {}),
      },
    },
  };
  if (grafico) grafico.destroy();
  grafico = new Chart($("grafico"), { type: "line", data: { labels, datasets }, options: opcoes });
}

// ---------------------------------------------------------------- tabela
const COLUNAS = [
  { t: "Local", f: (r) => r.nm, txt: true },
  { t: "% apur.", g: "22", f: (r) => apur(r.y22), r: (v) => pct(v) },
  { t: "Lula", g: "22", f: (r) => r.y22?.a },
  { t: "Bolsonaro", g: "22", f: (r) => r.y22?.b },
  { t: "% apur.", g: "26", f: (r) => apur(r.y26), r: (v) => pct(v) },
  { t: "Lado Lula", g: "26", f: (r) => r.y26?.a },
  { t: "Lado Bolso.", g: "26", f: (r) => r.y26?.b },
  { t: "Δ Lula", g: "d", f: (r) => (r.y22 && r.y26 ? r.y26.a - r.y22.a : null), r: sinal, c: true },
  { t: "Δ Bolso.", g: "d", f: (r) => (r.y22 && r.y26 ? r.y26.b - r.y22.b : null), r: sinal, c: true },
  { t: "Δ vantagem", g: "d", f: (r) => (r.y22 && r.y26 ? (r.y26.a - r.y26.b) - (r.y22.a - r.y22.b) : null), r: sinal, c: true },
];

function renderTabela() {
  const filhosSaoUfs = st.escopo === "br";
  $("titulo-tab").textContent = filhosSaoUfs ? "Estado a estado" : "Cidade a cidade";
  $("tabela").querySelector("thead").innerHTML =
    `<tr class="grupo"><th></th><th colspan="3">2022 (mesmo horário)</th><th colspan="3">2026</th><th colspan="3">2026 − 2022</th></tr>` +
    `<tr>${COLUNAS.map((c, i) => `<th data-i="${i}">${c.t}${st.ordem.col === i ? (st.ordem.desc ? " ▾" : " ▴") : ""}</th>`).join("")}</tr>`;

  let linhas = st.dados.linhas.map((r) => ({ ...r, nm: filhosSaoUfs ? nomeEscopo(r.k) : r.nm + (st.escopo === "todas" ? ` (${r.uf})` : "") }));
  const q = st.busca.trim().toLowerCase().normalize("NFD").replace(/\p{Diacritic}/gu, "");
  if (q) linhas = linhas.filter((r) => r.nm.toLowerCase().normalize("NFD").replace(/\p{Diacritic}/gu, "").includes(q));
  const col = COLUNAS[st.ordem.col ?? 2];
  const desc = st.ordem.col == null ? true : st.ordem.desc;
  linhas.sort((x, y) => {
    const a = col.f(x), b = col.f(y);
    if (a == null) return 1;
    if (b == null) return -1;
    const r = col.txt ? String(a).localeCompare(String(b), "pt-BR") : a - b;
    return desc ? -r : r;
  });
  const MAX = 1500;
  $("tabela").querySelector("tbody").innerHTML = linhas.slice(0, MAX).map((r) => `
    <tr data-k="${r.k}" class="${st.sel === r.k ? "sel" : ""}">${COLUNAS.map((c) => {
      const v = c.f(r);
      return `<td class="${c.c ? cls(v) : ""}">${c.txt ? v : (c.r || fmt)(v)}</td>`;
    }).join("")}</tr>`).join("") +
    (linhas.length > MAX ? `<tr><td colspan="${COLUNAS.length}">… mais ${fmt(linhas.length - MAX)} linhas — use a busca.</td></tr>` : "");
}

// ---------------------------------------------------------------- carga
async function carregarEstado() {
  st.estado = await api("/api/estado");
  preencherFiltros();
  renderEstado();
}

async function carregarComparacao() {
  const qs = `t=${encodeURIComponent(st.hora)}&a=${st.a}&b=${st.b}`;
  st.dados = await api(`/api/comparar?k=${st.escopo}&${qs}`);
  renderComparacao();
  renderTabela();
}

async function carregarSerie() {
  const k = st.sel || (st.escopo === "todas" ? "br" : st.escopo);
  st.serie = await api(`/api/serie?k=${k}&a=${st.a}&b=${st.b}`);
  renderGrafico();
}

async function tudo() {
  try {
    await carregarEstado();
    await Promise.all([carregarComparacao(), carregarSerie()]);
  } catch (err) {
    $("aviso-erro").hidden = false;
    $("aviso-erro").textContent = `Erro ao falar com o servidor local: ${err.message}`;
  }
}

$("f-escopo").onchange = (e) => { st.escopo = e.target.value; st.sel = null; st.busca = ""; $("f-busca").value = ""; tudo(); };
$("f-hora").onchange = (e) => { st.hora = e.target.value; carregarComparacao(); };
$("f-a").onchange = (e) => { st.a = e.target.value; renderEstado(); carregarComparacao(); carregarSerie(); };
$("f-b").onchange = (e) => { st.b = e.target.value; renderEstado(); carregarComparacao(); carregarSerie(); };
$("f-busca").oninput = (e) => { st.busca = e.target.value; renderTabela(); };
$("f-metrica").onclick = (e) => {
  const m = e.target.dataset?.m;
  if (!m) return;
  st.metrica = m;
  for (const b of $("f-metrica").children) b.classList.toggle("ativo", b.dataset.m === m);
  renderGrafico();
};
$("tabela").onclick = (e) => {
  const th = e.target.closest("th[data-i]");
  if (th) {
    const i = +th.dataset.i;
    st.ordem = { col: i, desc: st.ordem.col === i ? !st.ordem.desc : !COLUNAS[i].txt };
    return renderTabela();
  }
  const tr = e.target.closest("tr[data-k]");
  if (!tr) return;
  if (st.escopo === "br" && st.sel === tr.dataset.k) {  // 2º clique num estado: abre as cidades
    st.escopo = tr.dataset.k; st.sel = null; $("f-escopo").value = st.escopo; return tudo();
  }
  st.sel = tr.dataset.k;
  renderTabela();
  carregarSerie();
};
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderGrafico);

tudo();
setInterval(tudo, 60_000);
