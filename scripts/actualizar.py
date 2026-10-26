"""Descarga los precios de carburantes del Ministerio y guarda un JSON ligero.

Provincias: cambia la lista PROVINCIAS (códigos INE: 46 Valencia, 12 Castellón, 03 Alicante...).
"""
import json
import os
import sys
import time
import urllib.request

PROVINCIAS = ["46"]
BASE = ("https://sedeaplicaciones.minetur.gob.es/ServiciosRESTCarburantes/"
        "PreciosCarburantes/EstacionesTerrestres/FiltroProvincia/")
SALIDA = os.path.join(os.path.dirname(__file__), "..", "data", "precios.json")


def num(s):
    s = (s or "").strip().replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def descargar(prov):
    req = urllib.request.Request(BASE + prov, headers={
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (repostaje-giulia)",
    })
    for intento in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"Provincia {prov}, intento {intento + 1}: {e}", file=sys.stderr)
            time.sleep(10)
    raise SystemExit(f"No se pudo descargar la provincia {prov}")


def main():
    estaciones, fecha = [], ""
    for prov in PROVINCIAS:
        datos = descargar(prov)
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
