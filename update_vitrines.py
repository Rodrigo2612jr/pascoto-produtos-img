"""
Auto-sync das imagens das vitrines da home.
Para cada produto no home-vitrines.json, busca a imagem ATUAL na pagina
publica do produto (og:image) e atualiza. Roda no GitHub Actions (sem login).
"""
import json, re, urllib.request, time

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36'

def og_image(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        html = urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'ignore')
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
    checked = changed = failed = 0
    for key, lst in vit.items():
        if not isinstance(lst, list):
            continue
        for p in lst:
            if not isinstance(p, dict):
                continue
            url = p.get('url', '')
            if not url:
                continue
            checked += 1
            img = og_image(url)
            if img:
                if img != p.get('image'):
                    p['image'] = img
                    changed += 1
            else:
                failed += 1
            time.sleep(0.25)
    meta = vit.setdefault('_meta', {})
    meta['auto_sync'] = 'github-actions'
    with open('home-vitrines.json', 'w', encoding='utf-8') as f:
        json.dump(vit, f, ensure_ascii=False, indent=2)
    print(f'checked={checked} changed={changed} failed={failed}')

if __name__ == '__main__':
    main()
