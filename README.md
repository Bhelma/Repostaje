# Repostaje Giulia

App para el móvil que calcula los litros que echas y muestra los precios de las gasolineras cercanas (datos oficiales del Ministerio, actualizados cada 30 minutos con GitHub Actions).

## Puesta en marcha

1. Crea un repositorio **público** en GitHub (por ejemplo `repostaje`) y sube todo el contenido de esta carpeta, incluida la carpeta oculta `.github`.
2. En el repositorio: **Settings → Actions → General → Workflow permissions** → marca **Read and write permissions** y guarda.
3. **Actions → Actualizar precios → Run workflow** para lanzar la primera descarga. Comprueba que termina en verde y que `data/precios.json` ya tiene estaciones.
4. **Settings → Pages** → *Source*: **Deploy from a branch**, rama `main`, carpeta `/ (root)`.
5. Al cabo de un minuto la app estará en `https://TU_USUARIO.github.io/repostaje/`. Ábrela en el móvil y usa "Añadir a pantalla de inicio".

## Ajustes

- Provincias: edita `PROVINCIAS` en `scripts/actualizar.py` (46 Valencia, 12 Castellón, 03 Alicante…).
- Frecuencia: cambia el `cron` en `.github/workflows/actualizar-precios.yml`.
