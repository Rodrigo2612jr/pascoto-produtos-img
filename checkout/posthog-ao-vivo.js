// PostHog no carrinho e no checkout da Tray, para a tela "Ao vivo" do painel
// enxergar as etapas depois de "pos no carrinho". Na vitrine quem faz isso e a
// tag do GTM (painel-pg docs/gtm/posthog-ao-vivo.html); aqui o GTM nao carrega.
// Regras (Rodrigo, 19/11/2026):
// - NUNCA grava a tela aqui (tem endereco, CPF e pagamento). Sem autocapture.
// - Vai so o NOME da etapa (begin_checkout, add_payment_info, purchase...) e o
//   caminho da pagina sem a query (a URL do carrinho leva o session_id da Tray).
// - Quem nao aceitou os cookies entra so na contagem anonima, sem cookie.
// Carregado pela lista de scripts externos da Tray. O CSP do checkout libera
// cdn.jsdelivr.net por host, por isso a biblioteca vem de la (versao fixa).
(function () {
  if (window.posthog || !/^\/checkout/.test(location.pathname)) return;
  var TOKEN = 'phc_yg8QK9c5MmMiG3Ly7pSHXzGHQCC7NfvaxYiR2JFBefC3', HOST = 'https://us.i.posthog.com';
  var LIB = 'https://cdn.jsdelivr.net/npm/posthog-js@1.447.3/dist/array.no-external.js';
  var aceitou = /(?:^|;\s*)pascoto_consent=granted/.test(document.cookie);
  var semQuery = function (u) { return typeof u === 'string' ? u.split('?')[0].split('#')[0] : u; };

  var ph = []; ph._i = []; ph.people = []; ph.__SV = 1;
  var met = 'capture register identify reset opt_in_capturing opt_out_capturing has_opted_out_capturing'.split(' ');
  for (var i = 0; i < met.length; i++) (function (m) { ph[m] = function () { ph.push([m].concat([].slice.call(arguments))); }; })(met[i]);
  ph._i.push([TOKEN, {
    api_host: HOST,
    person_profiles: 'identified_only',
    capture_pageview: true,
    capture_pageleave: true,
    autocapture: false,
    capture_dead_clicks: false,
    capture_exceptions: false,
    capture_heatmaps: false,
    capture_performance: false,
    disable_surveys: true,
    disable_session_recording: true,
    advanced_disable_flags: true,
    cookieless_mode: 'on_reject',
    opt_out_capturing_by_default: true,
    mask_all_text: true,
    mask_all_element_attributes: true,
    before_send: function (ev) {
      var p = ev && ev.properties;
      if (p) {
        var chaves = ['$current_url', '$referrer', '$prev_pageview_pathname', '$initial_current_url', '$initial_referrer', '$session_entry_url'];
        for (var k = 0; k < chaves.length; k++) if (p[chaves[k]]) p[chaves[k]] = semQuery(p[chaves[k]]);
        if (p.$set_once) for (var s in p.$set_once) p.$set_once[s] = semQuery(p.$set_once[s]);
        p.title = location.pathname.indexOf('/checkout/cart') === 0 ? 'Carrinho' : 'Checkout';
      }
      return ev;
    }
  }, 'posthog']);
  window.posthog = ph;
  var s = document.createElement('script');
  s.async = true; s.crossOrigin = 'anonymous'; s.src = LIB;
  document.head.appendChild(s);
  if (aceitou) window.posthog.opt_in_capturing();
  else if (/(?:^|;\s*)pascoto_consent=denied/.test(document.cookie)) window.posthog.opt_out_capturing();

  // Etapas: so o NOME dos eventos que a propria Tray poe no dataLayer do GA4, uma vez por pagina.
  var EV = { begin_checkout: 1, add_shipping_info: 1, add_payment_info: 1, purchase: 1 }, visto = {};
  var passa = function (o) {
    try {
      var n = o && (o.event || (o[0] === 'event' && o[1]));
      if (typeof n === 'string' && EV[n] && !visto[n]) { visto[n] = 1; window.posthog.capture(n); }
    } catch (e) {}
  };
  var escuta = function (nome) {
    var dl = window[nome] = window[nome] || [];
    for (var j = 0; j < dl.length; j++) passa(dl[j]);
    var push = dl.push;
    dl.push = function () {
      for (var k = 0; k < arguments.length; k++) passa(arguments[k]);
      return push.apply(dl, arguments);
    };
  };
  escuta('dataLayerGa4');
  escuta('dataLayer');
  // Saiu do carrinho e entrou na tela de dados: isso ja e "comecou o checkout".
  if (location.pathname.indexOf('/checkout/cart') !== 0) passa({ event: 'begin_checkout' });
})();
