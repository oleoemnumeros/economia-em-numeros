/* Calculadora de reajuste de aluguel: roda no navegador, com os índices mensais embutidos em #dados-aluguel:
   {"series":{"igpm":[["2000-01",1.24],...],...}, "nomes":{"igpm":"IGP-M",...}, "aniv":"aaaa-mm"} */
(function () {
  "use strict";
  var el = document.getElementById("dados-aluguel");
  if (!el) return;
  var D = JSON.parse(el.textContent), S = {}, k;
  for (k in D.series) { S[k] = {}; D.series[k].forEach(function (x) { S[k][x[0]] = x[1]; }); }
  var MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];
  function nome(p) { return MESES[parseInt(p.slice(5), 10) - 1] + " de " + p.slice(0, 4); }
  function mais(p, n) { var t = parseInt(p.slice(0, 4), 10) * 12 + parseInt(p.slice(5), 10) - 1 + n; var m = t % 12 + 1; return Math.floor(t / 12) + "-" + (m < 10 ? "0" : "") + m; }
  function acum(m, ate) { var f = 1; for (var i = 0; i < 12; i++) { var x = mais(ate, -i); if (!(x in m)) return null; f *= 1 + m[x] / 100; } return (f - 1) * 100; }
  function ultimo(m) { return Object.keys(m).sort().pop(); }
  function numero(t) { t = String(t).replace(/[^\d,.-]/g, ""); if (t.indexOf(",") >= 0) t = t.replace(/\./g, "").replace(",", "."); var n = parseFloat(t); return isFinite(n) ? n : NaN; }
  var moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  var pc = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  function sinal(v) { return (v > 0 ? "+" : v < 0 ? "−" : "") + pc.format(Math.abs(v)) + "%"; }

  var valor = document.getElementById("al-valor"), indice = document.getElementById("al-indice"), mes = document.getElementById("al-mes"),
      defas = document.getElementById("al-defas"), res = document.getElementById("al-res"), btn = document.getElementById("al-calc");
  if (!valor || !indice || !mes || !res) return;

  // meses de reajuste: do próximo aniversário possível (último índice + 2) até 2001
  var fimLista = mais(D.aniv, 1), p = fimLista;
  while (p >= "2001-02") {
    var o = document.createElement("option"); o.value = p; o.textContent = nome(p).replace(/^./, function (c) { return c.toUpperCase(); });
    mes.appendChild(o); p = mais(p, -1);
  }
  var q = new URLSearchParams(location.search);
  mes.value = q.get("mes") && /^\d{4}-\d{2}$/.test(q.get("mes")) ? q.get("mes") : D.aniv;
  if (!mes.value) mes.value = D.aniv;
  if (q.get("indice") && S[q.get("indice")]) indice.value = q.get("indice");
  if (q.get("valor")) valor.value = pc.format(numero(q.get("valor")) || 0);

  function span(cls, txt) { var s = document.createElement("span"); s.className = cls; s.textContent = txt; return s; }
  function calcular() {
    while (res.firstChild) res.removeChild(res.firstChild);
    var v = numero(valor.value), ind = indice.value, m = S[ind], a = mes.value, ate = mais(a, -parseInt(defas.value, 10));
    if (!(v > 0)) { res.appendChild(span("small", "Digite o valor do aluguel.")); return; }
    var r = acum(m, ate), previa = false, u = ultimo(m);
    if (r === null && ate > u) { r = acum(m, u); previa = true; }
    if (r === null) { res.appendChild(span("small", "Não há dados do " + D.nomes[ind] + " para esse período.")); return; }
    var novo = v * (1 + r / 100);
    res.appendChild(span("big", moeda.format(novo)));
    res.appendChild(span("", "Novo aluguel a partir de " + nome(a) + ": reajuste de " + sinal(r) + " (" + D.nomes[ind] + " em 12 meses até " + nome(previa ? u : ate) + ")."));
    var dif = novo - v;
    res.appendChild(span("small", (dif >= 0 ? "São " + moeda.format(dif) + " a mais por mês, " + moeda.format(dif * 12) + " no ano."
                                           : "São " + moeda.format(-dif) + " a menos por mês. Confira o contrato: alguns mantêm o valor quando o índice fica negativo.")));
    if (previa) res.appendChild(span("small", "O " + D.nomes[ind] + " de " + nome(ate) + " ainda não saiu. O número acima é uma prévia, com os 12 meses mais recentes."));
    var outros = [];
    for (var j in S) { if (j === ind) continue; var x = acum(S[j], previa ? ultimo(S[j]) : ate); if (x !== null) outros.push(D.nomes[j] + " " + sinal(x) + " (" + moeda.format(v * (1 + x / 100)) + ")"); }
    if (outros.length) res.appendChild(span("small", "Pelos outros índices: " + outros.join(" · ") + "."));
    if (window.goatcounter && window.goatcounter.count) try { window.goatcounter.count({ path: "aluguel-calculou-" + ind, event: true }); } catch (e) {}
  }
  btn.addEventListener("click", calcular);
  [indice, mes, defas].forEach(function (s) { s.addEventListener("change", calcular); });
  valor.addEventListener("keydown", function (e) { if (e.key === "Enter") calcular(); });
  calcular();
})();
