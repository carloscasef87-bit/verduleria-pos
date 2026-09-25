# Verdulería al Peso

Punto de venta para una verdulería, pensado para usarse desde el teléfono. La caja vende y la
dirección carga productos, precios y stock; los datos viven en un servidor pequeño (Flask +
SQLite) para que varios teléfonos vean lo mismo.

- **Demo en Railway (la que se le deja al cliente):** https://verduleria-pos-production.up.railway.app
- Demo estática con datos inventados (sin servidor): https://carloscasef87-bit.github.io/verduleria-pos/

## Qué hace

- **Vender** (la caja): rejilla con los productos encendidos, cada uno con su ilustración
  animada, su precio y su **nivel 0–100**. Se toca el producto, se teclea el peso de la báscula
  (kg o gramos) o «por dinero» («deme $20 de limón») y se agrega al ticket. Cobrar calcula el
  cambio, descuenta la existencia y ofrece **enviar el ticket por WhatsApp** (al número del
  cliente o eligiendo el contacto).
- **Dashboard**: vendido hoy contra ayer, tickets, kilos, ventas de 7 días en gráfica, lo que
  más se vende y la lista de productos por reponer.
- **Dirección** (el dueño): catálogo de 51 frutas y verduras comunes, todo apagado al inicio.
  En una sola tabla enciende lo que vende, escribe el precio y el stock actual (lo que guarda
  queda declarado como nivel 100). Puede crear productos nuevos con nombre, descripción,
  unidad (kilo, pieza o manojo), precio e ilustración, emoji o foto. Debajo, producto por
  producto: declarar entradas, ajustar por conteo o merma, editar, últimos movimientos.
- **Corte**: ventas del día por producto, tickets (cada uno con botón de WhatsApp) y entradas.
- **Ajustes**: nombre del negocio, moneda, PIN de dirección, respaldo, datos de ejemplo,
  empezar en limpio, borrar todo.

## El nivel 0–100

Cuando la dirección declara stock (entrada o carga), esa cantidad se vuelve el **declarado**
(nivel 100). Cada venta baja la existencia y el nivel es `existencia / declarado × 100`.
0 = se acabó. Verde ≥ 50, ámbar 20–49, rojo < 20.

## Sin señal

Si el teléfono pierde la señal, la caja sigue vendiendo: cada venta se guarda en el teléfono y
se envía sola cuando vuelve la conexión (una franja arriba avisa cuántas hay pendientes). Las
tareas de dirección sí necesitan conexión.

## Instalar en el teléfono

Abrir la dirección en Chrome (Android) o Safari (iPhone) y «Agregar a pantalla de inicio».
Queda como una app con ícono propio.

## Cómo corre

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
DATOS_DIR=./datos .venv/bin/python servidor.py      # http://localhost:8080
```

`index.html` es el mismo archivo en los dos modos: si encuentra `api/estado` trabaja contra el
servidor; si no (GitHub Pages, un archivo abierto a mano), guarda en el navegador.

## Railway

Proyecto `verduleria-pos`, servicio `verduleria-pos`, volumen montado en `/data` y variable
`DATOS_DIR=/data` (ahí viven `verduleria.db` y `secreto.txt`). Se despliega con `railway up`
desde esta carpeta. Un solo worker de gunicorn (SQLite).

## API

| Ruta | Quién | Qué hace |
|---|---|---|
| `GET /api/estado` | todos | productos, negocio y últimos 60 días de ventas y movimientos |
| `POST /api/ventas` | caja | registra una venta (idempotente por `id`) y descuenta stock |
| `POST /api/pin` | caja | cambia el PIN por un token (`X-Token`) para las rutas de dirección |
| `POST /api/carga` | dirección | precio y stock actual de varios productos |
| `POST /api/entradas`, `/api/ajustes` | dirección | entrada de mercancía, conteo o merma |
| `POST/PUT/DELETE /api/productos[/id]`, `POST /api/productos/id/activo` | dirección | alta, edición, baja, encender/apagar |
| `PUT /api/negocio` | dirección | nombre, moneda, PIN |
| `POST /api/ejemplo`, `/api/limpio`, `/api/borrar`, `/api/restaurar` | dirección | datos de demostración, limpieza y respaldo |

## Límites que hay que saber

- No se conecta a la báscula: el peso se teclea.
- El PIN protege las pantallas de dirección, no es una autenticación fuerte.
- Un negocio por instalación; para otra verdulería se despliega otra copia.
