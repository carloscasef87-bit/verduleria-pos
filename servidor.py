"""Verdulería al Peso: servidor.

Flask + SQLite. Sirve index.html y expone la API que usan la caja y la dirección.
El estado canónico vive aquí; el navegador solo dibuja y manda operaciones.

Variables de entorno:
  DATOS_DIR       carpeta de la base de datos (en Railway: /data, el volumen). Por defecto ./datos
  SECRETO         semilla de los tokens del PIN; si no existe se genera y se guarda en DATOS_DIR
  DIAS_HISTORIAL  cuántos días de ventas y movimientos se mandan al navegador (60)
"""
import hashlib
import json
import os
import random
import secrets
import sqlite3
import time
from functools import wraps

from flask import Flask, g, jsonify, request, send_from_directory

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATOS_DIR = os.environ.get('DATOS_DIR') or os.path.join(RAIZ, 'datos')
os.makedirs(DATOS_DIR, exist_ok=True)
DB = os.path.join(DATOS_DIR, 'verduleria.db')
DIAS_HISTORIAL = int(os.environ.get('DIAS_HISTORIAL', '60'))


def _secreto():
    s = os.environ.get('SECRETO')
    if s:
        return s
    ruta = os.path.join(DATOS_DIR, 'secreto.txt')
    if os.path.exists(ruta):
        return open(ruta, encoding='utf-8').read().strip()
    s = secrets.token_hex(24)
    with open(ruta, 'w', encoding='utf-8') as f:
        f.write(s)
    return s


SECRETO = _secreto()

# Catálogo inicial: (nombre, imagen = clave de ilustración o emoji, unidad, precio de referencia).
# Es el mismo que el del index.html. Arranca todo apagado: el dueño enciende en Dirección lo que vende.
CATALOGO = [
    ('Plátano', 'platano', 'kg', 28), ('Plátano macho', '🍌', 'kg', 32), ('Manzana', 'manzana', 'kg', 55), ('Naranja', 'naranja', 'kg', 22),
    ('Limón', 'limon', 'kg', 42), ('Mandarina', '🍊', 'kg', 35), ('Toronja', 'toronja', 'kg', 28), ('Sandía', 'sandia', 'kg', 18),
    ('Melón', 'melon', 'kg', 30), ('Papaya', 'papaya', 'kg', 32), ('Piña', '🍍', 'pieza', 45), ('Mango', '🥭', 'kg', 45),
    ('Fresa', '🍓', 'kg', 90), ('Uva', '🍇', 'kg', 85), ('Guayaba', 'guayaba', 'kg', 40), ('Pera', '🍐', 'kg', 60),
    ('Durazno', '🍑', 'kg', 65), ('Aguacate', 'aguacate', 'kg', 95), ('Coco', '🥥', 'pieza', 35),
    ('Jitomate', 'jitomate', 'kg', 30), ('Tomate verde', 'tomateverde', 'kg', 28), ('Cebolla', 'cebolla', 'kg', 26), ('Cebolla morada', 'cebollamorada', 'kg', 32),
    ('Papa', 'papa', 'kg', 32), ('Zanahoria', 'zanahoria', 'kg', 20), ('Chile serrano', 'chile', 'kg', 60), ('Chile jalapeño', 'jalapeno', 'kg', 45),
    ('Chile poblano', 'poblano', 'kg', 55), ('Pimiento morrón', '🫑', 'kg', 70), ('Cilantro', 'cilantro', 'manojo', 12), ('Perejil', 'perejil', 'manojo', 12),
    ('Epazote', '🌿', 'manojo', 10), ('Lechuga', '🥬', 'pieza', 25), ('Calabacita', 'calabacita', 'kg', 30), ('Pepino', '🥒', 'kg', 25),
    ('Chayote', 'chayote', 'kg', 28), ('Elote', '🌽', 'pieza', 12), ('Nopal', '🌵', 'kg', 25), ('Brócoli', '🥦', 'kg', 45),
    ('Coliflor', 'coliflor', 'pieza', 35), ('Ejote', '🫛', 'kg', 45), ('Espinaca', '🥬', 'manojo', 15), ('Acelga', '🥬', 'manojo', 15),
    ('Ajo', '🧄', 'kg', 120), ('Betabel', 'betabel', 'kg', 25), ('Camote', '🍠', 'kg', 30), ('Champiñón', '🍄', 'kg', 90),
    ('Col', 'col', 'pieza', 30), ('Apio', 'apio', 'pieza', 30), ('Rábano', 'rabano', 'manojo', 15), ('Jícama', 'jicama', 'kg', 25),
]
ILUS = {'platano', 'manzana', 'melon', 'sandia', 'limon', 'cilantro', 'perejil', 'aguacate', 'jitomate', 'cebolla', 'naranja',
        'zanahoria', 'papa', 'chile', 'canasta', 'toronja', 'papaya', 'guayaba', 'tomateverde', 'cebollamorada', 'jalapeno',
        'poblano', 'calabacita', 'chayote', 'coliflor', 'betabel', 'rabano', 'jicama', 'col', 'apio'}
UNIDADES = ('kg', 'pieza', 'manojo')


def unidad_valida(u):
    return u if u in UNIDADES else 'kg'

ARCHIVOS_PUBLICOS = {'index.html': 'text/html; charset=utf-8', 'manifest.webmanifest': 'application/manifest+json',
                     'sw.js': 'application/javascript', 'icono.svg': 'image/svg+xml', 'icono-180.png': 'image/png'}

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024  # las fotos viajan como data URL


# ---------------- utilidades ----------------
def r2(x):
    x = float(x)
    return round(x + (1e-9 if x >= 0 else -1e-9), 2)


def r3(x):
    x = float(x)
    return round(x + (1e-9 if x >= 0 else -1e-9), 3)


def num(x, defecto=0.0):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return defecto
    if v != v or v in (float('inf'), float('-inf')):
        return defecto
    return v


def texto(x, n=60):
    return str(x if x is not None else '').strip()[:n]


def uid():
    return secrets.token_hex(6)


def ahora():
    return int(time.time() * 1000)


def cuerpo():
    return request.get_json(force=True, silent=True) or {}


def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB, timeout=10)
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA journal_mode=WAL')
    return g.db


@app.teardown_appcontext
def _cerrar(_exc):
    d = g.pop('db', None)
    if d is not None:
        d.close()


ESQUEMA = """
CREATE TABLE IF NOT EXISTS negocio(id INTEGER PRIMARY KEY CHECK(id = 1), nombre TEXT, moneda TEXT, pin TEXT, ejemplo INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS productos(id TEXT PRIMARY KEY, nombre TEXT, ilus TEXT, emoji TEXT, foto TEXT, unidad TEXT,
    precio REAL, activo INTEGER, declarado REAL, existencia REAL, orden INTEGER, descripcion TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS movimientos(id TEXT PRIMARY KEY, ts INTEGER, tipo TEXT, pid TEXT, nombre TEXT, cantidad REAL, unidad TEXT, nota TEXT);
CREATE TABLE IF NOT EXISTS ventas(id TEXT PRIMARY KEY, ts INTEGER, lineas TEXT, total REAL, recibido REAL, cambio REAL);
CREATE INDEX IF NOT EXISTS ix_mov_ts ON movimientos(ts);
CREATE INDEX IF NOT EXISTS ix_ven_ts ON ventas(ts);
"""


def sembrar_catalogo(con, activos=None, stock=None):
    """Inserta el catálogo. activos: nombres que arrancan encendidos; stock: {nombre: (declarado, existencia)}."""
    activos = activos or set()
    stock = stock or {}
    creados = []
    for i, (nombre, img, unidad, precio) in enumerate(CATALOGO):
        pid = uid()
        declarado, existencia = stock.get(nombre, (0, 0))
        con.execute('INSERT INTO productos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (pid, nombre, img if img in ILUS else 'canasta', '' if img in ILUS else img, '', unidad, precio,
                     1 if nombre in activos else 0, declarado, existencia, i, ''))
        creados.append({'id': pid, 'nombre': nombre, 'unidad': unidad, 'precio': precio, 'declarado': declarado})
    return creados


def iniciar():
    con = sqlite3.connect(DB)
    con.executescript(ESQUEMA)
    columnas = {r[1] for r in con.execute('PRAGMA table_info(productos)')}
    if 'descripcion' not in columnas:
        con.execute("ALTER TABLE productos ADD COLUMN descripcion TEXT DEFAULT ''")
    if con.execute('SELECT COUNT(*) FROM negocio').fetchone()[0] == 0:
        con.execute("INSERT INTO negocio(id, nombre, moneda, pin, ejemplo) VALUES (1, 'Mi verdulería', '$', '', 0)")
        sembrar_catalogo(con)
    con.commit()
    con.close()


iniciar()


# ---------------- estado ----------------
def fila_producto(r):
    return {'id': r['id'], 'nombre': r['nombre'], 'descripcion': r['descripcion'] or '', 'ilus': r['ilus'], 'emoji': r['emoji'] or '',
            'foto': r['foto'] or '', 'unidad': r['unidad'], 'precio': r['precio'], 'activo': bool(r['activo']),
            'declarado': r['declarado'], 'existencia': r['existencia']}


def estado():
    con = db()
    n = con.execute('SELECT * FROM negocio WHERE id = 1').fetchone()
    desde = ahora() - DIAS_HISTORIAL * 86400000
    return {
        'servidor': True,
        'negocio': {'nombre': n['nombre'], 'moneda': n['moneda'], 'tiene_pin': bool(n['pin']), 'ejemplo': bool(n['ejemplo'])},
        'productos': [fila_producto(r) for r in con.execute('SELECT * FROM productos ORDER BY orden, nombre')],
        'movimientos': [dict(r) for r in con.execute(
            'SELECT id, ts, tipo, pid, nombre, cantidad, unidad, nota FROM movimientos WHERE ts >= ? ORDER BY ts', (desde,))],
        'ventas': [{'id': r['id'], 'ts': r['ts'], 'lineas': json.loads(r['lineas']), 'total': r['total'],
                    'recibido': r['recibido'], 'cambio': r['cambio']}
                   for r in con.execute('SELECT * FROM ventas WHERE ts >= ? ORDER BY ts', (desde,))],
    }


def responder(extra=None):
    e = estado()
    if extra:
        e.update(extra)
    return jsonify(e)


def error(msg, codigo=400):
    return jsonify(error=msg), codigo


def producto(con, pid):
    r = con.execute('SELECT * FROM productos WHERE id = ?', (pid,)).fetchone()
    return dict(r) if r else None


def movimiento(con, tipo, p, cantidad, nota='', ts=None):
    con.execute('INSERT INTO movimientos VALUES (?,?,?,?,?,?,?,?)',
                (uid(), ts or ahora(), tipo, p['id'], p['nombre'], r3(cantidad), p['unidad'], nota))


# ---------------- PIN de dirección ----------------
def token_de(pin):
    return hashlib.sha256(f'{SECRETO}:{pin}'.encode()).hexdigest()


def pin_actual():
    return db().execute('SELECT pin FROM negocio WHERE id = 1').fetchone()['pin'] or ''


def con_pin(f):
    """Las rutas de dirección piden el token del PIN solo si el negocio tiene PIN."""
    @wraps(f)
    def envoltura(*a, **k):
        pin = pin_actual()
        if pin and not secrets.compare_digest(request.headers.get('X-Token', ''), token_de(pin)):
            return error('Se necesita el PIN de dirección', 401)
        return f(*a, **k)
    return envoltura


# ---------------- archivos ----------------
@app.get('/')
def inicio():
    return estatico('index.html')


@app.get('/<path:archivo>')
def estatico(archivo):
    if archivo not in ARCHIVOS_PUBLICOS:
        return error('No existe', 404)
    resp = send_from_directory(RAIZ, archivo, mimetype=ARCHIVOS_PUBLICOS[archivo])
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.get('/api/salud')
def salud():
    return jsonify(ok=True, productos=db().execute('SELECT COUNT(*) FROM productos').fetchone()[0])


@app.get('/api/estado')
def api_estado():
    return responder()


@app.post('/api/pin')
def api_pin():
    pin = pin_actual()
    if not pin:
        return jsonify(token='')
    if not secrets.compare_digest(texto(cuerpo().get('pin'), 8), pin):
        return error('PIN incorrecto', 401)
    return jsonify(token=token_de(pin))


# ---------------- caja ----------------
@app.post('/api/ventas')
def api_venta():
    d = cuerpo()
    con = db()
    vid = texto(d.get('id'), 40) or uid()
    if con.execute('SELECT 1 FROM ventas WHERE id = ?', (vid,)).fetchone():
        return responder()  # reintento de una venta ya registrada
    lineas = []
    for l in (d.get('lineas') or [])[:100]:
        if not isinstance(l, dict):
            continue
        cantidad = r3(num(l.get('cantidad')))
        precio = r2(num(l.get('precio')))
        if cantidad <= 0 or precio < 0:
            continue
        p = producto(con, texto(l.get('pid'), 40))
        lineas.append({'pid': p['id'] if p else '', 'nombre': p['nombre'] if p else (texto(l.get('nombre'), 40) or 'Producto'),
                       'cantidad': cantidad, 'unidad': p['unidad'] if p else unidad_valida(l.get('unidad')),
                       'precio': precio, 'importe': r2(cantidad * precio)})
    if not lineas:
        return error('El ticket está vacío')
    total = r2(sum(l['importe'] for l in lineas))
    recibido = d.get('recibido')
    recibido = total if recibido in (None, '') else r2(num(recibido))
    if recibido < total:
        return error('Lo recibido no cubre el total')
    ts = int(num(d.get('ts'), 0))
    hoy = ahora()
    if not (hoy - 30 * 86400000 <= ts <= hoy + 300000):
        ts = hoy
    for l in lineas:
        if l['pid']:
            con.execute('UPDATE productos SET existencia = ROUND(existencia - ?, 3) WHERE id = ?', (l['cantidad'], l['pid']))
            movimiento(con, 'venta', producto(con, l['pid']), l['cantidad'], '', ts)
    con.execute('INSERT INTO ventas VALUES (?,?,?,?,?,?)',
                (vid, ts, json.dumps(lineas, ensure_ascii=False), total, recibido, r2(recibido - total)))
    con.commit()
    return responder()


# ---------------- dirección ----------------
@app.post('/api/entradas')
@con_pin
def api_entrada():
    d = cuerpo()
    con = db()
    p = producto(con, texto(d.get('pid'), 40))
    if not p:
        return error('Producto no encontrado', 404)
    c = r3(num(d.get('cantidad')))
    if c <= 0:
        return error('Escribe una cantidad')
    nueva = r3(max(0.0, p['existencia']) + c)
    con.execute('UPDATE productos SET existencia = ?, declarado = ? WHERE id = ?', (nueva, nueva, p['id']))
    movimiento(con, 'entrada', p, c, texto(d.get('nota')))
    con.commit()
    return responder()


@app.post('/api/ajustes')
@con_pin
def api_ajuste():
    d = cuerpo()
    con = db()
    p = producto(con, texto(d.get('pid'), 40))
    if not p:
        return error('Producto no encontrado', 404)
    nueva = r3(max(0.0, num(d.get('existencia'))))
    delta = r3(nueva - p['existencia'])
    con.execute('UPDATE productos SET existencia = ?, declarado = ? WHERE id = ?', (nueva, max(p['declarado'], nueva), p['id']))
    tipo = 'merma' if d.get('motivo') == 'merma' else 'ajuste'
    movimiento(con, tipo, p, abs(delta) if tipo == 'merma' else delta)
    con.commit()
    return responder()


@app.post('/api/carga')
@con_pin
def api_carga():
    """Tabla de Dirección: precio y stock actual de todos los productos de una vez."""
    d = cuerpo()
    con = db()
    cambios = 0
    ts = ahora()
    for it in (d.get('items') or [])[:500]:
        if not isinstance(it, dict):
            continue
        p = producto(con, texto(it.get('id'), 40))
        if not p:
            continue
        if it.get('precio') not in (None, ''):
            precio = r2(max(0.0, num(it.get('precio'))))
            if precio != p['precio']:
                con.execute('UPDATE productos SET precio = ? WHERE id = ?', (precio, p['id']))
                cambios += 1
        if it.get('existencia') not in (None, ''):
            v = r3(max(0.0, num(it.get('existencia'))))
            if v != r3(max(0.0, p['existencia'])):
                delta = r3(v - p['existencia'])
                con.execute('UPDATE productos SET existencia = ?, declarado = ? WHERE id = ?', (v, v, p['id']))
                movimiento(con, 'entrada' if delta > 0 else 'ajuste', p, delta, 'Carga desde Dirección', ts)
                cambios += 1
    con.commit()
    return responder({'cambios': cambios})


def datos_producto(d):
    nombre = texto(d.get('nombre'), 30)
    if not nombre:
        return None, 'Ponle nombre al producto'
    foto = str(d.get('foto') or '')
    if foto and not foto.startswith('data:image/'):
        foto = ''
    if len(foto) > 900000:
        return None, 'La foto es demasiado grande'
    return {'nombre': nombre, 'descripcion': texto(d.get('descripcion'), 60), 'unidad': unidad_valida(d.get('unidad')),
            'precio': r2(max(0.0, num(d.get('precio')))), 'ilus': d.get('ilus') if d.get('ilus') in ILUS else 'canasta',
            'emoji': texto(d.get('emoji'), 8), 'foto': foto}, None


@app.post('/api/productos')
@con_pin
def api_producto_nuevo():
    datos, err = datos_producto(cuerpo())
    if err:
        return error(err)
    con = db()
    orden = con.execute('SELECT COALESCE(MAX(orden), -1) + 1 FROM productos').fetchone()[0]
    con.execute('INSERT INTO productos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                (uid(), datos['nombre'], datos['ilus'], datos['emoji'], datos['foto'], datos['unidad'], datos['precio'], 1, 0, 0, orden, datos['descripcion']))
    con.commit()
    return responder()


@app.put('/api/productos/<pid>')
@con_pin
def api_producto_editar(pid):
    con = db()
    if not producto(con, pid):
        return error('Producto no encontrado', 404)
    datos, err = datos_producto(cuerpo())
    if err:
        return error(err)
    con.execute('UPDATE productos SET nombre = ?, ilus = ?, emoji = ?, foto = ?, unidad = ?, precio = ?, descripcion = ? WHERE id = ?',
                (datos['nombre'], datos['ilus'], datos['emoji'], datos['foto'], datos['unidad'], datos['precio'], datos['descripcion'], pid))
    con.commit()
    return responder()


@app.delete('/api/productos/<pid>')
@con_pin
def api_producto_borrar(pid):
    con = db()
    con.execute('DELETE FROM productos WHERE id = ?', (pid,))
    con.commit()
    return responder()


@app.post('/api/productos/<pid>/activo')
@con_pin
def api_producto_activo(pid):
    con = db()
    if not producto(con, pid):
        return error('Producto no encontrado', 404)
    con.execute('UPDATE productos SET activo = ? WHERE id = ?', (1 if cuerpo().get('activo') else 0, pid))
    con.commit()
    return responder()


@app.put('/api/negocio')
@con_pin
def api_negocio():
    d = cuerpo()
    con = db()
    con.execute('UPDATE negocio SET nombre = ?, moneda = ? WHERE id = 1',
                (texto(d.get('nombre'), 40) or 'Mi verdulería', texto(d.get('moneda'), 4) or '$'))
    extra = {}
    nuevo_pin = texto(d.get('pin'), 8)
    if d.get('quitar_pin'):
        con.execute("UPDATE negocio SET pin = '' WHERE id = 1")
        extra['token'] = ''
    elif nuevo_pin:
        if not (nuevo_pin.isdigit() and len(nuevo_pin) == 4):
            return error('El PIN son 4 números')
        con.execute('UPDATE negocio SET pin = ? WHERE id = 1', (nuevo_pin,))
        extra['token'] = token_de(nuevo_pin)
    con.commit()
    return responder(extra)


# ---------------- datos: limpio, ejemplo, borrar, restaurar ----------------
def _vaciar(con, productos_tambien=False):
    con.execute('DELETE FROM ventas')
    con.execute('DELETE FROM movimientos')
    if productos_tambien:
        con.execute('DELETE FROM productos')
    else:
        con.execute('UPDATE productos SET existencia = 0, declarado = 0')


@app.post('/api/limpio')
@con_pin
def api_limpio():
    con = db()
    _vaciar(con)
    con.execute('UPDATE negocio SET ejemplo = 0 WHERE id = 1')
    con.commit()
    return responder()


@app.post('/api/borrar')
@con_pin
def api_borrar():
    con = db()
    _vaciar(con, True)
    sembrar_catalogo(con)
    con.execute("UPDATE negocio SET nombre = 'Mi verdulería', moneda = '$', pin = '', ejemplo = 0 WHERE id = 1")
    con.commit()
    return responder({'token': ''})


@app.post('/api/ejemplo')
@con_pin
def api_ejemplo():
    """Siembra el catálogo con existencia en 10 productos y una semana de ventas inventadas, para enseñar el sistema."""
    con = db()
    _vaciar(con, True)
    azar = random.Random(20260925)
    stock = {'Plátano': (20, 14.5), 'Manzana': (15, 12), 'Melón': (25, 9), 'Sandía': (40, 31), 'Limón': (10, 1.6),
             'Cilantro': (30, 22), 'Perejil': (20, 0), 'Aguacate': (12, 6.8), 'Jitomate': (18, 11), 'Cebolla': (15, 9.5)}
    activos = {n for n in stock if n != 'Perejil'}
    t = time.localtime()
    base_hoy = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))) * 1000
    creados = sembrar_catalogo(con, activos, stock)
    prods = []
    for i, p in enumerate(creados):
        if p['declarado'] > 0:
            movimiento(con, 'entrada', p, p['declarado'], 'Central de abastos', base_hoy + (7 * 60 + 30 + i) * 60000)
        if p['nombre'] in activos:
            prods.append(p)
    limite = ahora() - 60000
    for d in range(6, -1, -1):
        dia = base_hoy - d * 86400000
        for _ in range(azar.randint(2, 5) if d else 2):
            ts = dia + azar.randint(8, 17) * 3600000 + azar.randint(0, 59) * 60000
            if d == 0:
                ts = min(ts, limite)
            lineas = []
            for p in azar.sample(prods, azar.randint(1, 3)):
                cantidad = r3(0.25 + azar.randint(0, 11) * 0.25) if p['unidad'] == 'kg' else float(azar.randint(1, 3))
                lineas.append({'pid': p['id'], 'nombre': p['nombre'], 'cantidad': cantidad, 'unidad': p['unidad'],
                               'precio': p['precio'], 'importe': r2(cantidad * p['precio'])})
                if d == 0:
                    movimiento(con, 'venta', p, cantidad, '', ts)
            total = r2(sum(l['importe'] for l in lineas))
            recibido = float(-(-total // 50) * 50) or total
            con.execute('INSERT INTO ventas VALUES (?,?,?,?,?,?)',
                        (uid(), ts, json.dumps(lineas, ensure_ascii=False), total, recibido, r2(recibido - total)))
    con.execute('UPDATE negocio SET ejemplo = 1 WHERE id = 1')
    con.commit()
    return responder()


@app.post('/api/restaurar')
@con_pin
def api_restaurar():
    """Carga un respaldo copiado desde Ajustes (sirve para traer los datos de la demo estática)."""
    d = cuerpo()
    if not isinstance(d.get('productos'), list) or not isinstance(d.get('negocio'), dict):
        return error('Ese texto no es un respaldo válido')
    con = db()
    _vaciar(con, True)
    n = d['negocio']
    con.execute('UPDATE negocio SET nombre = ?, moneda = ?, ejemplo = ? WHERE id = 1',
                (texto(n.get('nombre'), 40) or 'Mi verdulería', texto(n.get('moneda'), 4) or '$', 1 if n.get('ejemplo') else 0))
    ids = set()
    for i, p in enumerate(d['productos'][:500]):
        if not isinstance(p, dict):
            continue
        datos, err = datos_producto(p)
        if err:
            continue
        pid = texto(p.get('id'), 40) or uid()
        if pid in ids:
            pid = uid()
        ids.add(pid)
        con.execute('INSERT INTO productos VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (pid, datos['nombre'], datos['ilus'], datos['emoji'], datos['foto'], datos['unidad'], datos['precio'],
                     0 if p.get('activo') is False else 1, r3(max(0.0, num(p.get('declarado')))), r3(num(p.get('existencia'))), i, datos['descripcion']))
    for m in (d.get('movimientos') or [])[:20000]:
        if not isinstance(m, dict):
            continue
        con.execute('INSERT OR IGNORE INTO movimientos VALUES (?,?,?,?,?,?,?,?)',
                    (texto(m.get('id'), 40) or uid(), int(num(m.get('ts'), ahora())), texto(m.get('tipo'), 10) or 'ajuste',
                     texto(m.get('pid'), 40), texto(m.get('nombre'), 40), r3(num(m.get('cantidad'))),
                     unidad_valida(m.get('unidad')), texto(m.get('nota'), 60)))
    for v in (d.get('ventas') or [])[:20000]:
        if not isinstance(v, dict) or not isinstance(v.get('lineas'), list):
            continue
        total = r2(num(v.get('total')))
        recibido = r2(num(v.get('recibido'), total))
        con.execute('INSERT OR IGNORE INTO ventas VALUES (?,?,?,?,?,?)',
                    (texto(v.get('id'), 40) or uid(), int(num(v.get('ts'), ahora())),
                     json.dumps(v['lineas'][:100], ensure_ascii=False), total, recibido, r2(recibido - total)))
    con.commit()
    return responder()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8080')), debug=False)
