/* Calculadora de correção monetária (IPCA/IGP-M/INPC) e de rendimento bruto no CDI: tudo roda no navegador,
   com os índices mensais embutidos na página em #dados-calc: {"ipca":[["2000-01",0.62],...], "igpm":[...], "inpc":[...], "cdi":[...]}. */
(function () {
  "use strict";
  var el = document.getElementById("dados-calc");
  if (!el) return;
  var SERIES = JSON.parse(el.textContent); // cada uma: [[ "aaaa-mm", valor em % ao mês ], ...], em ordem
  var MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  function rotulo(p) { return MESES[parseInt(p.slice(5), 10) - 1] + "/" + p.slice(0, 4); }

  function numero(txt) {
    var t = String(txt).replace(/[^\d,.-]/g, "");
    if (t.indexOf(",") >= 0) t = t.replace(/\./g, "").replace(",", ".");
    var n = parseFloat(t);
    return isFinite(n) ? n : NaN;
  }
  var moeda = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  var pc = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  function linha(classe, texto) {
    var s = document.createElement("span");
    s.className = classe;
    s.textContent = texto;
    return s;
  }
  function mostrar(res) {
    var filhos = Array.prototype.slice.call(arguments, 1);
    while (res.firstChild) res.removeChild(res.firstChild);
    filhos.forEach(function (f) { res.appendChild(f); });
  }

  function preencher(sel, dados, padrao) {
    sel.innerHTML = "";
    dados.forEach(function (d, i) {
      var o = document.createElement("option");
      o.value = String(i);
      o.textContent = rotulo(d[0]);
      sel.appendChild(o);
    });
    sel.value = String(Math.max(0, Math.min(dados.length - 1, padrao)));
  }

  // ---------- ferramenta 1: correção pelo índice escolhido ----------
  (function () {
    var indice = document.getElementById("indice"), ini = document.getElementById("ini"), fim = document.getElementById("fim");
    var valor = document.getElementById("valor"), res = document.getElementById("res");
    if (!indice || !ini || !fim || !valor || !res) return;

    function trocarIndice() {
      var dados = SERIES[indice.value] || [];
      preencher(ini, dados, dados.length - 61);
      preencher(fim, dados, dados.length - 1);
      calcular();
    }
    function calcular() {
      var dados = SERIES[indice.value] || [];
      var v = numero(valor.value), a = parseInt(ini.value, 10), b = parseInt(fim.value, 10);
      if (!dados.length) { mostrar(res, linha("small", "Índice indisponível no momento.")); return; }
      if (!(v >= 0)) { mostrar(res, linha("small", "Digite um valor válido, por exemplo 1.000,00.")); return; }
      if (b <= a) { mostrar(res, linha("small", "Escolha um mês final depois do mês inicial.")); return; }
      var f = 1;
      for (var i = a + 1; i <= b; i++) f *= 1 + dados[i][1] / 100;
      var nome = (indice.options[indice.selectedIndex] || {}).textContent || "índice";
      mostrar(res,
        linha("small", moeda.format(v) + " em " + rotulo(dados[a][0]) + " equivalem a, pelo " + nome + ","),
        linha("big num", moeda.format(v * f)),
        linha("small", "em " + rotulo(dados[b][0]) + " · variação acumulada de " + pc.format((f - 1) * 100) + "% no período")
      );
    }
    trocarIndice();
    indice.addEventListener("change", trocarIndice);
    [valor, ini, fim].forEach(function (e) { e.addEventListener("change", calcular); });
    valor.addEventListener("keydown", function (e) { if (e.key === "Enter") calcular(); });
    document.getElementById("calcular").addEventListener("click", calcular);
  })();

  // ---------- ferramenta 2: rendimento bruto no CDI ----------
  (function () {
    var ini2 = document.getElementById("ini2"), fim2 = document.getElementById("fim2");
    var valor2 = document.getElementById("valor2"), pct = document.getElementById("pct"), res2 = document.getElementById("res2");
    if (!ini2 || !fim2 || !valor2 || !pct || !res2) return;
    var cdi = SERIES.cdi || [];
    preencher(ini2, cdi, cdi.length - 13);
    preencher(fim2, cdi, cdi.length - 1);

    function calcular2() {
      var v = numero(valor2.value), p = numero(pct.value), a = parseInt(ini2.value, 10), b = parseInt(fim2.value, 10);
      if (!(v >= 0)) { mostrar(res2, linha("small", "Digite um valor válido, por exemplo 1.000,00.")); return; }
      if (!(p >= 0)) { mostrar(res2, linha("small", "Digite um percentual do CDI válido, por exemplo 100.")); return; }
      if (b <= a) { mostrar(res2, linha("small", "Escolha um mês final depois do mês inicial.")); return; }
      var f = 1;
      for (var i = a + 1; i <= b; i++) f *= 1 + (cdi[i][1] * p / 100) / 100;
      mostrar(res2,
        linha("small", moeda.format(v) + " em " + rotulo(cdi[a][0]) + " renderiam BRUTO, a " + pc.format(p) + "% do CDI,"),
        linha("big num", moeda.format(v * f)),
        linha("small", "em " + rotulo(cdi[b][0]) + " · rendimento bruto de " + pc.format((f - 1) * 100) + "% no período, antes do Imposto de Renda")
      );
    }
    calcular2();
    [valor2, pct, ini2, fim2].forEach(function (e) { e.addEventListener("change", calcular2); });
    valor2.addEventListener("keydown", function (e) { if (e.key === "Enter") calcular2(); });
    pct.addEventListener("keydown", function (e) { if (e.key === "Enter") calcular2(); });
    document.getElementById("calcular2").addEventListener("click", calcular2);
  })();
})();
