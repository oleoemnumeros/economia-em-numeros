/* Clicar (ou tocar, ou apertar Enter) no gráfico abre a tabela com os números dele. */
(function () {
  function abrir(el) {
    var d = document.getElementById(el.getAttribute("data-abre"));
    if (!d) return;
    d.open = !d.open;
    if (d.open) d.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  }
  document.addEventListener("click", function (e) {
    var el = e.target.closest && e.target.closest("[data-abre]");
    if (el) abrir(el);
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Enter" && e.key !== " ") return;
    var el = e.target.closest && e.target.closest("[data-abre]");
    if (el && el === e.target) { e.preventDefault(); abrir(el); }
  });
})();
