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
import functools

# Que cada mensaje salga al momento en el registro de GitHub (si no, Python los guarda hasta el final)
print = functools.partial(print, flush=True)  # noqa: A001

DGT = "https://nap.dgt.es/datex2/dgt/PredefinedLocationsPublication/radares/content.xml"
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
SALIDA = os.path.join(os.path.dirname(__file__), "..", "data", "radares.json")
UA = {"User-Agent": "MiGiulia/1.0 (app personal; github.com/Bhelma/Repostaje)"}


def bajar(url, datos=None, timeout=300):
    req = urllib.request.Request(url, data=datos, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def overpass(consulta, rondas=3, timeout=300):
    ultimo = None
    for intento in range(rondas):
        for url in OVERPASS:
            try:
                return json.loads(bajar(url, urllib.parse.urlencode({"data": consulta}).encode(), timeout))
            except Exception as e:  # noqa: BLE001
                ultimo = e
                print(f"  Overpass {url} falló: {e}")
        if intento < rondas - 1:
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
        # (el «direction» numérico de OSM no se usa: unos lo ponen hacia donde mira la cámara y otros
        #  el sentido que controla; el sentido sale de la calzada en ajustar_por_via)
        fijos.append({"t": "F", "lat": c["lat"], "lon": c["lon"], "vmax": v, "rumbo": rb, "carretera": tg.get("ref", "")})
    return fijos, tramos


HIGHWAYS = "motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link|unclassified|residential"


def _segmento_mas_cercano(lat, lon, geom):
    """(metros, rumbo del segmento en el sentido de los nodos) del tramo de vía más cercano al punto."""
    mejor = (1e9, None)
    k = math.cos(math.radians(lat)) * 111320
    for a, b in zip(geom, geom[1:]):
        ax, ay = (a["lon"] - lon) * k, (a["lat"] - lat) * 110540
        bx, by = (b["lon"] - lon) * k, (b["lat"] - lat) * 110540
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        t = 0 if l2 == 0 else max(0, min(1, -(ax * dx + ay * dy) / l2))
        d = math.hypot(ax + t * dx, ay + t * dy)
        if d < mejor[0]:
            mejor = (d, rumbo(a["lat"], a["lon"], b["lat"], b["lon"]))
    return mejor


def ajustar_por_via(radares):
    """Mira en OpenStreetMap la carretera de cada radar:
    - En calzadas de sentido único (autovías y autopistas, con una calzada para cada sentido) el sentido
      que controla el radar es el de su calzada: esto evita avisar de los radares de la calzada de enfrente.
    - Si falta el límite, el de esa vía (solo si no hay duda).
    """
    print(f"Revisando la vía de {len(radares)} radares…")
    cambiados = puestos = anulados = 0
    inicio = time.time()
    for i in range(0, len(radares), 120):
        # Tope de 45 minutos: si OpenStreetMap va lento, los que falten se quedan como venían
        if time.time() - inicio > 45 * 60:
            print(f"  Tiempo agotado: {len(radares) - i} radares se quedan sin revisar.")
            break
        print(f"  lote {i // 120 + 1}/{(len(radares) + 119) // 120} ({round(time.time() - inicio)} s)")
        lote = radares[i:i + 120]
        partes = ["[out:json][timeout:180];"]
        for k, r in enumerate(lote):
            partes.append(f'way(around:25,{r["lat"]},{r["lon"]})["highway"~"^({HIGHWAYS})$"];out tags geom;make sep k={k};out;')
        try:
            j = overpass("\n".join(partes), rondas=2, timeout=200)
        except RuntimeError as e:
            print(f"  lote {i}: {e}")
            continue
        vias = []
        for e in j.get("elements", []):
            if e["type"] != "sep":
                vias.append(e)
                continue
            r = lote[int(e["tags"]["k"])]
            cands = []
            for w in vias:
                g = w.get("geometry") or []
                if len(g) < 2:
                    continue
                d, rb = _segmento_mas_cercano(r["lat"], r["lon"], g)
                tg = w.get("tags") or {}
                ow = str(tg.get("oneway", "")).lower()
                unico = ow in ("yes", "true", "1", "-1") or tg.get("highway") in ("motorway", "motorway_link") or tg.get("junction") == "roundabout"
                if ow == "-1":
                    rb = (rb + 180) % 360
                cands.append((d, rb, unico, velocidad(tg.get("maxspeed"))))
            vias = []
            if not cands:
                continue
            cands.sort()
            d0, rb0, unico0, v0 = cands[0]
            if r.get("vmax") is None:
                vs = {c[3] for c in cands if c[3] and c[0] <= d0 + 8}
                if len(vs) == 1:
                    r["vmax"] = vs.pop()
            # Un sentido que no va ni en una dirección ni en la otra de la vía está mal anotado (le pasaba al
            # de la A-3 km 247, con 157° en un tramo que va de este a oeste): mejor sin sentido que callado
            if r["t"] == "F" and r.get("rumbo") is not None and d0 <= 30:
                dif = abs((r["rumbo"] - rb0 + 540) % 360 - 180)
                if 40 < dif < 140:
                    r["rumbo"] = None
                    anulados += 1
            if r["t"] != "F" or not unico0 or d0 > 15:
                continue
            # ¿Hay otra calzada de sentido contrario casi igual de cerca? Entonces no se sabe cuál es.
            dudosa = any(c[2] and c[0] - d0 < 4 and abs((c[1] - rb0 + 540) % 360 - 180) > 120 for c in cands[1:])
            if dudosa:
                continue   # se queda con el sentido que traía (si lo tenía)
            if r.get("rumbo") is None:
                puestos += 1
            elif abs((r["rumbo"] - rb0 + 540) % 360 - 180) > 60:
                cambiados += 1
            r["rumbo"] = round(rb0)
        time.sleep(5)
    print(f"  Sentido puesto en {puestos} radares, corregido en {cambiados} y quitado en {anulados} (estaba mal).")


def quitar_repetidos(radares):
    """El mismo radar en la DGT y en OSM, o dos veces en OSM: a menos de 60 m y mismo sentido."""
    quedan = []
    for r in sorted(radares, key=lambda x: (x.get("vmax") is None, x.get("rumbo") is None)):
        rep_ = False
        for q in quedan:
            if q["t"] != r["t"] or abs(q["lat"] - r["lat"]) > 0.001 or abs(q["lon"] - r["lon"]) > 0.0012:
                continue
            if dist_m(q["lat"], q["lon"], r["lat"], r["lon"]) > 60:
                continue
            a, b = q.get("rumbo"), r.get("rumbo")
            if a is None or b is None or abs((a - b + 540) % 360 - 180) < 45:
                rep_ = True
                break
        if not rep_:
            quedan.append(r)
    print(f"Repetidos quitados: {len(radares) - len(quedan)}")
    return quedan


def unir(dgt, osm_fijos, osm_tramos):
    """DGT manda; de OSM se toma el límite y el sentido si hay una cámara a menos de 150 m, y se añaden las que faltan."""
    usados = set()
    for r in dgt:
        if r["t"] != "F":
            continue
        mejor, md = None, 60   # más lejos podría ser la cámara de la otra calzada
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
        ajustar_por_via(todos_r)
    todos_r = quitar_repetidos(todos_r)
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
