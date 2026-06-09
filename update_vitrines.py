"""
Auto-sync das imagens das vitrines da home.
Para cada produto no home-vitrines.json, busca a imagem ATUAL na pagina
publica do produto (og:image) e atualiza. Roda no GitHub Actions (sem login).
Paralelo (rapido): ~12 produtos ao mesmo tempo.
"""
import json, re, urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'

def og_image(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        html = urllib.request.urlopen(req, timeout=12).read().decode('utf-8', 'ignore')
        m = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)', html)
        if not m:
            m = re.search(r'id=["\']main-image["\'][^>]*src=["\']([^"\']+)', html)
        if m and 'img_prod' in m.group(1):
            return m.group(1).split('?')[0]
    except Exception:
        pass
    return None

def main():
    with open('home-vitrines.json', encoding='utf-8') as f:
        vit = json.load(f)
    prods = [p for lst in vit.values() if isinstance(lst, list)
             for p in lst if isinstance(p, dict) and p.get('url')]
    with ThreadPoolExecutor(max_workers=12) as ex:
        imgs = list(ex.map(og_image, [p['url'] for p in prods]))
    changed = failed = 0
    for p, img in zip(prods, imgs):
        if img:
            if img != p.get('image'):
                p['image'] = img
                changed += 1
        else:
            failed += 1
    vit.setdefault('_meta', {})['auto_sync'] = 'github-actions'
    with open('home-vitrines.json', 'w', encoding='utf-8') as f:
        json.dump(vit, f, ensure_ascii=False, indent=2)
    print(f'checked={len(prods)} changed={changed} failed={failed}')

if __name__ == '__main__':
    main()
