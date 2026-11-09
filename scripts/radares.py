"""Descarga los radares de España y guarda un JSON ligero para la app (data/radares.json).

Fuentes:
  1. DGT (oficial): radares fijos y de tramo de toda España salvo Cataluña y País Vasco.
     https://nap.dgt.es/datex2/dgt/PredefinedLocationsPublication/radares/content.xml
  2. OpenStreetMap: cámaras de velocidad (incluye Cataluña, País Vasco y muchos radares municipales)
     y el límite de velocidad, que la DGT no publica.

Formato de cada radar: [tipo, lat, lon, vmax, rumbo, carretera, lat2, lon2]
  tipo: "F" fijo, "T" tramo (lat/lon = inicio, lat2/lon2 = fin)
  vmax: km/h o null si no se sabe
  rumbo: grados (0 = norte) del sentido que controla, o null si no se sabe
"""
import json
import math
import os
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

DGT = "https://nap.dgt.es/datex2/dgt/PredefinedLocationsPublication/radares/content.xml"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
SALIDA = os.path.join(os.path.dirname(__file__), "..", "data", "radares.json")
UA = {"User-Agent": "MiGiulia/1.0 (app personal; github.com/Bhelma/Repostaje)"}


def bajar(url, datos=None, timeout=300):
    req = urllib.request.Request(url, data=datos, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def overpass(consulta):
    ultimo = None
    for intento in range(3):
        for url in OVERPASS:
            try:
                return json.loads(bajar(url, urllib.parse.urlencode({"data": consulta}).encode()))
            except Exception as e:  # noqa: BLE001
                ultimo = e
                print(f"  Overpass {url} falló: {e}")
        time.sleep(30 * (intento + 1))
    raise RuntimeError(f"Overpass no responde: {ultimo}")


def dist_m(a, b, c, d):
    r = math.pi / 180
    x = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(x))


def rumbo(a, b, c, d):
    r = math.pi / 180
    y = math.sin((d - b) * r) * math.cos(c * r)
    x = math.cos(a * r) * math.sin(c * r) - math.sin(a * r) * math.cos(c * r) * math.cos((d - b) * r)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def velocidad(txt):
    """'100', '100 mph', 'ES:urban'... -> km/h o None."""
    if not txt:
        return None
    t = str(txt).split(";")[0].strip().lower()
    if t.endswith("mph"):
        try:
            return round(float(t[:-3]) * 1.609)
        except ValueError:
            return None
    try:
        v = int(float(t))
        return v if 10 <= v <= 150 else None
    except ValueError:
        return {"es:urban": 50, "es:rural": 90, "es:motorway": 120, "es:trunk": 100}.get(t)


# ---------- DGT ----------

def sin_ns(tag):
    return tag.split("}", 1)[-1]


def hijos(e, nombre):
    return [h for h in e if sin_ns(h.tag) == nombre]


def todos(e, nombre):
    return [h for h in e.iter() if sin_ns(h.tag) == nombre]


def texto(e, nombre):
    for h in e.iter():
        if sin_ns(h.tag) == nombre and (h.text or "").strip():
            return h.text.strip()
    return ""


def coords(e):
    """Lista de (lat, lon) de todos los pointCoordinates dentro de e."""
    r = []
    for pc in todos(e, "pointCoordinates"):
        try:
            r.append((float(texto(pc, "latitude")), float(texto(pc, "longitude"))))
        except ValueError:
            pass
    return r


def leer_dgt(xml):
    raiz = ET.fromstring(xml)
    radares = []
    for conjunto in todos(raiz, "predefinedLocationSet"):
        nombre_set = (texto(conjunto, "value") or conjunto.get("id", "")).lower()
        es_tramo_set = "media" in nombre_set or "tramo" in nombre_set
        for loc in hijos(conjunto, "predefinedLocation"):
            carretera = texto(loc, "roadNumber") or texto(loc, "value")
            desde = [p for p in todos(loc, "from")]
            hasta = [p for p in todos(loc, "to")]
            if desde and hasta:
                a, b = coords(desde[0]), coords(hasta[0])
                if a and b:
                    radares.append({"t": "T", "lat": a[0][0], "lon": a[0][1], "lat2": b[0][0], "lon2": b[0][1],
                                    "carretera": carretera, "rumbo": round(rumbo(a[0][0], a[0][1], b[0][0], b[0][1]))})
                    continue
            c = coords(loc)
            if not c:
                continue
            if es_tramo_set and len(c) >= 2:
                radares.append({"t": "T", "lat": c[0][0], "lon": c[0][1], "lat2": c[-1][0], "lon2": c[-1][1],
                                "carretera": carretera, "rumbo": round(rumbo(c[0][0], c[0][1], c[-1][0], c[-1][1]))})
            else:
                radares.append({"t": "F", "lat": c[0][0], "lon": c[0][1], "carretera": carretera, "rumbo": None})
    return radares


# ---------- OpenStreetMap ----------

CONSULTA_OSM = """[out:json][timeout:600];
area["ISO3166-1"="ES"][admin_level=2]->.es;
(
  node["highway"="speed_camera"](area.es);
  relation["type"="enforcement"]["enforcement"~"^(maxspeed|average_speed)$"](area.es);
);
out body;
>;
out skel qt;
"""


def leer_osm(j):
    nodos, camaras, rels = {}, [], []
    for e in j.get("elements", []):
        if e["type"] == "node":
            nodos[e["id"]] = e
            if (e.get("tags") or {}).get("highway") == "speed_camera":
                camaras.append(e)
        elif e["type"] == "relation":
            rels.append(e)
    # Límite y sentido de las relaciones enforcement (device = radar, from = por dónde llegas)
    por_dispositivo = {}
    tramos = []
    for r in rels:
        tg = r.get("tags") or {}
        v = velocidad(tg.get("maxspeed"))
        dev = [m["ref"] for m in r.get("members", []) if m["type"] == "node" and m.get("role") == "device"]
        frm = [m["ref"] for m in r.get("members", []) if m["type"] == "node" and m.get("role") == "from"]
        to = [m["ref"] for m in r.get("members", []) if m["type"] == "node" and m.get("role") == "to"]
        if tg.get("enforcement") == "average_speed" and frm and to and frm[0] in nodos and to[0] in nodos:
            a, b = nodos[frm[0]], nodos[to[0]]
            tramos.append({"t": "T", "lat": a["lat"], "lon": a["lon"], "lat2": b["lat"], "lon2": b["lon"], "vmax": v,
                           "rumbo": round(rumbo(a["lat"], a["lon"], b["lat"], b["lon"])), "carretera": tg.get("name", "")})
            continue
        for d in dev:
            info = {"vmax": v}
            if frm and frm[0] in nodos and d in nodos:
                a, b = nodos[frm[0]], nodos[d]
                info["rumbo"] = round(rumbo(a["lat"], a["lon"], b["lat"], b["lon"]))
            por_dispositivo[d] = info
    fijos = []
    for c in camaras:
        tg = c.get("tags") or {}
        info = por_dispositivo.get(c["id"], {})
        v = velocidad(tg.get("maxspeed")) or info.get("vmax")
        rb = info.get("rumbo")
        if rb is None and tg.get("direction", "").replace(".", "").isdigit():
            rb = round(float(tg["direction"])) % 360
        fijos.append({"t": "F", "lat": c["lat"], "lon": c["lon"], "vmax": v, "rumbo": rb, "carretera": tg.get("ref", "")})
    return fijos, tramos


def limites_por_via(radares):
    """Límite de la vía donde está cada radar sin velocidad (consulta a OSM por lotes)."""
    sin = [r for r in radares if r.get("vmax") is None]
    print(f"Buscando el límite de la vía para {len(sin)} radares…")
    for i in range(0, len(sin), 150):
        lote = sin[i:i + 150]
        partes = ["[out:json][timeout:300];"]
        for k, r in enumerate(lote):
            partes.append(f'way(around:20,{r["lat"]},{r["lon"]})["highway"]["maxspeed"];out tags;make sep k={k};out;')
        try:
            j = overpass("\n".join(partes))
        except RuntimeError as e:
            print(f"  lote {i}: {e}")
            continue
        actuales = []
        for e in j.get("elements", []):
            if e["type"] == "sep":
                k = int(e["tags"]["k"])
                vs = sorted({v for v in (velocidad((w.get("tags") or {}).get("maxspeed")) for w in actuales) if v})
                if len(vs) == 1:   # solo si no hay duda (cruces con varias vías y límites distintos: se deja sin dato)
                    lote[k]["vmax"] = vs[0]
                actuales = []
            else:
                actuales.append(e)
        time.sleep(5)


def unir(dgt, osm_fijos, osm_tramos):
    """DGT manda; de OSM se toma el límite y el sentido si hay una cámara a menos de 150 m, y se añaden las que faltan."""
    usados = set()
    for r in dgt:
        if r["t"] != "F":
            continue
        mejor, md = None, 150
        for i, o in enumerate(osm_fijos):
            if abs(o["lat"] - r["lat"]) > 0.002 or abs(o["lon"] - r["lon"]) > 0.003:
                continue
            d = dist_m(r["lat"], r["lon"], o["lat"], o["lon"])
            if d < md:
                mejor, md = i, d
        if mejor is not None:
            usados.add(mejor)
            o = osm_fijos[mejor]
            r["vmax"] = r.get("vmax") or o["vmax"]
            r["rumbo"] = r.get("rumbo") if r.get("rumbo") is not None else o["rumbo"]
    extra = [o for i, o in enumerate(osm_fijos) if i not in usados]
    tramos_dgt = [r for r in dgt if r["t"] == "T"]
    for t in osm_tramos:
        cerca = [r for r in tramos_dgt if dist_m(r["lat"], r["lon"], t["lat"], t["lon"]) < 300]
        if cerca:
            for r in cerca:
                r["vmax"] = r.get("vmax") or t["vmax"]
        else:
            extra.append(t)
    return dgt + extra


def main():
    dgt, fuentes = [], []
    try:
        dgt = leer_dgt(bajar(DGT, timeout=120))
        fuentes.append(f"DGT ({len(dgt)})")
        print(f"DGT: {sum(r['t'] == 'F' for r in dgt)} fijos y {sum(r['t'] == 'T' for r in dgt)} tramos")
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo leer la DGT: {e}")
    osm_fijos, osm_tramos = [], []
    try:
        osm_fijos, osm_tramos = leer_osm(overpass(CONSULTA_OSM))
        fuentes.append(f"OpenStreetMap ({len(osm_fijos) + len(osm_tramos)})")
        print(f"OSM: {len(osm_fijos)} cámaras y {len(osm_tramos)} tramos")
    except Exception as e:  # noqa: BLE001
        print(f"No se pudo leer OpenStreetMap: {e}")
    if not dgt and not osm_fijos:
        print("Sin datos: se deja el fichero anterior.")
        return 1
    todos_r = unir(dgt, osm_fijos, osm_tramos)
    if os.environ.get("SIN_LIMITES_VIA") != "1":
        limites_por_via(todos_r)
    # Si la descarga ha salido rara (muchos menos que la vez anterior), no se pisa el fichero bueno
    try:
        antes = len(json.load(open(SALIDA, encoding="utf-8"))["radares"])
        if len(todos_r) < antes * 0.7:
            print(f"Solo {len(todos_r)} radares frente a {antes} la vez anterior: no se actualiza.")
            return 1
    except Exception:  # noqa: BLE001
        pass
    r5 = lambda x: round(x, 5)  # noqa: E731
    lista = [[r["t"], r5(r["lat"]), r5(r["lon"]), r.get("vmax"), r.get("rumbo"), (r.get("carretera") or "")[:20],
              r5(r["lat2"]) if r.get("lat2") is not None else None, r5(r["lon2"]) if r.get("lon2") is not None else None]
             for r in todos_r]
    con_v = sum(1 for x in lista if x[3])
    out = {"fecha": time.strftime("%d/%m/%Y"), "fuentes": fuentes,
           "campos": ["tipo", "lat", "lon", "vmax", "rumbo", "carretera", "lat2", "lon2"], "radares": lista}
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Guardados {len(lista)} radares ({con_v} con límite conocido).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
