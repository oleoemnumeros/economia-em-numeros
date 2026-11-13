/* Busca de municípios (Bolsa Família): carrega o índice na primeira vez que a pessoa usa o campo e filtra sem acento. */
(function () {
  var campo = document.getElementById("bf-busca");
  var lista = document.getElementById("bf-res");
  if (!campo || !lista) return;
  var indice = null, carregando = false;
  function norm(t) {
    return String(t).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim();
  }
  function carregar(depois) {
    if (indice) return depois();
    if (carregando) return;
    carregando = true;
    fetch(campo.getAttribute("data-indice")).then(function (r) { return r.json(); }).then(function (d) {
      indice = d.map(function (x) { return { n: norm(x[0]), nome: x[0], uf: x[1], url: x[2], f: x[3], c: x[4] }; });
      carregando = false;
      depois();
    }).catch(function () {
      carregando = false;
      lista.textContent = "Não consegui carregar a lista de municípios. Tente de novo em instantes.";
    });
  }
  function fmt(n) { return n.toLocaleString("pt-BR"); }
  function mostrar() {
    var q = norm(campo.value);
    lista.textContent = "";
    if (q.length < 2) return;
    var ini = [], meio = [];
    for (var i = 0; i < indice.length && ini.length < 8; i++) {
      var k = indice[i].n.indexOf(q);
      if (k === 0) ini.push(indice[i]); else if (k > 0 && meio.length < 8) meio.push(indice[i]);
    }
    var achados = ini.concat(meio).slice(0, 8);
    if (!achados.length) {
      var vazio = document.createElement("li");
      vazio.textContent = "Nenhum município encontrado com esse nome.";
      lista.appendChild(vazio);
      return;
    }
    achados.forEach(function (m) {
      var li = document.createElement("li");
      var a = document.createElement("a");
      a.href = m.url;
      a.textContent = m.nome + " (" + m.uf + ")";
      var s = document.createElement("span");
      s.className = "small";
      s.textContent = " · " + fmt(m.f) + " famílias" + (m.c !== null && m.c !== undefined ? ", " + String(m.c).replace(".", ",") + "% da população" : "");
      li.appendChild(a);
      li.appendChild(s);
      lista.appendChild(li);
    });
  }
  campo.addEventListener("focus", function () { carregar(function () {}); });
  campo.addEventListener("input", function () { carregar(mostrar); });
  campo.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      var a = lista.querySelector("a");
      if (a) { e.preventDefault(); window.location.href = a.href; }
    }
  });
})();
