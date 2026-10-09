# Verdulería al Peso

Punto de venta para una verdulería, pensado para usarse desde el teléfono. La caja vende y la
dirección carga productos, precios y stock; los datos viven en un servidor pequeño (Flask +
SQLite) para que varios teléfonos vean lo mismo.

- **Demo en Railway (la que se le deja al cliente):** https://verduleria-pos-production.up.railway.app
- Demo estática con datos inventados (sin servidor): https://carloscasef87-bit.github.io/verduleria-pos/

## Varias verdulerías, varias sucursales

Un solo servidor sirve a muchas verdulerías. Cada dueño crea su **cuenta** (correo y
contraseña) y tiene una o más **sucursales**; cada sucursal tiene su catálogo, precios, stock,
ventas y una **clave de caja** de 6 letras.

- **Punto de venta**: el teléfono de la caja abre la dirección y escribe la clave de caja (o
  abre el enlace `?caja=CLAVE` que el dueño le manda por WhatsApp). Solo ve la pantalla de vender.
  No necesita cuenta. Si el dueño cambia la clave, ese teléfono deja de vender hasta escribir la nueva.
- **Dirección**: el dueño entra con su correo. Arriba elige la sucursal; el Dashboard tiene
  «Esta sucursal / Todas» para comparar puestos. En Ajustes crea sucursales (copiando el
  catálogo y los precios de otra si quiere), ve la clave de caja de cada una y cambia su cuenta.
- Crear cuenta pide un **código de invitación** (variable `CODIGO_ALTA` en Railway) tanto con correo
  como con Google. Sin la variable, el registro queda abierto.
- **Con Google**: si existe la variable `GOOGLE_CLIENT_ID` (ID de cliente OAuth de tipo
  «aplicación web», con el dominio de Railway como origen autorizado), aparece «Continuar con
  Google» y la cuenta se crea con el Gmail verificado, sin contraseña. Esa cuenta puede ponerse
  una contraseña después en Ajustes → Mi cuenta. El servidor valida el token con
  `oauth2.googleapis.com/tokeninfo`.

## Qué hace

- **Vender** (la caja): rejilla con los productos encendidos, cada uno con su ilustración
  animada, su precio y su **nivel 0–100**. Se toca el producto, se teclea el peso de la báscula
  (kg o gramos) o «por dinero» («deme $20 de limón») y se agrega al ticket. Cobrar calcula el
  cambio, descuenta la existencia y ofrece **enviar el ticket por WhatsApp** (al número del
  cliente o eligiendo el contacto). Si el producto tiene precio de mayoreo, entra solo al llegar
  a la cantidad mínima y el cajero puede forzarlo o quitarlo.
- **Dashboard**: vendido hoy contra ayer, tickets, kilos, ganancia estimada del día (precio
  menos costo, si el dueño cargó costos), ventas de 7 días en gráfica, lo que más se vende y la
  lista de productos por reponer.
- **Dirección** (el dueño): catálogo de 51 frutas y verduras comunes, todo apagado al inicio.
  En una sola tabla enciende lo que vende, escribe el precio y el stock actual (lo que guarda
  queda declarado como nivel 100). Puede crear productos nuevos con nombre, descripción,
  unidad (kilo, pieza o manojo), **costo**, **precio de menudeo**, **precio de mayoreo** con cantidad mínima, e
  ilustración, emoji o foto. Debajo, producto por
  producto: declarar entradas, ajustar por conteo o merma, editar, últimos movimientos.
- **Corte**: ventas del día por producto, tickets (cada uno con botón de WhatsApp) y entradas.
- **Ajustes**: nombre del negocio, moneda, PIN de dirección, respaldo, datos de ejemplo,
  empezar en limpio, borrar todo.

## El nivel 0–100

Cuando la dirección declara stock (entrada o carga), esa cantidad se vuelve el **declarado**
(nivel 100). Cada venta baja la existencia y el nivel es `existencia / declarado × 100`.
0 = se acabó. Verde ≥ 50, ámbar 20–49, rojo < 20.

## Página de operador

`/operador` (con la variable `CLAVE_OPERADOR`) muestra el avance de todas las cuentas: sucursales,
productos encendidos, con stock y con costo, tickets, vendido, última venta, última carga y ventas
de los últimos 7 días. También la **ganancia y el margen** de cada cliente: el de lo vendido (con el
costo que tenía cada línea al venderse; las líneas sin costo no cuentan) y el promedio del catálogo
encendido, con aviso de productos que se venden con pérdida. Cifras agregadas, sin tickets.

## Versiones

Cada respuesta del servidor trae su versión; si la página abierta en un teléfono es más vieja,
se recarga sola. Así una pestaña o app que se quedó abierta no sigue llamando rutas que ya no
existen.

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
`DATOS_DIR=/data` (ahí vive `verduleria.db`). Se despliega con `railway up` desde esta carpeta
(ver «Desplegar un cambio»).
Un solo worker de gunicorn (SQLite). Las variables `MIGRACION_CORREO` y `MIGRACION_CONTRASENA`
solo se usaron una vez, para convertir la base de un solo negocio en la primera cuenta.

## Desplegar un cambio

Siempre en este orden, para que GitHub y Railway tengan exactamente lo mismo:

1. **Probar en local** (`DATOS_DIR=./datos python servidor.py`) la pantalla que cambió, en
   computadora y en teléfono.
2. **Versión**: si cambió `index.html`, subir `VERSION` en `servidor.py` **y** en `index.html`
   al mismo valor (`AAAA-MM-DD.n`); si cambió `index.html`, `manifest.webmanifest` o `icono.svg`,
   subir también `CACHE` en `sw.js`. Si solo cambió el servidor u otra página (`operador.html`,
   `terminos.html`…), **no** tocar `VERSION`: con valores distintos los teléfonos se recargarían
   sin parar.
3. **Commit** en `main` con todo lo que va a salir: `git status` debe quedar limpio.
4. **`git push origin main`**: GitHub queda como copia de lo que corre (y actualiza la demo de
   GitHub Pages).
5. **`railway up --ci`** desde esta carpeta y con el árbol limpio: `railway up` sube los archivos
   tal como están en el disco, no el último commit.
6. **Comprobar**: `/api/salud` responde y la pantalla cambiada se ve bien en producción.

## API

| Ruta | Quién | Qué hace |
|---|---|---|
| `GET /api/estado` | todos | dice que hay servidor multi-negocio y si el alta está abierta |
| `POST /api/cuentas`, `POST/DELETE /api/sesion`, `GET/PUT /api/mi` | dueño | crear cuenta, entrar y salir (`X-Sesion`), ver y editar la cuenta |
| `GET /api/mi/resumen` | dueño | ventas de 8 días y alertas de todas las sucursales |
| `POST /api/mi/sucursales`, `PUT/DELETE …/<id>`, `POST …/<id>/clave` | dueño | crear, editar, borrar sucursal, nueva clave de caja |
| `GET /api/mi/sucursales/<id>/estado` | dueño | productos y últimos 60 días de esa sucursal |
| `POST …/<id>/ventas`, `entradas`, `ajustes`, `carga`, `productos…`, `ejemplo`, `limpio`, `borrar`, `restaurar` | dueño | operaciones de la sucursal |
| `GET /api/c/<clave>/estado`, `POST /api/c/<clave>/ventas` | caja | lo único que puede hacer un teléfono de punto de venta |

## Límites que hay que saber

- No se conecta a la báscula: el peso se teclea.
- La clave de caja es un secreto de 6 letras: quien la tenga puede vender en esa sucursal (no
  puede ver ni cambiar nada más). Se cambia desde Ajustes.
- Una base SQLite para todas las cuentas; sirve para decenas de verdulerías. Más allá, Postgres.
