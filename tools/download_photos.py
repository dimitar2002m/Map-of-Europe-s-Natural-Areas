#!/usr/bin/env python3
"""
Сваля снимките на видовете и на зоните и записва авторите и лицензите им.

Пуска се ВЕДНЪЖ на компютър с интернет връзка, от папката на проекта:

    python3 tools/download_photos.py --contact вашият@имейл

(На Windows може да трябва python вместо python3.)

Какво прави:
  1. Чете ZONES и SPECIES от data/content.js.
  2. За всеки вид търси снимка в английската Уикипедия по латинското име.
     Ако няма подходяща, търси в българската Уикипедия по българското име
     (тогава проверете снимката). За всяка зона взима снимката от полето wiki.
     SVG файловете (схеми и карти) се пропускат. Видовете с поле "photo" в
     content.js се пропускат – там е вашият собствен файл.
  3. Сваля миниатюра от 800 px в img/<id>.jpg (зоните – в img/zone-<id>.jpg).
  4. Взима автора и лиценза от Wikimedia Commons и ги записва в data/photos.js.

Снимките са на различни автори и лицензи (често CC BY или CC BY-SA). Ако публикувате
проекта, не махайте бележките в data/photos.js – в тях са авторите.
Ако дадена снимка не ви харесва, сложете свой файл в img/ и добавете в SPECIES:
    photo: "img/vulk.jpg"

Опции:
  --contact КОНТАКТ   имейл или адрес, изпращан в заявките (препоръчително)
  --skip-existing     не сваля отново файловете, които вече са в img/
  --pause СЕК         пауза между заявките, в секунди (по подразбиране 0.5)
"""
import argparse
import glob
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
CONTENT_JS = os.path.join(ROOT, 'data', 'content.js')
PHOTOS_JS = os.path.join(ROOT, 'data', 'photos.js')
IMG_DIR = os.path.join(ROOT, 'img')

EN_API = 'https://en.wikipedia.org/w/api.php'
BG_API = 'https://bg.wikipedia.org/w/api.php'
COMMONS_API = 'https://commons.wikimedia.org/w/api.php'
THUMB_WIDTH = 800
ALLOWED_EXT = ('.jpg', '.jpeg', '.png', '.webp', '.gif')

PAUSE = 0.5


def parse_content(text):
    """Връща (зони, видове) от data/content.js. Разчита на форматирането на файла."""
    zones_part = text[text.index('var ZONES'):text.index('var SPECIES')]
    species_part = text[text.index('var SPECIES'):]

    zones = []
    # Всеки обект на зона завършва с "\n  }" (с или без запетая след него).
    for m in re.finditer(r'\{\s*id:\s*"([^"]+)",(.*?)\n  \}', zones_part, re.S):
        body = m.group(2)
        name = re.search(r'name:\s*"([^"]+)"', body)
        wiki = re.search(r'wiki:\s*"([^"]*)"', body)
        zones.append({
            'id': m.group(1),
            'name': name.group(1) if name else m.group(1),
            'wiki': wiki.group(1) if wiki else '',
        })

    species = []
    pattern = (r'\{\s*id:\s*"([^"]+)",\s*type:\s*"(animal|plant)",\s*'
               r'name:\s*"([^"]+)",\s*latin:\s*"([^"]+)"([^}]*)\}')
    for m in re.finditer(pattern, species_part, re.S):
        species.append({
            'id': m.group(1),
            'type': m.group(2),
            'name': m.group(3),
            'latin': m.group(4),
            'photo': bool(re.search(r'photo:\s*"', m.group(5))),
        })
    return zones, species


def make_ua(contact):
    ua = 'PrirodniZoniPhotos/1.0 (edu map project'
    if contact:
        ua += '; ' + contact
    return ua + ') python-urllib'


def api_get(api, params, ua):
    query = dict(params)
    query.update({'format': 'json', 'formatversion': '2'})
    url = api + '?' + urllib.parse.urlencode(query)
    req = urllib.request.Request(url, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    time.sleep(PAUSE)
    return data


def pick_page(data):
    """Взима първата страница с миниатюра. Връща речник или None."""
    pages = (data.get('query') or {}).get('pages') or []
    if not pages:
        return None
    page = pages[0]
    if page.get('missing') or not page.get('thumbnail'):
        return None
    image_name = page.get('pageimage', '')
    if image_name.lower().endswith('.svg'):
        return None  # схемите и картите в SVG не са снимки
    return {
        'url': page['thumbnail']['source'],
        'file': image_name,
        'page': page.get('title', ''),
    }


def en_lead_image(title, ua):
    data = api_get(EN_API, {
        'action': 'query', 'redirects': 1, 'prop': 'pageimages',
        'piprop': 'thumbnail|name', 'pithumbsize': THUMB_WIDTH, 'titles': title,
    }, ua)
    hit = pick_page(data)
    if hit:
        hit['origin'] = 'en'
    return hit


def bg_search_image(name, ua):
    data = api_get(BG_API, {
        'action': 'query', 'generator': 'search', 'gsrsearch': name, 'gsrlimit': 1,
        'prop': 'pageimages', 'piprop': 'thumbnail|name', 'pithumbsize': THUMB_WIDTH,
    }, ua)
    hit = pick_page(data)
    if not hit:
        return None
    # Търсенето връща най-близката статия, която не винаги е за същия вид.
    # Приемаме снимката само ако заглавието съдържа българското име (без скобите).
    base = re.sub(r'\(.*?\)', '', name).strip().lower()
    if base not in hit['page'].lower():
        return None
    hit['origin'] = 'bg'
    return hit


def strip_html(text):
    text = re.sub(r'<[^>]+>', ' ', text or '')
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()


def commons_credit(file_name, ua):
    """Автор и лиценз от Wikimedia Commons. Връща речник (може да е празен)."""
    if not file_name:
        return {}
    data = api_get(COMMONS_API, {
        'action': 'query', 'prop': 'imageinfo', 'iiprop': 'extmetadata|url',
        'titles': 'File:' + file_name,
    }, ua)
    pages = (data.get('query') or {}).get('pages') or []
    if not pages or pages[0].get('missing'):
        return {}
    info = (pages[0].get('imageinfo') or [{}])[0]
    meta = info.get('extmetadata') or {}

    def val(key):
        return strip_html((meta.get(key) or {}).get('value', ''))

    return {
        'artist': val('Artist'),
        'license': val('LicenseShortName'),
        'licenseUrl': (meta.get('LicenseUrl') or {}).get('value', ''),
        'source': info.get('descriptionurl', ''),
    }


def download(url, dst, ua):
    req = urllib.request.Request(url, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(dst, 'wb') as f:
        f.write(data)
    time.sleep(PAUSE)


def ext_of(url):
    ext = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower()
    return ext if ext in ALLOWED_EXT else '.jpg'


def fetch_one(base_name, en_title, bg_name, ua, skip_existing):
    """Връща запис за data/photos.js или None, ако няма снимка."""
    hit = None
    try:
        if en_title:
            hit = en_lead_image(en_title, ua)
        if not hit and bg_name:
            hit = bg_search_image(bg_name, ua)
    except Exception as exc:  # мрежова грешка или неочакван отговор
        print('  ГРЕШКА при търсенето: %s' % exc)
        return None
    if not hit:
        print('  няма подходяща снимка')
        return None

    existing = sorted(glob.glob(os.path.join(IMG_DIR, base_name + '.*')))
    try:
        if skip_existing and existing:
            dst = existing[0]
        else:
            dst = os.path.join(IMG_DIR, base_name + ext_of(hit['url']))
            download(hit['url'], dst, ua)
        credit = commons_credit(hit['file'], ua)
    except Exception as exc:
        print('  ГРЕШКА при сваляне: %s' % exc)
        return None

    entry = {
        'file': 'img/' + os.path.basename(dst),
        'origin': hit['origin'],
        'page': hit['page'],
    }
    entry.update(credit)
    print('  ок: %s (%s)' % (entry['file'], 'английската' if hit['origin'] == 'en' else 'българската Уикипедия'))
    return entry


def write_photos_js(credits):
    header = ('// Снимки на видовете и зоните: файловете са в img/, а тук са бележките за авторите и лиценза.\n'
              '// Генерирано от tools/download_photos.py – при всяко пускане се презаписва.\n')
    body = json.dumps(credits, ensure_ascii=False, indent=2, sort_keys=True)
    with open(PHOTOS_JS, 'w', encoding='utf-8') as f:
        f.write(header)
        f.write('var PHOTO_CREDITS = ' + body + ';\n')


def main():
    global PAUSE
    ap = argparse.ArgumentParser(description='Сваля снимките за природните зони и видовете.')
    ap.add_argument('--contact', default='',
                    help='имейл или адрес, изпращан в заявките (препоръчително)')
    ap.add_argument('--skip-existing', action='store_true',
                    help='не сваля отново файловете, които вече са в img/')
    ap.add_argument('--pause', type=float, default=0.5,
                    help='пауза между заявките, в секунди (по подразбиране 0.5)')
    opts = ap.parse_args()

    PAUSE = max(0.0, opts.pause)
    if not opts.contact:
        print('Съвет: добавете --contact вашият@имейл (Уикипедия препоръчва да се знае кой прави заявките).')
    ua = make_ua(opts.contact)

    with open(CONTENT_JS, encoding='utf-8') as f:
        zones, species = parse_content(f.read())
    print('Зони: %d, видове: %d' % (len(zones), len(species)))
    os.makedirs(IMG_DIR, exist_ok=True)

    # (ключ в PHOTO_CREDITS, име на файла без разширение, заглавие в en.wikipedia, име за bg търсене, етикет)
    jobs = []
    for z in zones:
        jobs.append(('zone/' + z['id'], 'zone-' + z['id'], z['wiki'], None, 'Зона: ' + z['name']))
    for s in species:
        if s['photo']:
            print('пропускам %s – има собствен файл (photo:)' % s['id'])
            continue
        jobs.append(('species/' + s['id'], s['id'], s['latin'], s['name'], 'Вид: ' + s['name']))

    credits = {}
    missing = []
    for key, base_name, en_title, bg_name, label in jobs:
        print(label)
        entry = fetch_one(base_name, en_title, bg_name, ua, opts.skip_existing)
        if entry:
            credits[key] = entry
        else:
            missing.append(label)

    write_photos_js(credits)
    print()
    print('Готово: снимки за %d от %d. Записани са в data/photos.js.' % (len(credits), len(jobs)))
    if missing:
        print('Без снимка (сложете свой файл в img/ и добавете photo: "img/..." в content.js):')
        for label in missing:
            print('  - ' + label)
    bg_used = [k for k, v in credits.items() if v.get('origin') == 'bg']
    if bg_used:
        print('Снимки от българската Уикипедия (проверете ги): ' + ', '.join(bg_used))


if __name__ == '__main__':
    main()
