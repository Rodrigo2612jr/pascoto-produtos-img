"""Refresca o home-vitrines.json com precos atuais da loja Pascoto.

Roda no GitHub Actions cron diariamente:
  1. Le o catalogo na web_api PUBLICA da Tray (id, nome, preco, foto, url, disponibilidade)
  2. Calcula colecoes fantasma (achados_banca, imunidade, cafe_fit, snacks_naturais, lanche_saudavel, sem_gluten)
  3. Faz merge com home-vitrines.json existente (preserva chaves antigas)
  4. Salva no diretorio raiz do repo

Saida: home-vitrines.json (na raiz do repo)

POR QUE NAO RASPA MAIS O SITEMAP (12/08/2026):
A versao antiga raspava o sitemap e lia o JSON-LD de cada pagina de produto.
Isso trouxe dois problemas graves:

1. O sitemap nao expoe o ID numerico do produto, entao TODO item saia com
   id null. O tema, sem id, tentava adivinhar o produto pelo nome do arquivo
   da imagem, e quando a imagem virava um placeholder isso desabava: 22
   produtos DESATIVADOS ficaram na loja mostrando o logo esticado.
2. Pagina de produto desativado responde 302 pra /sem-resultados-na-busca, e o
   scraping engolia os dados da pagina de erro como se fossem do produto.

A web_api resolve os dois: devolve id, foto e disponibilidade sem ambiguidade,
sem redirect e sem pagina de erro pra confundir.
"""
import json, re, urllib.request, time, sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse
from collections import OrderedDict

ROOT = Path(__file__).parent.parent
HOME_VITRINES = ROOT / "home-vitrines.json"

SITEMAP = "https://emporiopascoto.commercesuite.com.br/loja/arquivos/1491433/sitemaps/sitemap_1.xml"
WORKERS = 12
PRICE_KG_LIMIT = 19.90

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    "Accept-Encoding": "identity",
    "Cache-Control": "no-cache",
}
URL_RE = re.compile(r"<loc>([^<]+)</loc>")
JSONLD_RE = re.compile(r'<script type="application/ld\+json">([\s\S]*?)</script>', re.IGNORECASE)
META_PRICE_RE = re.compile(r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
META_AVAIL_RE = re.compile(r'<meta[^>]+property=["\']product:availability["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
META_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
META_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
SLUG_RE = re.compile(r"^/(\d+)-([^/]+)/([^/?]+)")

WEIGHT_RE = re.compile(r"(\d+(?:[\.,]\d+)?)\s*(kg|g|gr|gramas?)\b", re.IGNORECASE)
PAREN_RE = re.compile(r"\(([^)]*)\)")


WEB_API = "https://www.emporiopascoto.com.br/web_api/products"
# imagens que nunca sao foto de produto (a 1a e o logo 190x60 da pagina de erro)
PLACEHOLDER_RE = re.compile(
    r"design[_-]?sem[_-]?nome|sem[_-]?imagem|sem[_-]?foto|no[-_]?image|placeholder", re.I)


def catalogo_web_api():
    """Catalogo inteiro pela web_api publica, paginado. Sem login, sem scraping."""
    produtos = []
    pagina = 1
    while pagina <= 40:
        url = f"{WEB_API}?limit=50&page={pagina}"
        try:
            req = urllib.request.Request(url, headers={**HEADERS, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.loads(r.read().decode("utf-8", "ignore"))
        except Exception as e:
            print(f"    falha na pagina {pagina}: {e}")
            break
        itens = d.get("Products") or d.get("products") or []
        if not itens:
            break
        for it in itens:
            p = it.get("Product", it)
            if not p.get("id"):
                continue
            imgs = p.get("ProductImage") or []
            img = ""
            if imgs:
                img = imgs[0].get("https") or imgs[0].get("http") or ""
            if img and PLACEHOLDER_RE.search(img):
                img = ""      # nunca deixa placeholder entrar no dado
            u = p.get("url") or {}
            link = (u.get("https") or u.get("http")) if isinstance(u, dict) else (u or "")
            promo = float(p.get("promotional_price") or 0)
            preco = promo if promo > 0 else float(p.get("price") or 0)
            # cat_id vem do prefixo do slug ("12-chips-e-snacks/..."), que e o
            # mesmo numero que o sitemap dava antes; category_id da API e outro id
            slug = p.get("slug") or ""
            m = re.match(r"^(\d+)-([^/]+)/(.+)$", slug)
            produtos.append({
                "id": int(p["id"]),
                "name": (p.get("name") or "").strip(),
                "price": preco,
                "image": img,
                "url": link,
                "available": str(p.get("available")) == "1",
                "in_stock": str(p.get("available_for_purchase") or p.get("available")) == "1",
                "cat_id": int(m.group(1)) if m else None,
                "cat_slug": m.group(2) if m else None,
                "prod_slug": m.group(3) if m else None,
            })
        pagina += 1
    return produtos


def fetch_urls():
    req = urllib.request.Request(SITEMAP, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        xml = r.read().decode("utf-8", errors="ignore")
    urls = URL_RE.findall(xml)
    products = []
    for u in urls:
        parsed = urlparse(u)
        m = SLUG_RE.match(parsed.path)
        if m:
            products.append({
                "url": u,
                "cat_id": int(m.group(1)),
                "cat_slug": m.group(2),
                "prod_slug": m.group(3),
            })
    return products


def parse_product_page(html, base):
    result = {**base}
    for blk in JSONLD_RE.findall(html):
        try:
            obj = json.loads(blk)
        except Exception:
            continue
        if isinstance(obj, list):
            for o in obj:
                if (o.get("@type") or "").lower() == "product":
                    obj = o
                    break
        if (obj.get("@type") or "").lower() == "product":
            result["name"] = obj.get("name") or result.get("name")
            offers = obj.get("offers") or {}
            if isinstance(offers, list) and offers:
                offers = offers[0]
            try:
                result["price"] = float(offers.get("price") or 0)
            except Exception:
                pass
            avail = (offers.get("availability") or "").lower()
            result["in_stock"] = "instock" in avail or "in_stock" in avail
            img = obj.get("image")
            if isinstance(img, list) and img:
                img = img[0]
            if isinstance(img, str):
                result["image"] = img
            break
    if not result.get("name"):
        m = META_TITLE_RE.search(html)
        if m: result["name"] = m.group(1).strip()
    if "price" not in result:
        m = META_PRICE_RE.search(html)
        if m:
            try: result["price"] = float(m.group(1))
            except: pass
    if "in_stock" not in result:
        m = META_AVAIL_RE.search(html)
        if m: result["in_stock"] = "instock" in m.group(1).lower()
    if not result.get("image"):
        m = META_IMAGE_RE.search(html)
        if m: result["image"] = m.group(1).strip()
    return result


def fetch_one(prod):
    try:
        req = urllib.request.Request(prod["url"], headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", errors="ignore")
        return parse_product_page(html, prod)
    except Exception as e:
        return {**prod, "_error": str(e)[:80]}


def _parse_w(num, unit):
    try:
        n = float(num.replace(",", "."))
    except ValueError:
        return None
    return n * 1000 if unit.lower() == "kg" else n


def weight_g(name):
    if not name: return None
    for inside in PAREN_RE.findall(name):
        m = WEIGHT_RE.search(inside)
        if m:
            r = _parse_w(m.group(1), m.group(2))
            if r: return r
    matches = WEIGHT_RE.findall(name)
    if not matches: return None
    return _parse_w(matches[0][0], matches[0][1])


def to_card(p):
    """O campo id e OBRIGATORIO: e por ele que o tema confere no ar se o
    produto ainda esta ativo e qual e a foto atual. Sem id, o tema tinha que
    adivinhar pelo nome do arquivo da imagem, e era isso que quebrava."""
    return {
        "id": p.get("id"),
        "name": p.get("name", ""),
        "price": p.get("price"),
        "image": p.get("image"),
        "url": p.get("url"),
        "in_stock": p.get("in_stock"),
        "available": p.get("available"),
    }


CATEGORY_RULES = {
    # 03/09/2026 (Rodrigo): card "Lanche saudavel" na home no lugar do "Sem gluten".
    # Ocasiao de consumo (bolsa, trabalho, lancheira), sem promessa de saude:
    # frutas secas (9), chips (12), drageados (13), granolas (22) + barrinhas,
    # biscoitos, balas de mel, pipoca e mixes pelo nome.
    "lanche_saudavel": {
        "cat_ids": [9, 12, 13, 22],
        "kw_include": [r"barr(a|inha)s? de", r"biscoit", r"cookie", r"bala de", r"pipoca",
                       r"\bmix\b", r"banana ?passa", r"granola", r"damasco", r"t[aâ]mara",
                       r"uva ?passa", r"ameixa", r"cranberry", r"chips?\b"],
        # capsula/suplemento nao e lanche (o "cranberry 500mg 90cap" entrava pelo nome)
        "kw_exclude": [r"\bcaps?\b", r"c[aá]psula", r"comprimido", r"\d+ ?mg\b", r"extrato",
                       r"tintura", r"suplement", r"whey", r"creatin", r"col[aá]geno", r"vitamina"],
    },
    "snacks_naturais": {
        "cat_ids": [12],
        "kw_include": [r"drageado", r"barra de", r"banana ?passa", r"\bchips?\b", r"snack"],
    },
}

KEYWORDS = {
    # 03/09/2026 (Rodrigo): cards da home por DOR. Imunidade fica; entram estes 3.
    "sono_ansiedade": {
        "include": [r"camomila", r"melissa", r"mulungu", r"passiflora", r"maracuj[aá]", r"capim[- ]?lim[aã]o",
                    r"cidreira", r"lavanda", r"valeriana", r"magn[eé]sio", r"triptofano", r"ashwagandha",
                    r"\bsono\b", r"calmante", r"relax", r"l[- ]?teanina", r"erva[- ]?doce", r"tília|tilia"],
        "exclude": [r"energ[eé]tico", r"caf[eé]\b", r"leite de magn[eé]sia", r"farinha de maracuj", r"erva[- ]?doce|funcho"],
    },
    "emagrecer": {
        "include": [r"\bchia\b", r"psyllium", r"linha[cç]a", r"farinha de (banana verde|maracuj[aá]|berinjela|coco|am[eê]ndoa|aveia|chia|linha[cç]a)",
                    r"ch[aá] verde", r"hibisco", r"\bgengibre\b", r"cavalinha", r"carqueja", r"ch[aá] branco",
                    r"spirulina", r"termog", r"detox", r"\bslim\b", r"emagre", r"glucomanan", r"aveia em flocos|flocos de aveia|farelo de aveia",
                    r"quinoa|quinua", r"chlorella|clorela", r"sene\b", r"moringa"],
        "exclude": [r"chocolate", r"confeitad", r"caramel", r"cristalizad", r"com mel", r"a[cç][uú]car", r"\bbala\b", r"em cubos", r"\b[oó]leo de gengibre"],
    },
    "sem_acucar": {
        "include": [r"eritritol", r"xilitol", r"stevia|est[eé]via", r"\bzero\b", r"sem a[cç][uú]car|s/ ?a[cç][uú]car|s\.a[cç][uú]car",
                    r"\bdiet\b", r"(choc|cacau)[^,]*(7[0-9]|8[0-9]|9[0-9]|100) ?%", r"(7[0-9]|8[0-9]|9[0-9]|100) ?% ?cacau", r"cacau nibs|nibs de cacau", r"sem adi[cç][aã]o", r"monk ?fruit", r"ado[cç]ante",
                    r"taumatina|sucralose", r"pasta de amendoim", r"manteiga de amendoim", r"cacau em p[oó]|cacau 100"],
        "exclude": [r"c/ ?a[cç][uú]car|com a[cç][uú]car", r"caramel", r"confeitad", r"cristalizad", r"ao leite"],
    },
    "sem_gluten": {
        "include": [r"sem ?gl[úu]ten", r"glut[eê]n[- ]?free"],
        "exclude": [],
    },
    "imunidade": {
        "include": [
            r"prop[óo]lis", r"geleia real", r"camu[- ]?camu", r"acer?ola",
            r"a[çc]a[íi]\b", r"\bguaran[áa]\b", r"\bgengibre\b",
            r"c[úu]rcuma|açafrão|acafrao", r"cogumelo", r"reishi", r"shiitake",
            r"echin[áa]cea|equin[áa]cea", r"castanha do par[áa]|castanha do brasil",
            r"goji",
        ],
        "exclude": [],
    },
    "cafe_fit": {
        "include": [
            r"\bcacau\b", r"chocolate ?(70|80|100)", r"caf[ée]\b", r"\bmuesli\b",
            r"granola", r"aveia em flocos|flocos de aveia", r"\bproteína|proteina\b",
            r"whey", r"manteiga de amendoim", r"pasta de amendoim", r"\bcastanha\b",
            r"amêndoa|amendoa", r"avelã|avela", r"\bnozes?\b", r"\bgoji\b",
            r"chia", r"linhaça|linhaca", r"\bquinoa\b",
        ],
        "exclude": [],
    },
}


def match_any(name, patterns):
    s = (name or "").lower()
    return any(re.search(p, s) for p in patterns)


def build_achados(products):
    out = []
    for p in products:
        price = p.get("price") or 0
        if price <= 0: continue
        w = weight_g(p.get("name", ""))
        if not w or w <= 0: continue
        ppk = price / (w / 1000.0)
        if ppk > PRICE_KG_LIMIT: continue
        card = to_card(p)
        card["_price_per_kg"] = round(ppk, 2)
        out.append(card)
    out.sort(key=lambda x: x["_price_per_kg"])
    return out


def build_keyword(products, key):
    cfg = KEYWORDS[key]
    out, seen = [], set()
    for p in products:
        n = p.get("name", "")
        if match_any(n, cfg["include"]) and not match_any(n, cfg["exclude"]):
            u = p.get("url")
            if u and u not in seen:
                seen.add(u)
                out.append(to_card(p))
    return out


def build_category(products, key):
    cfg = CATEGORY_RULES[key]
    out, seen = [], set()
    for p in products:
        ok = False
        if p.get("cat_id") in cfg.get("cat_ids", []):
            ok = True
        elif cfg.get("kw_include") and match_any(p.get("name", ""), cfg["kw_include"]):
            ok = True
        if ok and cfg.get("kw_exclude") and match_any(p.get("name", ""), cfg["kw_exclude"]):
            ok = False
        if ok:
            u = p.get("url")
            if u and u not in seen:
                seen.add(u)
                out.append(to_card(p))
    return out


def main():
    t0 = time.time()
    print("[1] Lendo catalogo na web_api publica da Tray...")
    todos = catalogo_web_api()
    print(f"    {len(todos)} produtos em {time.time()-t0:.1f}s")
    if len(todos) < 100:
        print("ABORTADO: catalogo pequeno demais, provavel falha de rede. Nada gravado.")
        raise SystemExit(1)

    # so entra em vitrine quem esta ATIVO e tem foto de verdade
    products = [p for p in todos if p["available"] and p["image"]]
    fora = len(todos) - len(products)
    print(f"[2] {len(products)} elegiveis ({fora} fora: desativados ou sem foto)")

    print(f"[3] Construindo coleções...")
    new_keys = OrderedDict()
    new_keys["achados_banca"] = build_achados(products)
    new_keys["imunidade"] = build_keyword(products, "imunidade")
    new_keys["cafe_fit"] = build_keyword(products, "cafe_fit")
    new_keys["snacks_naturais"] = build_category(products, "snacks_naturais")
    new_keys["lanche_saudavel"] = build_category(products, "lanche_saudavel")
    new_keys["sono_ansiedade"] = build_keyword(products, "sono_ansiedade")
    new_keys["emagrecer"] = build_keyword(products, "emagrecer")
    new_keys["sem_acucar"] = build_keyword(products, "sem_acucar")
    sg = build_keyword(products, "sem_gluten")
    if sg:
        new_keys["sem_gluten"] = sg
    for k, v in new_keys.items():
        print(f"    {k}: {len(v)} produtos")

    print(f"[4] Merge com home-vitrines.json existente...")
    if HOME_VITRINES.exists():
        with open(HOME_VITRINES, encoding="utf-8") as f:
            current = json.load(f)
    else:
        current = {}
    merged = {**current, **new_keys}

    # TRAVA: nao publica item sem id nem com placeholder. Se sobrar, o job
    # falha de proposito, pra virar email do GitHub em vez de logo na loja.
    ruins = []
    for k, lst in merged.items():
        if not isinstance(lst, list):
            continue
        for p in lst:
            if not isinstance(p, dict):
                continue
            nome = (p.get("name") or "?").strip()
            if p.get("id") is None:
                ruins.append(f"{k}: {nome} (sem id)")
            if PLACEHOLDER_RE.search(p.get("image") or ""):
                ruins.append(f"{k}: {nome} (imagem placeholder)")

    with open(HOME_VITRINES, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    size_kb = HOME_VITRINES.stat().st_size // 1024
    print(f"    Salvo: {HOME_VITRINES} ({size_kb} KB)")
    print(f"\nTotal: {time.time()-t0:.1f}s")
    if ruins:
        print(f"FALHA: {len(ruins)} itens invalidos ficaram no arquivo:")
        for x in ruins[:30]:
            print("   ", x)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
