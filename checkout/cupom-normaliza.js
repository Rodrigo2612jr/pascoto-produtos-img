// Tira acento e espaco do codigo de cupom no carrinho e no checkout da Tray,
// na hora de aplicar. POR QUE: o admin da Tray nao aceita acento em codigo de
// cupom e o corretor do celular troca LANCAMENTO10 por LANÇAMENTO10, que a Tray
// responde "Cupom invalido ou inexistente". Carregado pelo container GTM do
// checkout (campo GTM nativo da Tray), por src: o CSP do checkout libera
// cdn.jsdelivr.net por host e barra script inline sem nonce.
(function () {
  if (window.pascotoCupomNormaliza || !/^\/checkout/.test(location.pathname)) return;
  window.pascotoCupomNormaliza = 1;

  // Bug da Tray com o campo GTM preenchido: d() do easy-modernize-cart faz
  // c.checkout.products = t com c = google_tag_manager[id].dataLayer.get("ecommerce").
  // Se ecommerce existe sem checkout (ex: mexeu no +/- antes do CEP), da TypeError
  // dentro do setShipping.done e o frete nao atualiza. Garante checkout no retorno.
  function blindaGtm() {
    var g = window.google_tag_manager;
    if (!g) return;
    Object.keys(g).forEach(function (id) {
      var dl = g[id] && g[id].dataLayer;
      if (!dl || typeof dl.get !== 'function' || dl.pascotoBlindado) return;
      var get = dl.get;
      dl.get = function (k) {
        var v = get.apply(this, arguments);
        if (k === 'ecommerce' && v && typeof v === 'object' && !v.checkout) v.checkout = {};
        return v;
      };
      dl.pascotoBlindado = 1;
    });
  }
  blindaGtm();
  setTimeout(blindaGtm, 1500);
  setTimeout(blindaGtm, 5000);

  var SEL = 'input[placeholder*="cupom" i]';
  function normaliza(el) {
    var v = el.value;
    var n = v.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/\s+/g, '');
    if (n === v) return;
    el.value = n;
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  }
  // fase de captura no document: roda antes do handler do Vue no botao Aplicar
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('button');
    if (b && /aplicar/i.test(b.textContent)) document.querySelectorAll(SEL).forEach(normaliza);
  }, true);
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && e.target.matches && e.target.matches(SEL)) normaliza(e.target);
  }, true);
})();
