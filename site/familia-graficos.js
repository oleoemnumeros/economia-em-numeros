/* Família em Números: gráficos com linha ao tocar (ou passar o mouse), valor em balão e filtro de período.
 *
 * Uso: <div class="fam-gr" data-fam-gr='{...}'>SVG de reserva</div>
 * O JavaScript troca o conteúdo da div pelo gráfico interativo; sem JavaScript, o SVG de reserva continua lá.
 *
 * Configuração (JSON):
 *   t  "l" linha | "b" barras (agrupadas se houver mais de uma série) | "d" degraus (valor vale até o próximo ponto)
 *   p  períodos: "AAAA-MM", "AAAA-MM-DD", "AAAA-T1" ou "AAAA" (com datas aparecem os botões 1/3/5 anos/Total)
 *   l  rótulos do eixo x e do balão, um por período (opcional; sem ele saem dos períodos)
 *   s  séries: [{n: nome, v: [valores ou null], c: cor CSS, d: 1 se tracejada, cs: cores por ponto (barras), cn: cor dos negativos}]
 *   d  casas decimais do valor mostrado (padrão 2) · pre / suf: prefixo e sufixo do valor ("US$ ", "%")
 *   u  unidade, escrita no alto do eixo vertical · z 1 força o zero no eixo · lg 1 mostra a legenda das séries
 *   a  descrição para leitores de tela · w 0 desliga o filtro de período · ate  fim dos degraus ("AAAA-MM-DD")
 */
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var MES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  var CHAVE = "fam-periodo";
  var JANELAS = [[1, "1 ano"], [3, "3 anos"], [5, "5 anos"]];
  var graficos = [];

  function svg(tag, attrs, pai) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) if (attrs[k] != null) e.setAttribute(k, attrs[k]);
    if (pai) pai.appendChild(e);
    return e;
  }
  function no(tag, cls, pai, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt != null) e.textContent = txt;
    if (pai) pai.appendChild(e);
    return e;
  }
  function nf(v, d) {
    return v.toLocaleString("pt-BR", { minimumFractionDigits: d, maximumFractionDigits: d }).replace("-", "−");
  }
  function guardar(k, v) { try { if (v == null) return localStorage.getItem(k); localStorage.setItem(k, v); } catch (e) {} return null; }

  // ---------- períodos ----------
  function periodo(p, i) {
    var m, y, mo;
    if ((m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(p))) {
      y = +m[1]; mo = +m[2];
      return { t: y + (mo - 1) / 12 + (+m[3] - 1) / 372, c: MES[mo - 1] + "/" + m[1].slice(2), l: m[3] + "/" + m[2] + "/" + m[1], tempo: true };
    }
    if ((m = /^(\d{4})-(\d{2})$/.exec(p))) {
      y = +m[1]; mo = +m[2];
      return { t: y + (mo - 1) / 12, c: MES[mo - 1] + "/" + m[1].slice(2), l: MES[mo - 1] + "/" + m[1], tempo: true };
    }
    if ((m = /^(\d{4})-T([1-4])$/.exec(p))) {
      return { t: +m[1] + (+m[2] - 1) / 4, c: m[2] + "T" + m[1].slice(2), l: m[2] + "º tri/" + m[1], tempo: true };
    }
    if (/^\d{4}$/.test(p)) return { t: +p, c: p, l: p, tempo: true };
    // formatos por extenso usados nos portais: "2º trimestre de 2023" e "ago-out/2023" (trimestre móvel: vale o mês final)
    if ((m = /^([1-4])º trimestre de (\d{4})$/.exec(p))) return { t: +m[2] + (+m[1] - 1) / 4, c: m[1] + "T" + m[2].slice(2), l: p, tempo: true };
    if ((m = /^([a-zç]{3})-([a-zç]{3})\/(\d{4})$/.exec(p)) && MES.indexOf(m[2]) >= 0) {
      mo = MES.indexOf(m[2]) + 1; y = +m[3];
      return { t: y + (mo - 1) / 12, c: m[2] + "/" + m[3].slice(2), l: p, tempo: true };
    }
    return { t: i, c: p, l: p, tempo: false };
  }

  // ---------- eixo vertical ----------
  function eixo(min, max, zero) {
    if (zero) { min = Math.min(min, 0); max = Math.max(max, 0); }
    if (!(max > min)) { max = min + 1; if (!zero) min -= 1; }
    var bruto = (max - min) / 4, p10 = Math.pow(10, Math.floor(Math.log10(bruto))), passo = p10, f = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < f.length; i++) { passo = f[i] * p10; if (passo >= bruto - 1e-12) break; }
    var lo = Math.floor(min / passo + 1e-9) * passo, hi = Math.ceil(max / passo - 1e-9) * passo, marcas = [];
    for (var v = lo; v <= hi + passo / 2; v += passo) marcas.push(+v.toFixed(10));
    var casas = 0;
    while (casas < 6 && Math.abs(passo * Math.pow(10, casas) - Math.round(passo * Math.pow(10, casas))) > 1e-7) casas++;
    return { lo: lo, hi: hi, marcas: marcas, casas: casas };
  }

  // ---------- um gráfico ----------
  function montar(raiz) {
    var cfg;
    try { cfg = JSON.parse(raiz.getAttribute("data-fam-gr")); } catch (e) { return; }
    if (!cfg || !cfg.p || !cfg.s || !cfg.s.length || cfg.p.length < 2) return;
    var tipo = cfg.t || "l", n = cfg.p.length, pts = [], temporal = true, i;
    for (i = 0; i < n; i++) {
      var q = periodo(String(cfg.p[i]), i);
      if (cfg.l && cfg.l[i] != null) { q.c = cfg.l[i]; q.l = (cfg.ll && cfg.ll[i] != null) ? cfg.ll[i] : cfg.l[i]; }
      if (!q.tempo) temporal = false;
      pts.push(q);
    }
    var casas = cfg.d == null ? 2 : cfg.d, pre = cfg.pre || "", suf = cfg.suf || "";
    var st = { win: null, sel: null, w: 0 };

    raiz.textContent = "";
    raiz.classList.add("fam-gr-on");
    var ctl = no("div", "fam-gr-ctl", raiz);
    ctl.setAttribute("role", "group");
    ctl.setAttribute("aria-label", "Período do gráfico");
    var area = no("div", "fam-gr-area", raiz);
    var tip = no("div", "fam-gr-tip", area);
    tip.hidden = true;
    var leg = null;
    if (cfg.lg && cfg.s.length > 1) {
      leg = no("div", "fam-gr-leg", raiz);
      cfg.s.forEach(function (s) {
        var it = no("span", "", leg);
        no("i", "", it).style.background = s.c;
        it.appendChild(document.createTextNode(s.n || ""));
      });
    }
    var sr = no("p", "fam-sr", raiz);
    sr.setAttribute("aria-live", "polite");

    // janelas disponíveis: só as menores que a série
    var tfim = (tipo === "d" && cfg.ate) ? periodo(cfg.ate, 0).t : pts[n - 1].t, disp = [];
    if (temporal && cfg.w !== 0) {
      // só entra a janela que mostra pelo menos 5 pontos e é menor que a série (barras anuais não têm "1 ano")
      JANELAS.forEach(function (j) {
        var dentro = 0;
        pts.forEach(function (q) { if (q.t >= tfim - j[0] - 1e-9) dentro++; });
        if (dentro < n && (dentro >= 5 || tipo === "d")) disp.push(j);
      });
    }
    var botoes = {};
    if (disp.length) {
      disp.concat([[0, "Total"]]).forEach(function (j) {
        var b = no("button", "", ctl, j[1]);
        b.type = "button";
        b.setAttribute("data-w", String(j[0]));
        b.addEventListener("click", function () { guardar(CHAVE, String(j[0])); graficos.forEach(function (g) { g.aplicar(String(j[0])); }); });
        botoes[j[0]] = b;
      });
    } else ctl.hidden = true;

    var vista = [], geom = {}, sombra = null, vl = null, dots = [], gSvg = null;

    function calcular() {
      var ini = 0, inicio = null;
      if (st.win) {
        var corte = tfim - st.win - 1e-9;
        while (ini < n - 1 && pts[ini].t < corte) ini++;
        if (tipo === "d" && ini > 0 && pts[ini].t > corte + 2e-9) { ini--; inicio = corte + 1e-9; }
      }
      vista = [];
      for (i = ini; i < n; i++) vista.push({ i: i, x: tipo === "b" || !temporal ? vista.length : pts[i].t });
      if (inicio != null) vista[0].x = inicio;
    }

    function desenhar() {
      var W = Math.round(raiz.clientWidth);
      if (W < 120) return;
      st.w = W;
      var H = W < 480 ? 230 : 280, barras = tipo === "b", i, k;
      if (gSvg) gSvg.remove();
      var vmin = Infinity, vmax = -Infinity;
      cfg.s.forEach(function (s) { vista.forEach(function (p) { var v = s.v[p.i]; if (v != null) { vmin = Math.min(vmin, v); vmax = Math.max(vmax, v); } }); });
      if (vmin === Infinity) { vmin = 0; vmax = 1; }
      var E = eixo(vmin, vmax, barras ? cfg.z !== 0 : (cfg.z && !st.win)), maxlab = 0;
      E.marcas.forEach(function (m) { maxlab = Math.max(maxlab, nf(m, E.casas).length); });
      var PL = Math.max(30, maxlab * 6.6 + 12), PR = 12, PT = cfg.u ? 24 : 10, PB = 26, iw = W - PL - PR, ih = H - PT - PB;
      var y = function (v) { return PT + ih * (1 - (v - E.lo) / (E.hi - E.lo)); };
      var x0 = vista[0].x, x1 = vista[vista.length - 1].x;
      if (tipo === "d" && cfg.ate) { x1 = periodo(cfg.ate, 0).t; }
      var nv = vista.length, passoB = iw / nv;
      var x = function (xv) { return barras ? PL + passoB * (xv + 0.5) : PL + (x1 > x0 ? (xv - x0) / (x1 - x0) * iw : iw / 2); };

      var s_ = svg("svg", { viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": cfg.a || "Gráfico", tabindex: "0", focusable: "true" });
      gSvg = s_;
      area.insertBefore(s_, tip);
      var txt = function (t, ax, ay, anc) { var e = svg("text", { x: ax, y: ay, "text-anchor": anc || "start", "font-size": 11, "class": "fam-gr-t" }, s_); e.textContent = t; return e; };
      if (cfg.u) txt(cfg.u, 2, 12);
      E.marcas.forEach(function (m) {
        var neg0 = Math.abs(m) < 1e-9 && E.lo < 0;
        svg("line", { x1: PL, x2: W - PR, y1: y(m).toFixed(1), y2: y(m).toFixed(1), "class": "fam-gr-g" + (neg0 ? " zero" : "") }, s_);
        txt(nf(m, E.casas), PL - 6, y(m) + 4, "end");
      });
      // eixo x
      var base = H - 8, usados = [];
      if (barras || !temporal) {
        var cab = Math.max(1, Math.floor(iw / 40)), passo = Math.ceil(nv / cab);
        for (k = nv - 1; k >= 0; k -= passo) usados.push(k);
        usados.forEach(function (kk) { txt(pts[vista[kk].i].c, x(vista[kk].x), base, "middle"); });
      } else {
        var m = Math.max(2, Math.min(7, Math.floor(iw / 70)));
        for (k = 0; k < m; k++) {
          var idx = Math.round(k * (nv - 1) / (m - 1)), rot = pts[vista[idx].i].c;
          if (tipo === "d") { var tt = x0 + (x1 - x0) * k / (m - 1); rot = (x1 - x0) > 4 ? String(Math.round(tt)) : MES[Math.min(11, Math.floor((tt % 1) * 12))] + "/" + String(Math.floor(tt)).slice(2); idx = null;
            txt(rot, PL + iw * k / (m - 1), base, k === 0 ? "start" : k === m - 1 ? "end" : "middle"); }
          else txt(rot, x(vista[idx].x), base, k === 0 ? "start" : k === m - 1 ? "end" : "middle");
        }
      }
      sombra = barras ? svg("rect", { y: PT, height: ih, width: passoB, "class": "fam-gr-banda", visibility: "hidden" }, s_) : null;

      // séries
      cfg.s.forEach(function (s, si) {
        var cor = s.c || "var(--fam-cor)";
        if (barras) {
          var ns = cfg.s.length, larg = passoB * 0.72 / ns, g0 = passoB * 0.14;
          vista.forEach(function (p, kk) {
            var v = s.v[p.i]; if (v == null) return;
            var c = (s.cs && s.cs[p.i]) || (v < 0 && s.cn) || cor, z0 = Math.max(E.lo, Math.min(E.hi, 0)), ya = y(Math.max(v, z0)), yb = y(Math.min(v, z0));
            svg("rect", { x: (PL + passoB * kk + g0 + larg * si).toFixed(1), y: ya.toFixed(1), width: Math.max(1, larg - (ns > 1 ? 1 : 0)).toFixed(1),
              height: Math.max(1, yb - ya).toFixed(1), rx: 2, style: "fill:" + c, "class": "fam-gr-b", "data-k": kk,
              opacity: s.op ? s.op[p.i] : (cfg.hl === 0 || kk === nv - 1) ? 1 : 0.62 }, s_);
            // valor em cima da barra, quando há espaço (cfg.vl: 1)
            if (cfg.vl && ns === 1 && passoB >= 26) txt(nf(v, cfg.vd || 0) + suf, +(PL + passoB * kk + passoB / 2).toFixed(1), (v < 0 ? yb + 13 : ya - 5).toFixed(1), "middle");
          });
          return;
        }
        var d = "", seg = [], fim = null;
        function fecha() {
          if (seg.length > 1 && cfg.s.length === 1 && tipo === "l") svg("path", { d: "M" + seg[0][0] + " " + (H - PB) + "L" + seg.map(function (a) { return a[0] + " " + a[1]; }).join("L") + "L" + seg[seg.length - 1][0] + " " + (H - PB) + "Z", style: "fill:" + cor, opacity: 0.12 }, s_);
          if (seg.length > 1) svg("path", { d: "M" + seg.map(function (a) { return a[0] + " " + a[1]; }).join("L"), fill: "none", style: "stroke:" + cor, "stroke-width": 2.4, "stroke-linejoin": "round", "stroke-dasharray": s.d ? "5 4" : null }, s_);
          seg = [];
        }
        vista.forEach(function (p, kk) {
          var v = s.v[p.i];
          if (v == null) { fecha(); return; }
          var px = +x(p.x).toFixed(1), py = +y(v).toFixed(1);
          if (tipo === "d" && seg.length) seg.push([px, seg[seg.length - 1][1]]);
          seg.push([px, py]);
          fim = [px, py];
        });
        if (tipo === "d" && seg.length) seg.push([+x(x1).toFixed(1), seg[seg.length - 1][1]]);
        fecha();
        if (fim) svg("circle", { cx: tipo === "d" ? x(x1).toFixed(1) : fim[0], cy: fim[1], r: 4.2, style: "fill:" + cor }, s_);
      });

      // cursor
      vl = barras ? null : svg("line", { y1: PT, y2: PT + ih, "class": "fam-gr-cur", visibility: "hidden" }, s_);
      dots = barras ? [] : cfg.s.map(function (s) { return svg("circle", { r: 5, style: "fill:" + (s.c || "var(--fam-cor)"), "class": "fam-gr-dot", visibility: "hidden" }, s_); });
      geom = { PL: PL, PT: PT, iw: iw, ih: ih, W: W, y: y, x: x, passoB: passoB };
      if (st.sel != null) marcar(st.sel, true);

      function alvo(ev) {
        var r = s_.getBoundingClientRect(), px = (ev.clientX - r.left) * (W / r.width);
        if (barras) return Math.max(0, Math.min(nv - 1, Math.floor((px - PL) / passoB)));
        var melhor = 0, dist = Infinity;
        for (var j = 0; j < nv; j++) { var dd = Math.abs(x(vista[j].x) - px); if (dd < dist) { dist = dd; melhor = j; } }
        return melhor;
      }
      s_.addEventListener("pointermove", function (ev) { if (ev.pointerType === "mouse" || ev.buttons || ev.pointerType === "touch" || ev.pointerType === "pen") marcar(alvo(ev)); });
      s_.addEventListener("pointerdown", function (ev) { raiz.classList.remove("teclado"); marcar(alvo(ev)); });
      s_.addEventListener("pointerleave", function (ev) { if (ev.pointerType === "mouse") limpar(); });
      s_.addEventListener("keydown", function (ev) {
        raiz.classList.add("teclado");
        var k0 = st.sel == null ? nv - 1 : st.sel;
        if (ev.key === "ArrowLeft") k0 = Math.max(0, k0 - 1);
        else if (ev.key === "ArrowRight") k0 = Math.min(nv - 1, k0 + 1);
        else if (ev.key === "Home") k0 = 0;
        else if (ev.key === "End") k0 = nv - 1;
        else if (ev.key === "Escape") { limpar(); return; }
        else return;
        ev.preventDefault();
        marcar(k0);
      });
    }

    function valor(v) { return v == null ? "–" : (v < 0 ? "\u2212" : "") + pre + nf(Math.abs(v), casas).replace("\u2212", "") + suf; }

    function marcar(k, silencio) {
      if (!vista[k]) return;
      st.sel = k;
      var p = vista[k], g = geom, px = g.x(p.x), linhas = [];
      if (sombra) { sombra.setAttribute("x", (g.PL + g.passoB * k).toFixed(1)); sombra.setAttribute("visibility", "visible"); }
      if (vl) { vl.setAttribute("x1", px.toFixed(1)); vl.setAttribute("x2", px.toFixed(1)); vl.setAttribute("visibility", "visible"); }
      cfg.s.forEach(function (s, si) {
        var v = s.v[p.i];
        if (dots[si]) {
          if (v == null) dots[si].setAttribute("visibility", "hidden");
          else { dots[si].setAttribute("cx", px.toFixed(1)); dots[si].setAttribute("cy", g.y(v).toFixed(1)); dots[si].setAttribute("visibility", "visible"); }
        }
        linhas.push({ n: s.n, c: s.cs && s.cs[p.i] || (v != null && v < 0 && s.cn) || s.c, v: valor(v) });
      });
      (cfg.x || []).forEach(function (s) { linhas.push({ n: s.n, c: null, v: valor(s.v[p.i]), extra: true }); });
      tip.textContent = "";
      no("b", "", tip, (tipo === "d" ? "Desde " : "") + pts[p.i].l);
      linhas.forEach(function (l) {
        var r = no("span", "fam-gr-lin", tip);
        if (cfg.s.length > 1 && l.c) no("i", "", r).style.background = l.c;
        r.appendChild(document.createTextNode(((cfg.s.length > 1 || l.extra) && l.n ? l.n + ": " : "") + l.v));
      });
      tip.hidden = false;
      var w = tip.offsetWidth, esq = px + 12;
      if (esq + w > g.W - 4) esq = px - w - 12;
      tip.style.left = Math.max(2, esq).toFixed(0) + "px";
      tip.style.top = (g.PT + 4) + "px";
      if (!silencio) sr.textContent = (tipo === "d" ? "Desde " : "") + pts[p.i].l + ": " + linhas.map(function (l) { return ((cfg.s.length > 1 || l.extra) && l.n ? l.n + " " : "") + l.v; }).join("; ");
    }

    function limpar() {
      st.sel = null;
      tip.hidden = true;
      if (sombra) sombra.setAttribute("visibility", "hidden");
      if (vl) vl.setAttribute("visibility", "hidden");
      dots.forEach(function (d) { d.setAttribute("visibility", "hidden"); });
    }

    st.aplicar = function (chave) {
      var w = +chave || 0;
      if (w && !disp.some(function (j) { return j[0] === w; })) w = 0;
      st.win = w || null;
      for (var b in botoes) botoes[b].setAttribute("aria-pressed", String(+b === w));
      st.sel = null;
      calcular();
      desenhar();
    };
    st.limpar = limpar;
    st.raiz = raiz;
    graficos.push(st);
    st.aplicar(guardar(CHAVE) || "0");

    var ultimaLargura = raiz.clientWidth, agenda = 0;
    function redimensionar() {
      if (agenda) return;
      agenda = requestAnimationFrame(function () {
        agenda = 0;
        var w = Math.round(raiz.clientWidth);
        if (w !== ultimaLargura && w >= 120) { ultimaLargura = w; desenhar(); }
        else if (!gSvg && w >= 120) desenhar();
      });
    }
    if (window.ResizeObserver) new ResizeObserver(redimensionar).observe(raiz);
    else window.addEventListener("resize", redimensionar);
  }

  function iniciar() {
    Array.prototype.forEach.call(document.querySelectorAll(".fam-gr[data-fam-gr]"), function (r) { if (!r.classList.contains("fam-gr-on")) montar(r); });
  }
  // toque fora do gráfico apaga a seleção
  document.addEventListener("pointerdown", function (ev) {
    graficos.forEach(function (g) { if (g.sel != null && !g.raiz.contains(ev.target)) g.limpar(); });
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", iniciar); else iniciar();
  window.famGraficos = { iniciar: iniciar };
})();
