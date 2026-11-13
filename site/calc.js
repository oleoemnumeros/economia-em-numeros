/* Calculadora de correção pelo IPCA: tudo roda no navegador, com os índices mensais embutidos na página. */
(function () {
  "use strict";
  var el = document.getElementById("dados-ipca");
  if (!el) return;
  var dados = JSON.parse(el.textContent); // [["2000-01", 0.62], ...] em % ao mês
  var MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];
  var ini = document.getElementById("ini"), fim = document.getElementById("fim");
  var valor = document.getElementById("valor"), res = document.getElementById("res");

  function rotulo(p) { return MESES[parseInt(p.slice(5), 10) - 1] + "/" + p.slice(0, 4); }
  function preencher(sel, padrao) {
    dados.forEach(function (d, i) {
      var o = document.createElement("option");
      o.value = String(i);
      o.textContent = rotulo(d[0]);
      sel.appendChild(o);
    });
    sel.value = String(padrao);
  }
  preencher(ini, Math.max(0, dados.length - 61));
  preencher(fim, dados.length - 1);

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
  function mostrar() {
    var filhos = Array.prototype.slice.call(arguments);
    while (res.firstChild) res.removeChild(res.firstChild);
    filhos.forEach(function (f) { res.appendChild(f); });
  }

  function calcular() {
    var v = numero(valor.value), a = parseInt(ini.value, 10), b = parseInt(fim.value, 10);
    if (!(v >= 0)) { mostrar(linha("small", "Digite um valor válido, por exemplo 1.000,00.")); return; }
    if (b <= a) { mostrar(linha("small", "Escolha um mês final depois do mês inicial.")); return; }
    var f = 1;
    for (var i = a + 1; i <= b; i++) f *= 1 + dados[i][1] / 100;
    mostrar(
      linha("small", moeda.format(v) + " em " + rotulo(dados[a][0]) + " equivalem a"),
      linha("big num", moeda.format(v * f)),
      linha("small", "em " + rotulo(dados[b][0]) + " · inflação acumulada de " + pc.format((f - 1) * 100) + "% no período")
    );
  }

  document.getElementById("calcular").addEventListener("click", calcular);
  [valor, ini, fim].forEach(function (e) { e.addEventListener("change", calcular); });
  valor.addEventListener("keydown", function (e) { if (e.key === "Enter") calcular(); });
  calcular();
})();
