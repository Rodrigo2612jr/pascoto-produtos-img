#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Atualiza o feed do Instagram do tema.

Diferenca pro jeito antigo: as miniaturas sao BAIXADAS e servidas por este repo
(GitHub Pages). O CDN do Instagram assina as URLs e elas expiram em poucos dias,
entao guardar a URL crua no JSON fazia o feed do site "desconectar" toda vez que
o cron falhava. Com a imagem hospedada aqui, o feed continua de pe.

Uso:  python3 scripts/refresh_instagram.py
Token: env IG_TOKEN (Actions) ou ../Tema Tray/_ig_token.txt (local)
"""
import json, os, sys, urllib.request, urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "ig"
BASE = "https://rodrigo2612jr.github.io/pascoto-produtos-img/ig"
UA = {"User-Agent": "Mozilla/5.0"}

def token():
    t = os.environ.get("IG_TOKEN")
    if t: return t.strip()
    f = ROOT.parent / "Tema Tray" / "_ig_token.txt"
    if f.exists(): return f.read_text().strip()
    sys.exit("IG_TOKEN nao encontrado")

def get(url, timeout=60):
    r = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(r, timeout=timeout) as resp:
        return resp.read()

def main():
    campos = "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp"
    api = (f"https://graph.instagram.com/v21.0/me/media"
           f"?fields={campos}&limit=8&access_token={token()}")
    posts = json.loads(get(api).decode("utf-8")).get("data", [])
    print(f"{len(posts)} posts recebidos")
    DEST.mkdir(exist_ok=True)

    saida, mantidos = [], set()
    for p in posts:
        mt = p.get("media_type", "IMAGE")
        origem = (p.get("thumbnail_url") if mt == "VIDEO" else p.get("media_url")) or p.get("media_url") or ""
        if not origem:
            print(f"  pulei {p.get('id')}: sem imagem"); continue
        nome = f"{p['id']}.jpg"
        try:
            dados = get(origem)
        except Exception as e:
            print(f"  ERRO baixando {nome}: {e}"); continue
        (DEST / nome).write_bytes(dados)
        mantidos.add(nome)
        legenda = (p.get("caption") or "").strip()
        saida.append({
            "url": p.get("permalink", ""),
            "thumbnail": f"{BASE}/{nome}",
            "caption": legenda,
            "alt": legenda[:80] if legenda else "Post do Emporio Pascoto no Instagram",
            "media_type": mt,
            "timestamp": p.get("timestamp", ""),
        })
        print(f"  OK {nome} ({len(dados)//1024} KB) {legenda.splitlines()[0][:50] if legenda else ''}")

    if len(saida) < 4:
        sys.exit(f"ABORTADO: so {len(saida)} posts com imagem, nao vou publicar feed quebrado")

    (ROOT / "instagram-posts.json").write_text(
        json.dumps(saida, ensure_ascii=False, indent=2), encoding="utf-8")

    for velho in DEST.glob("*.jpg"):           # limpa miniatura de post que saiu do feed
        if velho.name not in mantidos:
            velho.unlink(); print(f"  removido {velho.name} (fora do feed)")
    print(f"\nOK: {len(saida)} posts, imagens em ig/")

if __name__ == "__main__":
    main()
