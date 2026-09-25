# Verdulería al Peso

Punto de venta para una verdulería, en un solo archivo (`index.html`). Sin servidor, sin
instalación: se abre en el navegador de una tableta o un teléfono y los datos se guardan en ese
navegador.

## Qué hace

- **Vender** (la caja): rejilla con los productos encendidos, cada uno con su ilustración
  animada, su precio por kilo y su **nivel 0–100**. Se toca el producto, se teclea el peso de la
  báscula (kg o gramos) o «por dinero» («deme $20 de limón») y se agrega al ticket. Cobrar
  calcula el cambio y descuenta la existencia.
- **Dashboard**: vendido hoy contra ayer, tickets, kilos, ventas de los últimos 7 días en
  gráfica (con tabla), lo que más se vende y la lista de productos por reponer.
- **Dirección** (el dueño): tabla para cargar de una vez el precio del kilo y el stock actual
  de todos los productos (lo que se guarda como stock queda declarado como nivel 100), prender
  o apagar cada uno, y debajo, producto por producto: declarar entradas, ajustar por conteo o
  merma, editar y crear productos, últimos movimientos.
- **Corte**: ventas del día por producto, tickets y entradas, con selector de fecha.
- **Ajustes**: nombre del negocio, moneda, PIN opcional para que la caja no entre a Dirección,
  respaldo (copiar/pegar o archivo), cargar los 8 productos de ejemplo, borrar todo.

## El nivel 0–100

Cuando el verdulero declara una entrada, la existencia sube y ese total se convierte en el
**declarado** (nivel 100). Cada venta baja la existencia y el nivel es
`existencia / declarado × 100`. 0 = se acabó. Colores: verde ≥ 50, ámbar 20–49, rojo < 20.

## Ilustraciones

15 ilustraciones animadas en SVG (plátano, manzana, melón, sandía, limón, cilantro, perejil,
aguacate, jitomate, cebolla, naranja, zanahoria, papa, chile y una canasta genérica). Cualquier
producto puede usar en su lugar un emoji o una foto/GIF subida desde el dispositivo (la foto se
reduce a 256 px para que quepa en el navegador; un GIF menor a 400 KB se conserva animado).

## Límites que hay que saber

- Los datos viven en el navegador donde se abre. Si se borra el historial del navegador, se
  pierden. Por eso existe «Copiar respaldo» en Ajustes.
- No se conecta a la báscula: el peso se teclea a mano. Conectar una báscula con puerto serie
  o USB es un siguiente paso posible.
- Un solo dispositivo por verdulería; no sincroniza entre dos cajas.

## Publicado

GitHub Pages: https://carloscasef87-bit.github.io/verduleria-pos/
