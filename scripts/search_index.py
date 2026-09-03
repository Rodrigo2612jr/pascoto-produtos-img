#!/usr/bin/env python3
"""Gera search-index.json: indice leve pro autocomplete da lupa do tema Tray.

Fonte: web_api PUBLICA da Tray (mesma dos outros scripts), paginada.
Entra so produto ATIVO com foto. Formato compacto (lista de listas) pra ficar
pequeno no navegador:
  p[i] = [id, nome, caminho_da_url, thumb_90px, preco, preco_promocional, category_id]
O tema (elements/busca-sugestoes.html) baixa este arquivo no primeiro foco da lupa.
Roda a cada hora no sync-vitrines e todo dia no refresh-catalog.
"""
import json, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent.parent
DESTINO = ROOT / "search-index.json"
WEB_API = "https://www.emporiopascoto.com.br/web_api/products"
HEADERS = {"User-Agent": "Mozilla/5.0 (pascoto search-index)", "Accept": "application/json"}


def catalogo():
    todos = []
    for pagina in range(1, 40):
        req = urllib.request.Request(f"{WEB_API}?limit=50&page={pagina}", headers=HEADERS)
        for tentativa in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.load(r)
                break
            except Exception as e:
                if tentativa == 2:
                    raise
                time.sleep(2)
        itens = d.get("Products") or d.get("products") or []
        if not itens:
            break
        todos.extend(it.get("Product", it) for it in itens)
    return todos


def linha(p):
    if str(p.get("available", "0")) != "1" or not p.get("id"):
        return None
    imgs = p.get("ProductImage") or []
    if not imgs:
        return None
    thumb = (imgs[0].get("thumbs") or {}).get("90") or {}
    img = thumb.get("https") or imgs[0].get("https") or imgs[0].get("http") or ""
    if not img:
        return None
    u = p.get("url") or {}
    url = (u.get("https") or u.get("http")) if isinstance(u, dict) else (u or "")
    caminho = urlparse(url).path if url else ""
    if not caminho:
        return None
    nome = " ".join(str(p.get("name", "")).split())
    try:
        preco = round(float(p.get("price") or 0), 2)
        promo = round(float(p.get("promotional_price") or 0), 2)
    except ValueError:
        preco, promo = 0.0, 0.0
    if promo and promo >= preco:
        promo = 0.0
    return [int(p["id"]), nome, caminho, img, preco, promo, int(p.get("category_id") or 0)]


def gerar():
    todos = catalogo()
    if len(todos) < 100:
        raise SystemExit(f"ABORTADO: catalogo pequeno demais ({len(todos)}), provavel falha de rede. Nada gravado.")
    linhas = [l for l in (linha(p) for p in todos) if l]
    linhas.sort(key=lambda l: l[1].lower())
    saida = {
        "_meta": {
            "gerado_em": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "fonte": "web_api publica da Tray (/web_api/products)",
            "total_catalogo": len(todos),
            "total_indexado": len(linhas),
            "campos": ["id", "nome", "caminho", "thumb90", "preco", "promo", "category_id"],
        },
        "p": linhas,
    }
    with open(DESTINO, "w", encoding="utf-8") as f:
        json.dump(saida, f, ensure_ascii=False, separators=(",", ":"))
    print(f"search-index.json: {len(linhas)} produtos indexados de {len(todos)} ({DESTINO.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    gerar()
