# InmoScout

App de escritorio (Windows) para invertir en vivienda en España: rastrea portales
inmobiliarios, guarda el histórico de precios, calcula la rentabilidad de cada piso,
avisa de chollos y bajadas de precio, muestra los anuncios en un mapa y pide a Claude
un análisis de cada oportunidad.

## Funciones

| Pestaña | Qué hace |
|---|---|
| **Oportunidades** | Tabla ordenable de anuncios con €/m², % bajo la mediana de la zona, alquiler estimado, rentabilidad bruta, cash flow y nota de la IA. Doble clic → ficha. |
| **Ficha** | Calculadora en vivo (entrada, gastos, hipoteca, vacío, gastos, reforma), histórico de precio y análisis con Claude (nota 0-100, veredicto, pros/contras, señales de alerta, preguntas al vendedor, oferta sugerida). |
| **Mapa** | Anuncios coloreados según lo baratos que son frente a su zona. |
| **Búsquedas** | Búsquedas guardadas por portal, operación, ubicación y filtros. |
| **Alertas** | Chollos y bajadas de precio. También salen como notificación de Windows. |
| **Ajustes** | Intervalo de rastreo, hipótesis financieras, umbrales de chollo, API keys. |

La app sigue en la bandeja del sistema al cerrar la ventana y rastrea cada N minutos.

### Cómo estima la rentabilidad
La app usa **sus propios datos**: con una búsqueda de *venta* y otra de *alquiler* en la
misma zona calcula el €/m² mediano de cada una. Alquiler estimado = €/m² alquiler × m².
Si la zona tiene menos comparables que el mínimo configurado, usa toda la ciudad.
Puedes sobrescribir el alquiler de cualquier anuncio desde su ficha.

Un anuncio de venta es **chollo** si está ≥ X % bajo la mediana de €/m² o su
rentabilidad bruta estimada supera el umbral (ambos configurables).

## Portales

| Portal | Método | Ubicación |
|---|---|---|
| pisos.com | Rastreo del HTML de los listados | fragmento de URL, p. ej. `valencia_capital` (de `pisos.com/venta/pisos-valencia_capital/`) |
| Idealista | [API oficial](https://developers.idealista.com) (pide credenciales gratis) | `lat,lon,radio_m`, p. ej. `40.4168,-3.7038,2000` |

**Sobre Fotocasa, Habitaclia e idealista.com:** sus condiciones de uso prohíben el
scraping y tienen sistemas antibot (DataDome, captchas). Por eso Idealista va por su API.
El rastreador es educado: respeta `robots.txt`, espera unos segundos entre peticiones
y se detiene si el portal bloquea. Úsalo para uso personal y con moderación.

Para añadir un portal: crea una subclase de `BaseScraper` en `app/scrapers/` que
devuelva objetos `Listing` y regístrala en `app/scrapers/__init__.py`.

## Ejecutar en desarrollo

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
python main.py
```

## Generar el .exe para Windows

```bash
build_windows.bat
```

Resultado: `dist\InmoScout\InmoScout.exe` (carpeta autocontenida, no hace falta Python).

## Datos

Todo se guarda en `%APPDATA%\InmoScout\`: `inmoscout.db` (SQLite), `settings.json`,
`geocache.json` y `inmoscout.log`.

## Tests

```bash
pytest
```

## Estructura

```
main.py                 punto de entrada
app/models.py           Listing, Search
app/db.py               SQLite: anuncios, histórico de precios, búsquedas, alertas
app/finance.py          hipoteca, rentabilidad bruta/neta, cash flow, cash-on-cash
app/market.py           medianas de €/m² por zona, alquiler estimado, detección de chollos
app/crawler.py          una pasada de rastreo completa
app/geocode.py          coordenadas aproximadas por zona (Nominatim/OSM)
app/ai.py               análisis con Claude (salida JSON validada con Pydantic)
app/scrapers/           pisos.com, Idealista API, cliente HTTP educado
app/ui/                 ventana principal, ficha, mapa (Leaflet incluido), diálogos
```
