(function () {
  var $ = window.jQuery;
  if (!$ || !$.ajaxPrefilter || window.pascotoPisoCarrinho) return;
  window.pascotoPisoCarrinho = 1;
  var UND = /\(\s*und\.?\s*\)|\bunidades?\b|\bunid\.?\b|\bund\.?\b/i;
  function piso(p) {
    var preco = p ? Number(p.price) : 0;
    if (!p || p.is_giveaway == 1 || p.is_kit == 1 || p.is_kit === true || !(preco > 0)) return 1;
    return preco < 15 && !UND.test(p.name || '') ? 2 : 1;
  }
  function item(id) {
    var c = window.globalCart && window.globalCart.data && window.globalCart.data.cart;
    var ps = (c && c.products) || [];
    for (var i = 0; i < ps.length; i++) {
      if (String(ps[i].cart_id) === id || String(ps[i].id_item) === id) return ps[i];
    }
    return null;
  }
  function aviso() {
    var el = document.getElementById('pc-piso');
    if (!el) {
      el = document.createElement('div');
      el.id = 'pc-piso';
      el.setAttribute('role', 'status');
      el.style.cssText = 'position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:99999;background:#1B5E20;color:#fff;padding:10px 16px;border-radius:8px;font:14px/1.3 sans-serif;max-width:90vw;text-align:center;box-shadow:0 4px 16px rgba(0,0,0,.2)';
      document.body.appendChild(el);
    }
    el.textContent = 'Este produto sai no m\u00ednimo em 200g (2 x 100g).';
    el.style.display = 'block';
    clearTimeout(aviso.t);
    aviso.t = setTimeout(function () { el.style.display = 'none'; }, 4000);
  }
  $.ajaxPrefilter(function (s) {
    try {
      if (String(s.type).toUpperCase() !== 'PUT' || typeof s.data !== 'string') return;
      var m = /\/cart\/api\/item\/([^\/?&#]+)/.exec(s.url || '');
      var q = /(?:^|&)quantity=(\d+)/.exec(s.data);
      if (!m || !q) return;
      var min = piso(item(m[1]));
      if (+q[1] >= 1 && +q[1] < min) {
        s.data = s.data.replace(/(^|&)quantity=\d+/, '$1quantity=' + min);
        aviso();
      }
    } catch (e) {}
  });
})();
