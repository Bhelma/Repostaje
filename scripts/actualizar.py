"""Descarga los precios de carburantes del Ministerio y guarda un JSON ligero.

Descarga toda España pidiendo las 52 provincias de una en una, con pausas (pedirla entera de golpe
es muy lento, y muchas peticiones a la vez hacen que el servidor del Ministerio corte la conexión). Para limitar la zona, pon códigos INE en PROVINCIAS
(46 Valencia, 12 Castellón, 03 Alicante...). Lista vacía = toda España.
"""
import json
import os
import subprocess
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
CABECERAS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-ES,es;q=0.9",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
}


def descargar(prov, timeout=90, intentos=3):
    url = BASE + ("FiltroProvincia/" + prov if prov else "")
    req = urllib.request.Request(url, headers=CABECERAS)
    for intento in range(intentos):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            print(f"Provincia {prov or 'todas'}, intento {intento + 1}: {e}", file=sys.stderr)
        # Segundo camino: curl conecta de otra forma y a veces el servidor lo acepta cuando a Python no.
        d = con_curl(url, timeout)
        if d is not None:
            return d
        time.sleep(10 * (intento + 1))
    return None


def con_curl(url, timeout):
    cmd = ["curl", "-sS", "--compressed", "--max-time", str(timeout)]
    for k, v in CABECERAS.items():
        cmd += ["-H", f"{k}: {v}"]
    try:
        r = subprocess.run(cmd + [url], capture_output=True, timeout=timeout + 10)
        if r.returncode == 0 and r.stdout:
            return json.loads(r.stdout.decode("utf-8"))
        print(f"  curl: {r.stderr.decode('utf-8', 'replace').strip()[:150]}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print(f"  curl: {e}", file=sys.stderr)
    return None


def descargar_todo():
    """Una provincia cada vez, con pausa entre peticiones, para no saturar al servidor."""
    lista = PROVINCIAS or TODAS_LAS_PROVINCIAS
    partes, fallidas = [], []
    for n, p in enumerate(lista):
        d = descargar(p)
        if d and d.get("ListaEESSPrecio"):
            partes.append(d)
        else:
            fallidas.append(p)
            # Si fallan las tres primeras, el servidor nos está rechazando: no insistir más.
            if n == 2 and not partes:
                raise SystemExit("El servidor del Ministerio rechaza la conexión desde GitHub. "
                                 "Se reintentará en la próxima ejecución.")
        time.sleep(1.5)
    if fallidas:
        print("Provincias sin datos: " + ", ".join(fallidas), file=sys.stderr)
    if len(partes) < max(1, int(len(lista) * 0.75)):
        raise SystemExit(f"Solo se han podido descargar {len(partes)} provincias de {len(lista)}")
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
                (e.get("IDProvincia") or "").strip(),
            ])
    if not estaciones:
        raise SystemExit("La respuesta no trae estaciones; no se sobrescribe el fichero")
    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8") as f:
        json.dump({
            "fecha": fecha,
            "campos": ["rotulo", "direccion", "localidad", "lat", "lon",
                       "gasoleoA", "gasoleoPremium", "gasolina95", "horario", "provincia"],
            "estaciones": estaciones,
        }, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(estaciones)} estaciones, datos del {fecha}")


if __name__ == "__main__":
    main()
