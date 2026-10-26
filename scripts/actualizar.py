"""Descarga los precios de carburantes del Ministerio y guarda un JSON ligero.

Por defecto descarga TODA España (unas 11.500 gasolineras), para poder buscar marcas lejos de casa.
Si prefieres solo algunas provincias, pon sus códigos INE en PROVINCIAS (46 Valencia, 12 Castellón, 03 Alicante...).
"""
import json
import os
import sys
import time
import urllib.request

PROVINCIAS = []  # vacío = toda España
BASE = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
        "PreciosCarburantes/EstacionesTerrestres/")
SALIDA = os.path.join(os.path.dirname(__file__), "..", "data", "precios.json")


def num(s):
    s = (s or "").strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


TODAS_LAS_PROVINCIAS = [f"{i:02d}" for i in range(1, 53)]


def descargar(prov, timeout=60, intentos=3, obligatorio=True):
    url = BASE + ("FiltroProvincia/" + prov if prov else "")
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (repostaje-giulia)",
    })
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"Provincia {prov or 'todas'}, intento {intento + 1}: {e}", file=sys.stderr)
            time.sleep(5)
    if obligatorio:
        raise SystemExit(f"No se pudo descargar la provincia {prov or 'todas'}")
    return None


def descargar_todo():
    """Intenta toda España de una vez; si el servidor tarda demasiado, va provincia a provincia."""
    if PROVINCIAS:
        return [descargar(p) for p in PROVINCIAS]
    datos = descargar("", timeout=240, intentos=2, obligatorio=False)
    if datos and datos.get("ListaEESSPrecio"):
        return [datos]
    print("Descarga completa fallida; probando provincia a provincia", file=sys.stderr)
    partes = []
    for p in TODAS_LAS_PROVINCIAS:
        d = descargar(p, timeout=90, intentos=3, obligatorio=False)
        if d:
            partes.append(d)
    if len(partes) < 40:
        raise SystemExit(f"Solo se han podido descargar {len(partes)} provincias de 52")
    return partes


def main():
    estaciones, fecha = [], ""
    for datos in descargar_todo():
        fecha = datos.get("Fecha", fecha)
        for e in datos.get("ListaEESSPrecio", []):
            lat, lon = num(e.get("Latitud")), num(e.get("Longitud (WGS84)"))
            if lat is None or lon is None:
                continue
            estaciones.append([
                (e.get("Rótulo") or "").strip(),
                (e.get("Dirección") or "").strip(),
                (e.get("Localidad") or "").strip(),
                round(lat, 5), round(lon, 5),
                num(e.get("Precio Gasoleo A")),
                num(e.get("Precio Gasoleo Premium")),
                num(e.get("Precio Gasolina 95 E5")),
                (e.get("Horario") or "").strip(),
            ])
    if not estaciones:
        raise SystemExit("La respuesta no trae estaciones; no se sobrescribe el fichero")
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump({
            "fecha": fecha,
            "campos": ["rotulo", "direccion", "localidad", "lat", "lon",
                       "gasoleoA", "gasoleoPremium", "gasolina95", "horario"],
            "estaciones": estaciones,
        }, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(estaciones)} estaciones, datos del {fecha}")


if __name__ == "__main__":
    main()
