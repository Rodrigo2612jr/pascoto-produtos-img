"""
Auto-sync das vitrines da home. Roda no GitHub Actions, sem login.

FONTE DA VERDADE: a web_api PUBLICA da Tray, consultada por ID.
Esta versao NAO raspa mais o HTML da pagina do produto.

POR QUE MUDOU (12/08/2026, depois do bug do logo esticado):
A versao antiga lia o og:image da pagina publica de cada produto. Quando um
produto e DESATIVADO na Tray, a pagina dele responde 302 para
/sem-resultados-na-busca, e o og:image dessa pagina de erro e a imagem social
padrao da loja: o logo, de 190x60 pixels. Como esse arquivo tambem mora em
/img_prod/, ele passava no unico filtro que existia e era gravado como se
fosse a foto do produto.

Resultado que o Rodrigo viu na loja: 22 produtos apareciam nas vitrines com o
logo esticado 4x no lugar da foto. E como este script roda de hora em hora,
qualquer correcao manual no JSON era desfeita em ate 60 minutos.

Os 22 produtos com logo eram EXATAMENTE os 22 produtos desativados. Correlacao
de 100%: nao era problema de foto, era produto morto sendo exibido na loja.

TRAVAS DESTA VERSAO (cada uma corta a falha num ponto diferente):
1. Consulta por ID na web_api, que devolve imagem, preco, url e disponibilidade
   sem ambiguidade. Sem HTML, sem redirect, sem pagina de erro pra confundir.
2. Grava o campo "id" em TODO item. Antes 165 dos 233 estavam com id null e o
   tema era obrigado a adivinhar o id lendo o nome do arquivo da imagem, que e
   justamente o que quebrava quando a imagem virava placeholder.
3. Marca "available": false em produto indisponivel, em vez de apagar o item.
   Assim a curadoria do Rodrigo nao se perde: se ele reativar o produto, ele
   volta pra vitrine sozinho na proxima hora.
4. Imagem que casa com a lista de placeholders NUNCA e gravada.
5. O job FALHA se sobrar placeholder ou item sem id. Erro vira email do GitHub
   em vez de logo esticado na loja.
"""
import json, re, sys, time, unicodedata, urllib.request

BASE = 'https://www.emporiopascoto.com.br'
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120 Safari/537.36')

# Imagens que NUNCA podem virar foto de produto. A primeira e o logo social da
# loja (190x60), que a pagina de erro devolve como og:image.
PLACEHOLDER = re.compile(
    r'design[_-]?sem[_-]?nome|sem[_-]?imagem|sem[_-]?foto|no[-_]?image|placeholder',
    re.I,
)

# Imagem fixada a mao, o sync nao sobrescreve.
SKIP_IMG = {'quirela-100gr'}

# Padrao do nome de arquivo de imagem de produto da Tray: ..._{id}_{n}_{hash}.jpg
RX_ID_ARQUIVO = re.compile(r'_(\d+)_\d+_[a-f0-9]+\.(?:jpe?g|png|webp)', re.I)


def norm(s):
    """Nome comparavel: sem acento, sem pontuacao, minusculo."""
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '', s.lower())


def buscar(url, tentativas=3):
    for i in range(tentativas):
        try:
            req = urllib.request.Request(
                url, headers={'User-Agent': UA, 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode('utf-8', 'ignore'))
        except Exception as e:
            if i == tentativas - 1:
                print(f'  falha em {url}: {e}')
                return None
            time.sleep(2 * (i + 1))
    return None


def catalogo():
    """Le o catalogo inteiro da web_api publica, paginado.

    Indexa por id E por nome normalizado: o id e o caminho principal, o nome e
    a rede de seguranca pros itens que ainda estao com id null no JSON.
    """
    por_id, por_nome = {}, {}
    pagina = 1
    while pagina <= 30:
        d = buscar(f'{BASE}/web_api/products?limit=50&page={pagina}')
        if d is None:
            return None, None  # rede ruim: aborta sem gravar nada
        itens = d.get('Products') or d.get('products') or []
        if not itens:
            break
        for it in itens:
            p = it.get('Product', it)
            if not p.get('id'):
                continue
            imgs = p.get('ProductImage') or []
            img = ''
            if imgs:
                img = imgs[0].get('https') or imgs[0].get('http') or ''
            u = p.get('url') or {}
            url = (u.get('https') or u.get('http')) if isinstance(u, dict) else u
            promo = float(p.get('promotional_price') or 0)
            preco = promo if promo > 0 else float(p.get('price') or 0)
            reg = {
                'id': int(p['id']),
                'name': (p.get('name') or '').strip(),
                'image': img,
                'url': url or '',
                'price': preco,
                'available': str(p.get('available')) == '1',
            }
            por_id[str(reg['id'])] = reg
            por_nome.setdefault(norm(reg['name']), reg)
        pagina += 1
    return por_id, por_nome


def resolver(p, por_id, por_nome):
    """Acha o produto do catalogo pro item da vitrine, em 3 tentativas."""
    # 1) id ja gravado no JSON (o caminho bom)
    if p.get('id') is not None:
        r = por_id.get(str(p['id']))
        if r:
            return r
    # 2) id escondido no nome do arquivo da imagem (legado)
    m = RX_ID_ARQUIVO.search(p.get('image') or '')
    if m:
        r = por_id.get(m.group(1))
        if r:
            return r
    # 3) pelo nome, pros itens sem id e sem imagem util
    return por_nome.get(norm(p.get('name')))


def main():
    with open('home-vitrines.json', encoding='utf-8') as f:
        vit = json.load(f)

    print('lendo catalogo da web_api...')
    por_id, por_nome = catalogo()
    if not por_id:
        print('ABORTADO: nao consegui ler o catalogo, nada foi gravado.')
        raise SystemExit(1)
    print(f'catalogo: {len(por_id)} produtos')

    total = achados = 0
    mudou_img = mudou_disp = 0
    ganhou_id = 0
    perdidos = []

    for chave, lista in vit.items():
        if not isinstance(lista, list):
            continue
        for p in lista:
            if not isinstance(p, dict):
                continue
            total += 1
            r = resolver(p, por_id, por_nome)
            if not r:
                perdidos.append(f"{chave}: {(p.get('name') or '?').strip()}")
                continue
            achados += 1

            if p.get('id') != r['id']:
                p['id'] = r['id']
                ganhou_id += 1

            # disponibilidade: marca em vez de apagar, pra nao perder curadoria
            antes = p.get('available')
            p['available'] = r['available']
            if antes != r['available']:
                mudou_disp += 1

            slug = (p.get('url') or '').rstrip('/').split('/')[-1]
            if slug in SKIP_IMG:
                continue

            # imagem: so grava foto de verdade
            nova = r['image']
            if nova and not PLACEHOLDER.search(nova):
                if nova != p.get('image'):
                    p['image'] = nova
                    mudou_img += 1
            if r['url']:
                p['url'] = r['url']
            if r['price'] > 0:
                p['price'] = r['price']

    # ---- travas finais: nao publica lixo ----
    restou_ph = [
        f"{k}: {(p.get('name') or '?').strip()}"
        for k, lst in vit.items() if isinstance(lst, list)
        for p in lst if isinstance(p, dict) and PLACEHOLDER.search(p.get('image') or '')
    ]
    sem_id = [
        f"{k}: {(p.get('name') or '?').strip()}"
        for k, lst in vit.items() if isinstance(lst, list)
        for p in lst if isinstance(p, dict) and p.get('id') is None
    ]

    if achados < total * 0.9:
        print(f'ABORTADO: so resolvi {achados}/{total} produtos, nao gravou.')
        for x in perdidos[:20]:
            print('   perdido:', x)
        raise SystemExit(1)

    indisponiveis = sum(
        1 for k, lst in vit.items() if isinstance(lst, list)
        for p in lst if isinstance(p, dict) and p.get('available') is False
    )

    meta = vit.setdefault('_meta', {})
    meta['auto_sync'] = 'github-actions'
    meta['fonte'] = 'web_api publica da Tray, por id'
    meta['itens'] = total
    meta['indisponiveis'] = indisponiveis

    with open('home-vitrines.json', 'w', encoding='utf-8') as f:
        json.dump(vit, f, ensure_ascii=False, indent=2)

    print(f'itens={total} resolvidos={achados} imagens_novas={mudou_img} '
          f'ids_gravados={ganhou_id} disponibilidade_mudou={mudou_disp} '
          f'indisponiveis={indisponiveis}')
    if perdidos:
        print(f'nao resolvidos ({len(perdidos)}):')
        for x in perdidos:
            print('   ', x)

    erro = False
    if restou_ph:
        print(f'\nFALHA: {len(restou_ph)} itens ficaram com imagem placeholder:')
        for x in restou_ph:
            print('   ', x)
        erro = True
    if sem_id:
        print(f'\nFALHA: {len(sem_id)} itens ficaram sem id:')
        for x in sem_id:
            print('   ', x)
        erro = True
    if erro:
        print('\nO arquivo foi gravado com o que deu pra corrigir, mas o job '
              'falha de proposito pra este erro virar email em vez de logo '
              'esticado na loja.')
        raise SystemExit(1)


if __name__ == '__main__':
    main()
