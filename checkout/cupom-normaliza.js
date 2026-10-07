// Tira acento e espaco do codigo de cupom no carrinho e no checkout da Tray,
// na hora de aplicar. POR QUE: o admin da Tray nao aceita acento em codigo de
// cupom e o corretor do celular troca LANCAMENTO10 por LANÇAMENTO10, que a Tray
// responde "Cupom invalido ou inexistente". Carregado pela lista de scripts
// externos da loja (integration.scripts, que o checkout injeta com nonce).
(function () {
  if (window.pascotoCupomNormaliza || !/^\/checkout/.test(location.pathname)) return;
  window.pascotoCupomNormaliza = 1;
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
