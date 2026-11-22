#!/usr/bin/env python3
"""
Създава двата файла с географията на сушата от държавните граници:

  tools/europe_land.geojson – сушата на Европа, Турция, Кипър и Исландия. От нея се строят зоните.
  tools/europe_base.geojson – подложката: сушата заедно с Кавказ (Грузия, Армения, Азербайджан)
                              и държавните граници между страните.

Източник: Natural Earth 1:10 m (публичен домейн), countries-10m.geojson. Лесен начин да го вземете:
    npm install world-atlas@2 topojson-client@3
и превръщане на node_modules/world-atlas/countries-10m.json в GeoJSON (topojson-client, feature).
Файловете са вече в проекта, затова за обикновена употреба не е нужно да ги пускате.

Употреба (от папката на проекта):
    pip install shapely
    python3 tools/make_europe_land.py <countries.geojson>

Какво включва:
  – европейските държави, Турция (цялата), Кипър, Исландия, Фарьорските острови и Гибралтар;
  – Русия само западно от Урал и северно от Кавказ (приблизителна линия);
  – Грузия, Армения и Азербайджан – само в подложката (сиви, без зони).
Какво НЕ включва:
  – Казахстан, Близкият изток и Африка (те са в цвета на морето);
  – отдалечените територии на държавите: Канарските и Азорските острови, Френска Гвиана,
    Карибите, Бувет и др. (режат се с обхватни кутии в CLIP_BOX).
"""
import json
import os
import sys

import numpy as np
import shapely
from shapely import make_valid
from shapely.geometry import shape, box, Polygon, mapping
from shapely.ops import unary_union, linemerge

HERE = os.path.dirname(os.path.abspath(__file__))
DST_LAND = os.path.join(HERE, 'europe_land.geojson')
DST_BASE = os.path.join(HERE, 'europe_base.geojson')

# Имена, както са в world-atlas (Natural Earth)
COUNTRIES = {
    "Albania", "Andorra", "Austria", "Belarus", "Belgium", "Bosnia and Herz.", "Bulgaria",
    "Croatia", "Cyprus", "N. Cyprus", "Czechia", "Denmark", "Estonia", "Faeroe Is.", "Finland",
    "France", "Germany", "Gibraltar", "Greece", "Hungary", "Iceland", "Ireland", "Italy",
    "Kosovo", "Latvia", "Liechtenstein", "Lithuania", "Luxembourg", "Malta", "Moldova", "Monaco",
    "Montenegro", "Netherlands", "Macedonia", "Norway", "Poland", "Portugal", "Romania",
    "San Marino", "Serbia", "Slovakia", "Slovenia", "Spain", "Sweden", "Switzerland", "Turkey",
    "Ukraine", "United Kingdom", "Åland", "Russia",
}

# Кавказ: сиви в подложката, без зони
NEIGHBOURS = {"Georgia", "Armenia", "Azerbaijan"}

# Обхватни кутии (дължина/ширина): махат отдалечените територии на държавите
CLIP_BOX = {
    "France": (-6.0, 41.0, 10.0, 52.0),        # без Френска Гвиана
    "Spain": (-12.0, 27.0, 6.0, 45.0),         # без Канарските острови
    "Portugal": (-12.0, 30.0, 0.0, 45.0),      # без Азорските и Мадейрските острови
    "Netherlands": (-12.0, 40.0, 10.0, 60.0),  # без Карибите
    "United Kingdom": (-12.0, 49.0, 3.0, 62.0),
    "Norway": (-12.0, 30.0, 40.0, 85.0),       # без остров Бувет (далеч на юг)
}

# Русия: западно от Урал и на север от Кавказ (приблизително)
RUSSIA_CLIP = Polygon([
    (-40.0, 30.0), (-40.0, 85.0), (69.5, 85.0), (69.5, 70.0), (67.5, 69.0), (65.5, 66.8),
    (61.5, 65.0), (60.5, 63.0), (59.8, 61.0), (59.0, 59.0), (58.0, 57.5), (58.5, 55.5),
    (58.0, 53.5), (58.6, 51.2), (55.1, 51.8), (53.5, 51.3), (51.4, 51.4), (51.4, 50.0),
    (51.0, 48.5), (51.9, 47.1), (51.3, 46.8), (50.0, 44.5), (48.8, 42.0), (46.5, 42.2),
    (42.5, 43.2), (40.1, 43.0), (40.0, 41.6),
])
RUSSIA_BOX = box(18.0, 41.0, 70.0, 85.0)          # европейската част за зоните
RUSSIA_BORDER_BOX = box(18.0, 38.0, 70.0, 85.0)   # по-широко, за границата с Грузия и Азербайджан

SIMPLIFY_LAND = 0.004   # градуси (~400 m) – за зоните
SIMPLIFY_BASE = 0.012   # градуси (~1,3 km) – за подложката
BORDER_NEAR_LAND = 0.02 # границите се пазят само край сушата
DECIMALS = 4


def round_coords(obj):
    if isinstance(obj, float):
        return round(obj, DECIMALS)
    if isinstance(obj, (list, tuple)):
        return [round_coords(x) for x in obj]
    return obj


def polygons_only(geom):
    """Оставя полигоните (make_valid и пресичанията може да върнат и линии или точки)."""
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type in ('Polygon', 'MultiPolygon'):
        return geom
    if geom.geom_type == 'GeometryCollection':
        polys = [g for g in geom.geoms if g.geom_type in ('Polygon', 'MultiPolygon')]
        return unary_union(polys) if polys else None
    return None


def line_parts(geom):
    """Всички линии от геометрията (LineString, MultiLineString или GeometryCollection)."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == 'LineString':
        return [geom]
    if geom.geom_type == 'MultiLineString':
        return list(geom.geoms)
    if geom.geom_type == 'GeometryCollection':
        out = []
        for g in geom.geoms:
            out.extend(line_parts(g))
        return out
    return []


def unwrap(geom, name):
    """Русия минава през 180° меридиан (Чукотка). Отрицателните дължини се преместват с +360°,
    за да са контурите непрекъснати. Без това make_valid разрушава част от европейска Русия
    (например празнина при 66° с.ш.)."""
    if name != 'Russia':
        return geom

    def shift(coords):
        c = np.array(coords, dtype=float)
        c[c[:, 0] < 0.0, 0] += 360.0
        return c

    return shapely.transform(geom, shift)


def load_countries(fc):
    """Геометриите на държавите от COUNTRIES и NEIGHBOURS (оправени)."""
    out = {}
    for feat in fc['features']:
        name = feat['properties'].get('name')
        if name not in COUNTRIES and name not in NEIGHBOURS:
            continue
        geom = polygons_only(make_valid(unwrap(shape(feat['geometry']), name)))
        if geom is not None:
            out[name] = geom
    return out


def land_part(name, geom):
    """Сушата на държавата без отдалечените ѝ територии."""
    if name == 'Russia':
        return polygons_only(geom.intersection(RUSSIA_CLIP).intersection(RUSSIA_BOX))
    if name in CLIP_BOX:
        return polygons_only(geom.intersection(box(*CLIP_BOX[name])))
    return geom


def border_part(name, geom):
    """Геометрията, в която се търсят общите граници."""
    if name == 'Russia':
        return polygons_only(geom.intersection(RUSSIA_BORDER_BOX))
    return land_part(name, geom)


def shared_borders(parts):
    """Общите граници: пресичане на контурите на всяка двойка съседни държави."""
    names = sorted(parts)
    lines = []
    for i, a in enumerate(names):
        ga = parts[a]
        ax0, ay0, ax1, ay1 = ga.bounds
        for b in names[i + 1:]:
            gb = parts[b]
            bx0, by0, bx1, by1 = gb.bounds
            if ax1 < bx0 or bx1 < ax0 or ay1 < by0 or by1 < ay0:
                continue
            lines.extend(line_parts(ga.boundary.intersection(gb.boundary)))
    return lines


def feature(geom, props):
    g = mapping(geom)
    return {'type': 'Feature', 'properties': props,
            'geometry': {'type': g['type'], 'coordinates': round_coords(g['coordinates'])}}


def write_fc(path, features):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'type': 'FeatureCollection', 'features': features}, f,
                  ensure_ascii=False, separators=(',', ':'))


def main(src):
    with open(src, encoding='utf-8') as f:
        fc = json.load(f)

    geoms = load_countries(fc)
    missing = sorted((COUNTRIES | NEIGHBOURS) - set(geoms))
    if missing:
        print('ВНИМАНИЕ: липсват държави в източника:', ', '.join(missing), file=sys.stderr)

    land_parts = []
    for name in COUNTRIES:
        if name in geoms:
            part = land_part(name, geoms[name])
            if part is not None:
                land_parts.append(part)
    neighbour_parts = [geoms[n] for n in NEIGHBOURS if n in geoms]

    # Зоните: само сушата на Европа, Турция и Исландия
    land_raw = make_valid(unary_union(land_parts))
    zone_land = polygons_only(make_valid(land_raw.simplify(SIMPLIFY_LAND, preserve_topology=True)))

    # Подложката: същата суша + Кавказ
    base_raw = make_valid(unary_union(land_parts + neighbour_parts))
    base_land = polygons_only(make_valid(base_raw.simplify(SIMPLIFY_BASE, preserve_topology=True)))

    # Държавните граници: само край сушата, без ръбовете на отрязаните територии
    border_parts = {}
    for name in COUNTRIES | NEIGHBOURS:
        if name in geoms:
            part = border_part(name, geoms[name])
            if part is not None:
                border_parts[name] = part
    near_land = base_raw.buffer(BORDER_NEAR_LAND)
    lines = line_parts(unary_union(shared_borders(border_parts)).intersection(near_land))
    # Слепваме отсечките в непрекъснати линии (иначе файлът е с хиляди парчета)
    borders = linemerge(lines).simplify(SIMPLIFY_BASE, preserve_topology=True) if lines else None

    write_fc(DST_LAND, [feature(zone_land, {'name': 'Европа, Турция, Кипър и Исландия (суша)'})])
    base_features = [feature(base_land, {'kind': 'land'})]
    if borders is not None and not borders.is_empty:
        base_features.append(feature(borders, {'kind': 'borders'}))
    write_fc(DST_BASE, base_features)

    print('държави:', len(geoms), '| граници (линии):', len(lines))
    print('Записан:', DST_LAND)
    print('Записан:', DST_BASE)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
