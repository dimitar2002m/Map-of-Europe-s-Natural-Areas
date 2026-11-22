#!/usr/bin/env python3
"""
Строи данните за картата от QGIS (qgis2web) слоя с EEA биогеографските региони и от географията на сушата:

  data/zones-geo.js – природните зони (от слоя EEA BiogeoRegions2016)
  data/base-geo.js  – подложката: сивата суша (с Кавказ) и държавните граници
  data/mask-geo.js  – маската: всичко извън сушата (морето и останалите континенти)

Употреба (от папката на проекта):
    pip install shapely
    python3 tools/build_zones.py <път_до_слоя.js>

Зоните са както в учебника (9 зони, от север на юг):
    arctic        – арктически пустини
    tundra        – тундра
    forest_tundra – лесотундра
    taiga         – иглолистни гори (тайга)
    broadleaf     – широколистни и смесени гори
    forest_steppe – лесостепи
    steppe        – степи
    subtropic     – субтропични вечнозелени гори и храсти (вкл. Черноморското крайбрежие и Турция)
    mountain      – планинска област

Сушата е в tools/europe_land.geojson (за зоните) и tools/europe_base.geojson (за подложката).
И двата файла се създават от tools/make_europe_land.py.

Какво прави:
  1. Чете GeoJSON-а от слоя (EEA BiogeoRegions2016).
  2. Съпоставя регионите със зоните. Boreal се дели по ширина на смесени гори, тайга, лесотундра
     и тундра; Arctic – на арктически пустини и тундра; Steppic – на степи и лесостепи;
     Continental – на широколистни гори и лесостепи (Украйна, Черноземната област на Русия).
  3. Отрязва зоните по сушата, така че морето не се защриховава.
  4. Премахва ситните парчета под MIN_PART_KM2 – те се виждат като точки на картата.
  5. Обединява полигоните по зона, опростява (TOLERANCE) и оправя геометрията.
  6. Строи подложката (сушата и границите) и маската (всичко извън сушата в MASK_BOX).

Резултатите се зареждат с <script> тагове, така че работят и от file://.
Границите по ширина са приблизителни. Променете константите по-долу, ако е нужно.
"""
import json
import math
import os
import sys

from shapely import make_valid, set_precision
from shapely.geometry import shape, mapping, box, MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

# Допуск при опростяване в градуси (~1 км при 0.01°).
TOLERANCE = 0.012
# Брой знаци след десетичната точка (4 ≈ 10 м).
DECIMALS = 4
# Части на зона, по-малки от това (км²), се премахват – на картата се виждат като точки.
MIN_PART_KM2 = 20.0

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LAND_FILE = os.path.join(HERE, 'europe_land.geojson')
BASE_FILE = os.path.join(HERE, 'europe_base.geojson')
ZONES_DST = os.path.join(ROOT, 'data', 'zones-geo.js')
BASE_DST = os.path.join(ROOT, 'data', 'base-geo.js')
MASK_DST = os.path.join(ROOT, 'data', 'mask-geo.js')

# Зоните в реда на легендата (от север на юг, както в учебника).
ZONE_ORDER = ["arctic", "tundra", "forest_tundra", "taiga", "broadleaf",
              "forest_steppe", "steppe", "subtropic", "mountain"]

# EEA регион (поле "code") -> зона. None = изключен. "split" = разделя се по ширина (вижте pieces()).
ZONE_OF = {
    "Mediterranean": "subtropic",
    "Macaronesia": "subtropic",    # острови край Африка – обикновено са извън сушата и се отрязват
    "BlackSea": "subtropic",       # в учебника Черноморското крайбрежие е в субтропичната зона
    "Continental": "broadleaf",    # с изключение на лесостепта в FOREST_STEPPE_BOX (вижте pieces())
    "Atlantic": "broadleaf",
    "Pannonian": "forest_steppe",  # Панонската низина е лесостепна
    "Anatolian": "steppe",         # вътрешността на Турция (Анадола) – степи
    "Alpine": "mountain",
    "Boreal": "split",
    "Arctic": "split",
    "Steppic": "split",
    "Outside": None,
}

# Граници по ширина (градуси с.ш.) – приблизителни, сверете с учебника, ако е нужно.
TAIGA_SOUTH_LAT = 60.0    # Boreal на юг от тази ширина са смесени (широколистни) гори, не тайга
TAIGA_NORTH_LAT = 66.5    # Boreal на север от тази ширина е лесотундра (или тундра)
TUNDRA_SOUTH_LAT = 68.0   # Boreal на север от тази ширина е тундра
ARCTIC_DESERT_LAT = 74.0  # Arctic: части с център на север от тази ширина са арктически пустини

# Лесостепният пояс в Украйна и Черноземната област на Русия (между степите и горите).
# Приблизителна линия (дължина, ширина). Важи за регионите Steppic и Continental:
# в него са лесостепите, извън него – степите (Steppic) или широколистните гори (Continental).
FOREST_STEPPE_AREA = Polygon([
    (25.0, 51.6), (27.0, 51.7), (30.0, 51.7), (33.0, 52.0), (36.0, 52.2), (39.0, 52.8),
    (42.0, 53.5), (45.0, 53.6), (48.0, 53.5), (51.5, 53.2), (55.0, 52.8),
    (55.0, 50.0), (50.0, 49.8), (46.0, 49.8), (42.0, 50.2), (39.5, 50.6), (37.5, 50.3),
    (36.0, 49.9), (34.0, 49.3), (32.0, 48.9), (29.5, 48.6), (27.0, 48.4), (25.0, 48.8),
    (24.0, 49.6), (24.6, 50.6),
])

# Маската покрива всичко в този прозорец (дължина/ширина), което не е суша.
MASK_BOX = (-70.0, 5.0, 110.0, 89.0)


def read_qgis_layer(path):
    """qgis2web записва: var json_<име> = {...GeoJSON...};"""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    start = text.index("{")
    end = text.rindex("}") + 1
    return json.loads(text[start:end])


def load_land():
    """Сушата за зоните (europe_land.geojson), като една геометрия."""
    with open(LAND_FILE, encoding="utf-8") as f:
        fc = json.load(f)
    return make_valid(unary_union([shape(f["geometry"]) for f in fc["features"]]))


def load_base():
    """Подложката (europe_base.geojson): сушата с Кавказ и държавните граници."""
    with open(BASE_FILE, encoding="utf-8") as f:
        fc = json.load(f)
    land, borders = None, None
    for feat in fc["features"]:
        kind = feat["properties"].get("kind")
        geom = shape(feat["geometry"])
        if kind == "land":
            land = geom
        elif kind == "borders":
            borders = geom
    if land is None:
        raise SystemExit("В europe_base.geojson липсва сушата (kind: land). Пуснете make_europe_land.py.")
    return make_valid(land), borders


def km2(geom):
    """Приблизителна площ в км² (градуси² × cos(ширина) × 111,32²)."""
    c = geom.centroid
    return geom.area * (111.32 ** 2) * math.cos(math.radians(c.y))


def parts_of(geom):
    """Полигоните в геометрията (и в GeometryCollection, която връщат пресичанията)."""
    if geom is None or geom.is_empty:
        return []
    if geom.geom_type == "MultiPolygon":
        return list(geom.geoms)
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type == "GeometryCollection":
        out = []
        for g in geom.geoms:
            out.extend(parts_of(g))
        return out
    return []


def drop_specks(geom):
    """Връща (геометрия без ситните части, брой премахнати)."""
    parts = parts_of(geom)
    kept = [p for p in parts if km2(p) >= MIN_PART_KM2]
    return (unary_union(kept) if kept else None), len(parts) - len(kept)


def round_coords(obj):
    if isinstance(obj, float):
        return round(obj, DECIMALS)
    if isinstance(obj, (list, tuple)):
        return [round_coords(x) for x in obj]
    return obj


def fix(geom):
    """Оправя невалидна геометрия и ориентира пръстените (външен – обратно на часовниковата,
    дупки – по часовниковата), за да се рисуват правилно дупките."""
    if not geom.is_valid:
        geom = make_valid(geom)
    # Прихващаме координатите към решетка от 0.0001°, после пак проверяваме валидността.
    geom = set_precision(geom, 1e-4)
    if not geom.is_valid:
        geom = make_valid(geom)
    if geom.geom_type == "GeometryCollection":
        geom = unary_union([g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    if geom.geom_type == "Polygon":
        return orient(geom, 1.0)
    if geom.geom_type == "MultiPolygon":
        return MultiPolygon([orient(p, 1.0) for p in geom.geoms])
    return geom


def to_feature(geom, props):
    geom_dict = mapping(fix(geom))
    geom_dict["coordinates"] = round_coords(geom_dict["coordinates"])
    return {"type": "Feature", "properties": props, "geometry": geom_dict}


def write_js(path, var_name, payload, header):
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write(f"var {var_name} = ")
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")


def band(geom, lo, hi):
    """Частта от геометрията между две ширини."""
    return geom.intersection(box(-180, lo, 180, hi))


def pieces(code, geom):
    """Връща списък от (зона, геометрия) за един EEA регион."""
    if code == "Boreal":
        return [
            ("broadleaf", band(geom, -90, TAIGA_SOUTH_LAT)),
            ("taiga", band(geom, TAIGA_SOUTH_LAT, TAIGA_NORTH_LAT)),
            ("forest_tundra", band(geom, TAIGA_NORTH_LAT, TUNDRA_SOUTH_LAT)),
            ("tundra", band(geom, TUNDRA_SOUTH_LAT, 90)),
        ]
    if code == "Continental":
        return [
            ("forest_steppe", geom.intersection(FOREST_STEPPE_AREA)),
            ("broadleaf", geom.difference(FOREST_STEPPE_AREA)),
        ]
    if code == "Steppic":
        return [
            ("forest_steppe", geom.intersection(FOREST_STEPPE_AREA)),
            ("steppe", geom.difference(FOREST_STEPPE_AREA)),
        ]
    if code == "Arctic":
        desert, tundra = [], []
        for p in parts_of(geom):
            (desert if p.centroid.y >= ARCTIC_DESERT_LAT else tundra).append(p)
        return [
            ("arctic", unary_union(desert) if desert else None),
            ("tundra", unary_union(tundra) if tundra else None),
        ]
    zone = ZONE_OF[code]
    return [] if zone is None else [(zone, geom)]


def base_feature(geom, props):
    geom_dict = mapping(fix(geom))
    geom_dict["coordinates"] = round_coords(geom_dict["coordinates"])
    return {"type": "Feature", "properties": props, "geometry": geom_dict}


def write_base(path, land, borders):
    header = ("// Подложка: сушата (сива, с Кавказ) и държавните граници. "
              "Генерирано от tools/build_zones.py от tools/europe_base.geojson.\n")
    land_fc = {"type": "FeatureCollection", "features": [base_feature(land, {"kind": "land"})]}
    border_features = []
    if borders is not None and not borders.is_empty:
        border_features.append(base_feature(borders, {"kind": "borders"}))
    border_fc = {"type": "FeatureCollection", "features": border_features}
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("var BASE_LAND_GEOJSON = ")
        json.dump(land_fc, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\nvar BASE_BORDERS_GEOJSON = ")
        json.dump(border_fc, f, ensure_ascii=False, separators=(",", ":"))
        f.write(";\n")


def main(src):
    data = read_qgis_layer(src)
    land = load_land()
    base_land, borders = load_base()

    by_zone = {}
    eea_by_zone = {}
    for feat in data["features"]:
        code = feat["properties"].get("code")
        if code not in ZONE_OF:
            print("ВНИМАНИЕ: непознат регион:", code, file=sys.stderr)
            continue
        if ZONE_OF[code] is None:
            print(f"{code:14s} -> изключен")
            continue
        for zone, g in pieces(code, shape(feat["geometry"])):
            if g is None or g.is_empty:
                continue
            polys = parts_of(g.intersection(land))
            if not polys:
                continue
            by_zone.setdefault(zone, []).extend(polys)
            eea_by_zone.setdefault(zone, set()).add(code)

    features = []
    total_removed = 0
    for zone in ZONE_ORDER:
        geoms = by_zone.get(zone)
        if not geoms:
            print(f"{zone:14s} – няма данни")
            continue
        merged = unary_union(geoms)
        cleaned, removed = drop_specks(merged)
        total_removed += removed
        if cleaned is None:
            print(f"{zone:14s} – няма останали части след отрязването")
            continue
        cleaned = fix(cleaned.simplify(TOLERANCE, preserve_topology=True))
        features.append(to_feature(cleaned, {
            "id": zone,
            "eea": sorted(eea_by_zone[zone]),
        }))
        print(f"{zone:14s} части премахнати: {removed:5d}  -> {cleaned.geom_type}")

    header = "// Генерирано от tools/build_zones.py от EEA BiogeoRegions2016 (QGIS експорт).\n"
    write_js(ZONES_DST, "ZONES_GEOJSON",
             {"type": "FeatureCollection", "features": features}, header)
    print(f"Общо премахнати ситни части: {total_removed}")
    print("Записан:", ZONES_DST)

    write_base(BASE_DST, base_land, borders)
    print("Записан:", BASE_DST)

    mask = box(*MASK_BOX).difference(base_land)
    write_js(MASK_DST, "EUROPE_MASK_GEOJSON",
             {"type": "FeatureCollection",
              "features": [to_feature(mask, {"id": "mask"})]},
             "// Маска: всичко, което не е суша (морето и останалите континенти). Генерирано от tools/build_zones.py.\n")
    print("Записан:", MASK_DST)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(1)
    main(sys.argv[1])
