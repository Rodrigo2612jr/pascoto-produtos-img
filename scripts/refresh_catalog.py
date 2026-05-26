"""Refresca o home-vitrines.json com precos atuais da loja Pascoto.

Roda no GitHub Actions cron diariamente:
  1. Scrape sitemap publico → todos os produtos com nome/preco/imagem
  2. Calcula coleções fantasma (achados_banca, imunidade, cafe_fit, snacks_naturais, sem_gluten)
  3. Faz merge com home-vitrines.json existente (preserva chaves antigas)
  4. Salva no diretorio raiz do repo

Saida: home-vitrines.json (na raiz do repo)
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

HEADERS = {"User-Agent": "Mozilla/5.0 (pascoto-refresh-bot)"}
URL_RE = re.compile(r"<loc>([^<]+)</loc>")
JSONLD_RE = re.compile(r'<script type="application/ld\+json">([\s\S]*?)</script>', re.IGNORECASE)
META_PRICE_RE = re.compile(r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
META_AVAIL_RE = re.compile(r'<meta[^>]+property=["\']product:availability["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
META_TITLE_RE = re.compile(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
META_IMAGE_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', re.IGNORECASE)
SLUG_RE = re.compile(r"^/(\d+)-([^/]+)/([^/?]+)")

WEIGHT_RE = re.compile(r"(\d+(?:[\.,]\d+)?)\s*(kg|g|gr|gramas?)\b", re.IGNORECASE)
PAREN_RE = re.compile(r"\(([^)]*)\)")


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
    return {
        "name": p.get("name", ""),
        "price": p.get("price"),
        "image": p.get("image"),
        "url": p.get("url"),
        "in_stock": p.get("in_stock"),
    }


CATEGORY_RULES = {
    "snacks_naturais": {
        "cat_ids": [12],
        "kw_include": [r"drageado", r"barra de", r"banana ?passa", r"\bchips?\b", r"snack"],
    },
}

KEYWORDS = {
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
        if ok:
            u = p.get("url")
            if u and u not in seen:
                seen.add(u)
                out.append(to_card(p))
    return out


def main():
    t0 = time.time()
    print(f"[1] Baixando sitemap...")
    urls = fetch_urls()
    print(f"    {len(urls)} URLs de produto")

    print(f"[2] Scrape paralelo ({WORKERS} workers)...")
    products = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(fetch_one, p): p for p in urls}
        for fut in as_completed(futures):
            r = fut.result()
            if "_error" not in r:
                products.append(r)
    print(f"    {len(products)} OK em {time.time()-t0:.1f}s")

    print(f"[3] Construindo coleções...")
    new_keys = OrderedDict()
    new_keys["achados_banca"] = build_achados(products)
    new_keys["imunidade"] = build_keyword(products, "imunidade")
    new_keys["cafe_fit"] = build_keyword(products, "cafe_fit")
    new_keys["snacks_naturais"] = build_category(products, "snacks_naturais")
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

    with open(HOME_VITRINES, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    size_kb = HOME_VITRINES.stat().st_size // 1024
    print(f"    Salvo: {HOME_VITRINES} ({size_kb} KB)")
    print(f"\nTotal: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
