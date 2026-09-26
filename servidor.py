"""Verdulería al Peso: servidor multi-negocio.

Flask + SQLite. Una cuenta (el dueño, con correo y contraseña) tiene una o más sucursales; cada
sucursal tiene su catálogo, precios, stock, ventas y una clave de caja con la que entran los
teléfonos del punto de venta. El estado canónico vive aquí; el navegador dibuja y manda operaciones.

Variables de entorno:
  DATOS_DIR               carpeta de la base de datos (Railway: /data, el volumen). Por defecto ./datos
  DIAS_HISTORIAL          días de ventas y movimientos que se mandan al navegador (60)
  CODIGO_ALTA             si se define, crear una cuenta exige este código de invitación
  MIGRACION_CORREO        correo de la cuenta que recibe los datos de una base vieja de un solo negocio
  MIGRACION_CONTRASENA    su contraseña (si falta, se genera una y se imprime en el log una sola vez)
"""
import hashlib
import json
import os
import random
import secrets
import sqlite3
import time
from functools import wraps

from flask import Flask, Response, g, jsonify, request, send_from_directory

RAIZ = os.path.dirname(os.path.abspath(__file__))
DATOS_DIR = os.environ.get('DATOS_DIR') or os.path.join(RAIZ, 'datos')
os.makedirs(DATOS_DIR, exist_ok=True)
DB = os.path.join(DATOS_DIR, 'verduleria.db')
DIAS_HISTORIAL = int(os.environ.get('DIAS_HISTORIAL', '60'))
CODIGO_ALTA = (os.environ.get('CODIGO_ALTA') or '').strip()
DIA_MS = 86400000
SESION_DIAS = 180

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
ARCHIVOS_PUBLICOS = {'index.html': 'text/html; charset=utf-8', 'manifest.webmanifest': 'application/manifest+json',
                     'sw.js': 'application/javascript', 'icono.svg': 'image/svg+xml', 'icono-180.png': 'image/png'}
COLS_PRODUCTO = 'id, sucursal_id, nombre, ilus, emoji, foto, unidad, precio, activo, declarado, existencia, orden, descripcion, precio_mayoreo, mayoreo_desde'
INS_PRODUCTO = f'INSERT INTO productos({COLS_PRODUCTO}) VALUES ({",".join("?" * 15)})'

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


def unidad_valida(u):
    return u if u in UNIDADES else 'kg'


def uid():
    return secrets.token_hex(6)


def ahora():
    return int(time.time() * 1000)


def cuerpo():
    return request.get_json(force=True, silent=True) or {}


def hash_pw(pw, sal):
    return hashlib.pbkdf2_hmac('sha256', pw.encode('utf-8'), bytes.fromhex(sal), 120000).hex()


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
CREATE TABLE IF NOT EXISTS cuentas(id TEXT PRIMARY KEY, correo TEXT UNIQUE, nombre TEXT, hash TEXT, sal TEXT, creado INTEGER);
CREATE TABLE IF NOT EXISTS sesiones(token TEXT PRIMARY KEY, cuenta_id TEXT, creado INTEGER, ultimo INTEGER);
CREATE TABLE IF NOT EXISTS sucursales(id TEXT PRIMARY KEY, cuenta_id TEXT, nombre TEXT, moneda TEXT, ejemplo INTEGER DEFAULT 0,
    clave_caja TEXT UNIQUE, creado INTEGER, orden INTEGER);
CREATE TABLE IF NOT EXISTS productos(id TEXT PRIMARY KEY, sucursal_id TEXT, nombre TEXT, ilus TEXT, emoji TEXT, foto TEXT, unidad TEXT,
    precio REAL, activo INTEGER, declarado REAL, existencia REAL, orden INTEGER, descripcion TEXT DEFAULT '',
    precio_mayoreo REAL DEFAULT 0, mayoreo_desde REAL DEFAULT 0);
CREATE TABLE IF NOT EXISTS movimientos(id TEXT PRIMARY KEY, sucursal_id TEXT, ts INTEGER, tipo TEXT, pid TEXT, nombre TEXT, cantidad REAL, unidad TEXT, nota TEXT);
CREATE TABLE IF NOT EXISTS ventas(id TEXT PRIMARY KEY, sucursal_id TEXT, ts INTEGER, lineas TEXT, total REAL, recibido REAL, cambio REAL);
CREATE INDEX IF NOT EXISTS ix_prod_suc ON productos(sucursal_id);
CREATE INDEX IF NOT EXISTS ix_mov_suc_ts ON movimientos(sucursal_id, ts);
CREATE INDEX IF NOT EXISTS ix_ven_suc_ts ON ventas(sucursal_id, ts);
CREATE INDEX IF NOT EXISTS ix_ses_cuenta ON sesiones(cuenta_id);
"""


def sembrar_catalogo(con, sid, activos=None, stock=None):
    """Inserta el catálogo en la sucursal. activos: nombres encendidos; stock: {nombre: (declarado, existencia)}."""
    activos = activos or set()
    stock = stock or {}
    creados = []
    for i, (nombre, img, unidad, precio) in enumerate(CATALOGO):
        pid = uid()
        declarado, existencia = stock.get(nombre, (0, 0))
        con.execute(INS_PRODUCTO, (pid, sid, nombre, img if img in ILUS else 'canasta', '' if img in ILUS else img, '', unidad, precio,
                                   1 if nombre in activos else 0, declarado, existencia, i, '', 0, 0))
        creados.append({'id': pid, 'nombre': nombre, 'unidad': unidad, 'precio': precio, 'declarado': declarado})
    return creados


def crear_cuenta(con, nombre, correo, contrasena):
    sal = secrets.token_hex(16)
    cid = uid()
    con.execute('INSERT INTO cuentas VALUES (?,?,?,?,?,?)', (cid, correo, nombre, hash_pw(contrasena, sal), sal, ahora()))
    return cid


def clave_nueva(con):
    alfabeto = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    while True:
        c = ''.join(secrets.choice(alfabeto) for _ in range(6))
        if not con.execute('SELECT 1 FROM sucursales WHERE clave_caja = ?', (c,)).fetchone():
            return c


def crear_sucursal(con, cid, nombre, moneda='$', copiar_de=None, sembrar=True):
    sid = uid()
    orden = con.execute('SELECT COALESCE(MAX(orden), -1) + 1 FROM sucursales WHERE cuenta_id = ?', (cid,)).fetchone()[0]
    con.execute('INSERT INTO sucursales VALUES (?,?,?,?,?,?,?,?)', (sid, cid, nombre, moneda, 0, clave_nueva(con), ahora(), orden))
    if copiar_de:
        for r in con.execute('SELECT * FROM productos WHERE sucursal_id = ? ORDER BY orden, nombre', (copiar_de,)):
            con.execute(INS_PRODUCTO, (uid(), sid, r['nombre'], r['ilus'], r['emoji'], r['foto'], r['unidad'], r['precio'], r['activo'],
                                       0, 0, r['orden'], r['descripcion'] or '', r['precio_mayoreo'] or 0, r['mayoreo_desde'] or 0))
    elif sembrar:
        sembrar_catalogo(con, sid)
    return sid


def iniciar():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    tablas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    vieja = 'negocio' in tablas and 'sucursales' not in tablas
    if vieja:
        # Base de un solo negocio (versión anterior): se le agregan las columnas nuevas antes de crear el resto.
        for t in ('productos', 'movimientos', 'ventas'):
            cols = {r[1] for r in con.execute(f'PRAGMA table_info({t})')}
            if 'sucursal_id' not in cols:
                con.execute(f'ALTER TABLE {t} ADD COLUMN sucursal_id TEXT')
        cols = {r[1] for r in con.execute('PRAGMA table_info(productos)')}
        for c, d in (('descripcion', "TEXT DEFAULT ''"), ('precio_mayoreo', 'REAL DEFAULT 0'), ('mayoreo_desde', 'REAL DEFAULT 0')):
            if c not in cols:
                con.execute(f'ALTER TABLE productos ADD COLUMN {c} {d}')
    con.executescript(ESQUEMA)
    if vieja:
        n = con.execute('SELECT * FROM negocio WHERE id = 1').fetchone()
        correo = (os.environ.get('MIGRACION_CORREO') or 'dueno@verduleria.local').strip().lower()
        contrasena = os.environ.get('MIGRACION_CONTRASENA') or secrets.token_urlsafe(9)
        cid = crear_cuenta(con, 'Dueño', correo, contrasena)
        sid = crear_sucursal(con, cid, (n['nombre'] if n else '') or 'Mi verdulería', (n['moneda'] if n else '') or '$', sembrar=False)
        con.execute('UPDATE sucursales SET ejemplo = ? WHERE id = ?', (1 if (n and n['ejemplo']) else 0, sid))
        for t in ('productos', 'movimientos', 'ventas'):
            con.execute(f'UPDATE {t} SET sucursal_id = ? WHERE sucursal_id IS NULL', (sid,))
        con.execute('ALTER TABLE negocio RENAME TO negocio_migrado')
        if not os.environ.get('MIGRACION_CONTRASENA'):
            print(f'[migración] cuenta {correo} con contraseña generada: {contrasena}', flush=True)
        print(f'[migración] el negocio pasó a la sucursal {sid} de la cuenta {correo}', flush=True)
    con.commit()
    con.close()


iniciar()


# ---------------- estado de una sucursal ----------------
def fila_producto(r):
    return {'id': r['id'], 'nombre': r['nombre'], 'descripcion': r['descripcion'] or '', 'ilus': r['ilus'], 'emoji': r['emoji'] or '',
            'foto': r['foto'] or '', 'unidad': r['unidad'], 'precio': r['precio'], 'activo': bool(r['activo']),
            'declarado': r['declarado'], 'existencia': r['existencia'],
            'precio_mayoreo': r['precio_mayoreo'] or 0, 'mayoreo_desde': r['mayoreo_desde'] or 0}


def fila_venta(r):
    return {'id': r['id'], 'ts': r['ts'], 'lineas': json.loads(r['lineas']), 'total': r['total'], 'recibido': r['recibido'], 'cambio': r['cambio']}


def estado_sucursal(suc, para_dueno=False):
    con = db()
    sid = suc['id']
    desde = ahora() - DIAS_HISTORIAL * DIA_MS
    negocio = {'nombre': suc['nombre'], 'moneda': suc['moneda'], 'ejemplo': bool(suc['ejemplo']), 'sucursal_id': sid}
    if para_dueno:
        negocio['clave_caja'] = suc['clave_caja']
    return {
        'servidor': True, 'multi': True, 'negocio': negocio,
        'productos': [fila_producto(r) for r in con.execute('SELECT * FROM productos WHERE sucursal_id = ? ORDER BY orden, nombre', (sid,))],
        'movimientos': [dict(r) for r in con.execute(
            'SELECT id, ts, tipo, pid, nombre, cantidad, unidad, nota FROM movimientos WHERE sucursal_id = ? AND ts >= ? ORDER BY ts', (sid, desde))],
        'ventas': [fila_venta(r) for r in con.execute('SELECT * FROM ventas WHERE sucursal_id = ? AND ts >= ? ORDER BY ts', (sid, desde))],
    }


def responder(extra=None):
    suc = db().execute('SELECT * FROM sucursales WHERE id = ?', (g.suc['id'],)).fetchone()  # releído: pudo cambiar
    e = estado_sucursal(suc, para_dueno=bool(getattr(g, 'cuenta', None)))
    if extra:
        e.update(extra)
    return jsonify(e)


def error(msg, codigo=400):
    return jsonify(error=msg), codigo


def producto(con, sid, pid):
    r = con.execute('SELECT * FROM productos WHERE id = ? AND sucursal_id = ?', (pid, sid)).fetchone()
    return dict(r) if r else None


def movimiento(con, sid, tipo, p, cantidad, nota='', ts=None):
    con.execute('INSERT INTO movimientos VALUES (?,?,?,?,?,?,?,?,?)',
                (uid(), sid, ts or ahora(), tipo, p['id'], p['nombre'], r3(cantidad), p['unidad'], nota))


def sucursales_de(con, cid):
    return [{'id': r['id'], 'nombre': r['nombre'], 'moneda': r['moneda'], 'clave_caja': r['clave_caja']}
            for r in con.execute('SELECT * FROM sucursales WHERE cuenta_id = ? ORDER BY orden, creado', (cid,))]


def cuenta_json(c):
    return {'id': c['id'], 'nombre': c['nombre'], 'correo': c['correo']}


# ---------------- acceso ----------------
def cuenta_actual():
    tok = request.headers.get('X-Sesion', '')
    if not tok:
        return None
    con = db()
    s = con.execute('SELECT * FROM sesiones WHERE token = ?', (tok,)).fetchone()
    if not s or s['ultimo'] < ahora() - SESION_DIAS * DIA_MS:
        return None
    if s['ultimo'] < ahora() - 3600000:
        con.execute('UPDATE sesiones SET ultimo = ? WHERE token = ?', (ahora(), tok))
        con.commit()
    return con.execute('SELECT * FROM cuentas WHERE id = ?', (s['cuenta_id'],)).fetchone()


def con_cuenta(f):
    @wraps(f)
    def envoltura(*a, **k):
        g.cuenta = cuenta_actual()
        if not g.cuenta:
            return error('Vuelve a entrar con tu correo y contraseña', 401)
        return f(*a, **k)
    return envoltura


def con_sucursal(f):
    """Rutas /api/mi/sucursales/<sid>/...: la sucursal debe ser de la cuenta."""
    @wraps(f)
    def envoltura(sid, *a, **k):
        g.cuenta = cuenta_actual()
        if not g.cuenta:
            return error('Vuelve a entrar con tu correo y contraseña', 401)
        g.suc = db().execute('SELECT * FROM sucursales WHERE id = ? AND cuenta_id = ?', (sid, g.cuenta['id'])).fetchone()
        if not g.suc:
            return error('Esa sucursal no existe', 404)
        return f(*a, **k)
    return envoltura


def con_caja(f):
    """Rutas /api/c/<clave>/...: el teléfono del punto de venta entra con la clave de caja."""
    @wraps(f)
    def envoltura(clave, *a, **k):
        g.cuenta = None
        g.suc = db().execute('SELECT * FROM sucursales WHERE clave_caja = ?', (texto(clave, 12).upper(),)).fetchone()
        if not g.suc:
            return error('Esa clave de caja no existe', 404)
        return f(*a, **k)
    return envoltura


def nueva_sesion(con, cid):
    tok = secrets.token_urlsafe(32)
    con.execute('INSERT INTO sesiones VALUES (?,?,?,?)', (tok, cid, ahora(), ahora()))
    return tok


def respuesta_sesion(con, c, tok):
    return jsonify(sesion=tok, cuenta=cuenta_json(c), sucursales=sucursales_de(con, c['id']))


# ---------------- archivos ----------------
@app.get('/')
def inicio():
    return estatico('index.html')


@app.get('/<path:archivo>')
def estatico(archivo):
    if archivo not in ARCHIVOS_PUBLICOS:
        return error('No existe', 404)
    if archivo == 'manifest.webmanifest':
        with open(os.path.join(RAIZ, archivo), encoding='utf-8') as f:
            m = json.load(f)
        caja = texto(request.args.get('caja'), 12).upper()
        if caja:
            m['start_url'] = './?caja=' + caja
            m['id'] = './?caja=' + caja
        resp = Response(json.dumps(m, ensure_ascii=False), mimetype=ARCHIVOS_PUBLICOS[archivo])
    else:
        resp = send_from_directory(RAIZ, archivo, mimetype=ARCHIVOS_PUBLICOS[archivo])
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.get('/api/salud')
def salud():
    con = db()
    return jsonify(ok=True, cuentas=con.execute('SELECT COUNT(*) FROM cuentas').fetchone()[0],
                   sucursales=con.execute('SELECT COUNT(*) FROM sucursales').fetchone()[0])


@app.get('/api/estado')
def api_estado():
    """Solo dice que hay servidor multi-negocio; los datos van por sucursal."""
    return jsonify(servidor=True, multi=True, alta_abierta=not CODIGO_ALTA)


# ---------------- cuentas y sesiones ----------------
@app.post('/api/cuentas')
def api_crear_cuenta():
    d = cuerpo()
    if CODIGO_ALTA and texto(d.get('codigo'), 40) != CODIGO_ALTA:
        return error('El código de invitación no es correcto')
    nombre = texto(d.get('nombre'), 40)
    correo = texto(d.get('correo'), 80).lower()
    contrasena = str(d.get('contrasena') or '')
    verduleria = texto(d.get('verduleria'), 40) or 'Mi verdulería'
    if not nombre or '@' not in correo or '.' not in correo.split('@')[-1]:
        return error('Escribe tu nombre y un correo válido')
    if len(contrasena) < 6:
        return error('La contraseña necesita al menos 6 caracteres')
    con = db()
    if con.execute('SELECT 1 FROM cuentas WHERE correo = ?', (correo,)).fetchone():
        return error('Ya hay una cuenta con ese correo. Entra con tu contraseña.')
    cid = crear_cuenta(con, nombre, correo, contrasena)
    crear_sucursal(con, cid, verduleria)
    tok = nueva_sesion(con, cid)
    con.commit()
    return respuesta_sesion(con, con.execute('SELECT * FROM cuentas WHERE id = ?', (cid,)).fetchone(), tok)


@app.post('/api/sesion')
def api_entrar():
    d = cuerpo()
    correo = texto(d.get('correo'), 80).lower()
    contrasena = str(d.get('contrasena') or '')
    con = db()
    c = con.execute('SELECT * FROM cuentas WHERE correo = ?', (correo,)).fetchone()
    if not c or not secrets.compare_digest(hash_pw(contrasena, c['sal']), c['hash']):
        return error('Correo o contraseña incorrectos', 401)
    tok = nueva_sesion(con, c['id'])
    con.commit()
    return respuesta_sesion(con, c, tok)


@app.delete('/api/sesion')
def api_salir():
    tok = request.headers.get('X-Sesion', '')
    if tok:
        con = db()
        con.execute('DELETE FROM sesiones WHERE token = ?', (tok,))
        con.commit()
    return jsonify(ok=True)


@app.get('/api/mi')
@con_cuenta
def api_mi():
    return jsonify(cuenta=cuenta_json(g.cuenta), sucursales=sucursales_de(db(), g.cuenta['id']))


@app.put('/api/mi')
@con_cuenta
def api_mi_editar():
    d = cuerpo()
    con = db()
    nombre = texto(d.get('nombre'), 40) or g.cuenta['nombre']
    correo = texto(d.get('correo'), 80).lower() or g.cuenta['correo']
    if '@' not in correo:
        return error('Escribe un correo válido')
    otra = con.execute('SELECT 1 FROM cuentas WHERE correo = ? AND id != ?', (correo, g.cuenta['id'])).fetchone()
    if otra:
        return error('Ese correo ya lo usa otra cuenta')
    nueva = str(d.get('contrasena_nueva') or '')
    if nueva:
        actual = str(d.get('contrasena_actual') or '')
        if not secrets.compare_digest(hash_pw(actual, g.cuenta['sal']), g.cuenta['hash']):
            return error('La contraseña actual no es correcta')
        if len(nueva) < 6:
            return error('La contraseña nueva necesita al menos 6 caracteres')
        sal = secrets.token_hex(16)
        con.execute('UPDATE cuentas SET hash = ?, sal = ? WHERE id = ?', (hash_pw(nueva, sal), sal, g.cuenta['id']))
        con.execute('DELETE FROM sesiones WHERE cuenta_id = ? AND token != ?', (g.cuenta['id'], request.headers.get('X-Sesion', '')))
    con.execute('UPDATE cuentas SET nombre = ?, correo = ? WHERE id = ?', (nombre, correo, g.cuenta['id']))
    con.commit()
    c = con.execute('SELECT * FROM cuentas WHERE id = ?', (g.cuenta['id'],)).fetchone()
    return jsonify(cuenta=cuenta_json(c), sucursales=sucursales_de(con, c['id']))


# ---------------- sucursales ----------------
@app.post('/api/mi/sucursales')
@con_cuenta
def api_sucursal_nueva():
    d = cuerpo()
    con = db()
    nombre = texto(d.get('nombre'), 40)
    if not nombre:
        return error('Ponle nombre a la sucursal')
    copiar = texto(d.get('copiar_de'), 40)
    if copiar and not con.execute('SELECT 1 FROM sucursales WHERE id = ? AND cuenta_id = ?', (copiar, g.cuenta['id'])).fetchone():
        copiar = ''
    sid = crear_sucursal(con, g.cuenta['id'], nombre, copiar_de=copiar or None)
    con.commit()
    return jsonify(sucursal=sid, sucursales=sucursales_de(con, g.cuenta['id']))


@app.put('/api/mi/sucursales/<sid>')
@con_sucursal
def api_sucursal_editar():
    d = cuerpo()
    con = db()
    con.execute('UPDATE sucursales SET nombre = ?, moneda = ? WHERE id = ?',
                (texto(d.get('nombre'), 40) or g.suc['nombre'], texto(d.get('moneda'), 4) or g.suc['moneda'], g.suc['id']))
    con.commit()
    return responder({'sucursales': sucursales_de(con, g.cuenta['id'])})


@app.delete('/api/mi/sucursales/<sid>')
@con_sucursal
def api_sucursal_borrar():
    con = db()
    if con.execute('SELECT COUNT(*) FROM sucursales WHERE cuenta_id = ?', (g.cuenta['id'],)).fetchone()[0] <= 1:
        return error('No se puede borrar la única sucursal')
    for t in ('productos', 'movimientos', 'ventas'):
        con.execute(f'DELETE FROM {t} WHERE sucursal_id = ?', (g.suc['id'],))
    con.execute('DELETE FROM sucursales WHERE id = ?', (g.suc['id'],))
    con.commit()
    return jsonify(sucursales=sucursales_de(con, g.cuenta['id']))


@app.post('/api/mi/sucursales/<sid>/clave')
@con_sucursal
def api_sucursal_clave():
    con = db()
    con.execute('UPDATE sucursales SET clave_caja = ? WHERE id = ?', (clave_nueva(con), g.suc['id']))
    con.commit()
    return responder({'sucursales': sucursales_de(con, g.cuenta['id'])})


@app.get('/api/mi/sucursales/<sid>/estado')
@con_sucursal
def api_sucursal_estado():
    return responder()


@app.get('/api/mi/resumen')
@con_cuenta
def api_resumen():
    """Todas las sucursales: ventas de los últimos 8 días y productos por reponer. El navegador agrupa por día en su hora local."""
    con = db()
    desde = ahora() - 8 * DIA_MS
    out = []
    for s in con.execute('SELECT * FROM sucursales WHERE cuenta_id = ? ORDER BY orden, creado', (g.cuenta['id'],)):
        ventas = [fila_venta(r) for r in con.execute('SELECT * FROM ventas WHERE sucursal_id = ? AND ts >= ? ORDER BY ts', (s['id'], desde))]
        alertas = []
        for r in con.execute('SELECT * FROM productos WHERE sucursal_id = ? AND activo = 1', (s['id'],)):
            nivel = round(r['existencia'] / r['declarado'] * 100) if r['declarado'] and r['declarado'] > 0 else 0
            nivel = max(0, min(100, nivel))
            if r['existencia'] <= 0 or nivel < 20:
                alertas.append({'nombre': r['nombre'], 'existencia': r['existencia'], 'nivel': nivel, 'unidad': r['unidad'], 'agotado': r['existencia'] <= 0})
        out.append({'id': s['id'], 'nombre': s['nombre'], 'moneda': s['moneda'], 'ventas': ventas, 'alertas': alertas})
    return jsonify(sucursales=out)


# ---------------- operaciones de una sucursal ----------------
def registrar_venta(d):
    con = db()
    sid = g.suc['id']
    vid = texto(d.get('id'), 40) or uid()
    if con.execute('SELECT 1 FROM ventas WHERE id = ?', (vid,)).fetchone():
        return None  # reintento de una venta ya registrada
    lineas = []
    for l in (d.get('lineas') or [])[:100]:
        if not isinstance(l, dict):
            continue
        cantidad = r3(num(l.get('cantidad')))
        precio = r2(num(l.get('precio')))
        if cantidad <= 0 or precio < 0:
            continue
        p = producto(con, sid, texto(l.get('pid'), 40))
        lineas.append({'pid': p['id'] if p else '', 'nombre': p['nombre'] if p else (texto(l.get('nombre'), 40) or 'Producto'),
                       'cantidad': cantidad, 'unidad': p['unidad'] if p else unidad_valida(l.get('unidad')),
                       'precio': precio, 'importe': r2(cantidad * precio), 'mayoreo': bool(l.get('mayoreo'))})
    if not lineas:
        return 'El ticket está vacío'
    total = r2(sum(l['importe'] for l in lineas))
    recibido = d.get('recibido')
    recibido = total if recibido in (None, '') else r2(num(recibido))
    if recibido < total:
        return 'Lo recibido no cubre el total'
    ts = int(num(d.get('ts'), 0))
    hoy = ahora()
    if not (hoy - 30 * DIA_MS <= ts <= hoy + 300000):
        ts = hoy
    for l in lineas:
        if l['pid']:
            con.execute('UPDATE productos SET existencia = ROUND(existencia - ?, 3) WHERE id = ?', (l['cantidad'], l['pid']))
            movimiento(con, sid, 'venta', producto(con, sid, l['pid']), l['cantidad'], '', ts)
    con.execute('INSERT INTO ventas VALUES (?,?,?,?,?,?,?)',
                (vid, sid, ts, json.dumps(lineas, ensure_ascii=False), total, recibido, r2(recibido - total)))
    con.commit()
    return None


@app.post('/api/c/<clave>/ventas')
@con_caja
def api_caja_venta():
    err = registrar_venta(cuerpo())
    return error(err) if err else responder()


@app.get('/api/c/<clave>/estado')
@con_caja
def api_caja_estado():
    return responder()


@app.post('/api/mi/sucursales/<sid>/ventas')
@con_sucursal
def api_venta():
    err = registrar_venta(cuerpo())
    return error(err) if err else responder()


@app.post('/api/mi/sucursales/<sid>/entradas')
@con_sucursal
def api_entrada():
    d = cuerpo()
    con = db()
    p = producto(con, g.suc['id'], texto(d.get('pid'), 40))
    if not p:
        return error('Producto no encontrado', 404)
    c = r3(num(d.get('cantidad')))
    if c <= 0:
        return error('Escribe una cantidad')
    nueva = r3(max(0.0, p['existencia']) + c)
    con.execute('UPDATE productos SET existencia = ?, declarado = ? WHERE id = ?', (nueva, nueva, p['id']))
    movimiento(con, g.suc['id'], 'entrada', p, c, texto(d.get('nota')))
    con.commit()
    return responder()


@app.post('/api/mi/sucursales/<sid>/ajustes')
@con_sucursal
def api_ajuste():
    d = cuerpo()
    con = db()
    p = producto(con, g.suc['id'], texto(d.get('pid'), 40))
    if not p:
        return error('Producto no encontrado', 404)
    nueva = r3(max(0.0, num(d.get('existencia'))))
    delta = r3(nueva - p['existencia'])
    con.execute('UPDATE productos SET existencia = ?, declarado = ? WHERE id = ?', (nueva, max(p['declarado'], nueva), p['id']))
    tipo = 'merma' if d.get('motivo') == 'merma' else 'ajuste'
    movimiento(con, g.suc['id'], tipo, p, abs(delta) if tipo == 'merma' else delta)
    con.commit()
    return responder()


@app.post('/api/mi/sucursales/<sid>/carga')
@con_sucursal
def api_carga():
    """Tabla de Dirección: precio, mayoreo y stock actual de varios productos de una vez."""
    d = cuerpo()
    con = db()
    sid = g.suc['id']
    cambios = 0
    ts = ahora()
    for it in (d.get('items') or [])[:500]:
        if not isinstance(it, dict):
            continue
        p = producto(con, sid, texto(it.get('id'), 40))
        if not p:
            continue
        if it.get('precio') not in (None, ''):
            precio = r2(max(0.0, num(it.get('precio'))))
            if precio != p['precio']:
                con.execute('UPDATE productos SET precio = ? WHERE id = ?', (precio, p['id']))
                cambios += 1
        if it.get('precio_mayoreo') is not None or it.get('mayoreo_desde') is not None:
            pm = r2(max(0.0, num(it.get('precio_mayoreo'))))
            md = r3(max(0.0, num(it.get('mayoreo_desde'))))
            if pm != (p['precio_mayoreo'] or 0) or md != (p['mayoreo_desde'] or 0):
                con.execute('UPDATE productos SET precio_mayoreo = ?, mayoreo_desde = ? WHERE id = ?', (pm, md, p['id']))
                cambios += 1
        if it.get('existencia') not in (None, ''):
            v = r3(max(0.0, num(it.get('existencia'))))
            if v != r3(max(0.0, p['existencia'])):
                delta = r3(v - p['existencia'])
                con.execute('UPDATE productos SET existencia = ?, declarado = ? WHERE id = ?', (v, v, p['id']))
                movimiento(con, sid, 'entrada' if delta > 0 else 'ajuste', p, delta, 'Carga desde Dirección', ts)
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
            'emoji': texto(d.get('emoji'), 8), 'foto': foto,
            'precio_mayoreo': r2(max(0.0, num(d.get('precio_mayoreo')))), 'mayoreo_desde': r3(max(0.0, num(d.get('mayoreo_desde'))))}, None


@app.post('/api/mi/sucursales/<sid>/productos')
@con_sucursal
def api_producto_nuevo():
    datos, err = datos_producto(cuerpo())
    if err:
        return error(err)
    con = db()
    orden = con.execute('SELECT COALESCE(MAX(orden), -1) + 1 FROM productos WHERE sucursal_id = ?', (g.suc['id'],)).fetchone()[0]
    con.execute(INS_PRODUCTO, (uid(), g.suc['id'], datos['nombre'], datos['ilus'], datos['emoji'], datos['foto'], datos['unidad'], datos['precio'],
                               1, 0, 0, orden, datos['descripcion'], datos['precio_mayoreo'], datos['mayoreo_desde']))
    con.commit()
    return responder()


@app.put('/api/mi/sucursales/<sid>/productos/<pid>')
@con_sucursal
def api_producto_editar(pid):
    con = db()
    if not producto(con, g.suc['id'], pid):
        return error('Producto no encontrado', 404)
    datos, err = datos_producto(cuerpo())
    if err:
        return error(err)
    con.execute('UPDATE productos SET nombre = ?, ilus = ?, emoji = ?, foto = ?, unidad = ?, precio = ?, descripcion = ?, precio_mayoreo = ?, mayoreo_desde = ? WHERE id = ?',
                (datos['nombre'], datos['ilus'], datos['emoji'], datos['foto'], datos['unidad'], datos['precio'], datos['descripcion'],
                 datos['precio_mayoreo'], datos['mayoreo_desde'], pid))
    con.commit()
    return responder()


@app.delete('/api/mi/sucursales/<sid>/productos/<pid>')
@con_sucursal
def api_producto_borrar(pid):
    con = db()
    con.execute('DELETE FROM productos WHERE id = ? AND sucursal_id = ?', (pid, g.suc['id']))
    con.commit()
    return responder()


@app.post('/api/mi/sucursales/<sid>/productos/<pid>/activo')
@con_sucursal
def api_producto_activo(pid):
    con = db()
    if not producto(con, g.suc['id'], pid):
        return error('Producto no encontrado', 404)
    con.execute('UPDATE productos SET activo = ? WHERE id = ?', (1 if cuerpo().get('activo') else 0, pid))
    con.commit()
    return responder()


# ---------------- datos: limpio, ejemplo, borrar, restaurar ----------------
def _vaciar(con, sid, productos_tambien=False):
    con.execute('DELETE FROM ventas WHERE sucursal_id = ?', (sid,))
    con.execute('DELETE FROM movimientos WHERE sucursal_id = ?', (sid,))
    if productos_tambien:
        con.execute('DELETE FROM productos WHERE sucursal_id = ?', (sid,))
    else:
        con.execute('UPDATE productos SET existencia = 0, declarado = 0 WHERE sucursal_id = ?', (sid,))


@app.post('/api/mi/sucursales/<sid>/limpio')
@con_sucursal
def api_limpio():
    con = db()
    _vaciar(con, g.suc['id'])
    con.execute('UPDATE sucursales SET ejemplo = 0 WHERE id = ?', (g.suc['id'],))
    con.commit()
    return responder()


@app.post('/api/mi/sucursales/<sid>/borrar')
@con_sucursal
def api_borrar():
    con = db()
    _vaciar(con, g.suc['id'], True)
    sembrar_catalogo(con, g.suc['id'])
    con.execute('UPDATE sucursales SET ejemplo = 0 WHERE id = ?', (g.suc['id'],))
    con.commit()
    return responder()


@app.post('/api/mi/sucursales/<sid>/ejemplo')
@con_sucursal
def api_ejemplo():
    """Siembra el catálogo con existencia en 10 productos y una semana de ventas inventadas, para enseñar el sistema."""
    con = db()
    sid = g.suc['id']
    _vaciar(con, sid, True)
    azar = random.Random(20260925)
    stock = {'Plátano': (20, 14.5), 'Manzana': (15, 12), 'Melón': (25, 9), 'Sandía': (40, 31), 'Limón': (10, 1.6),
             'Cilantro': (30, 22), 'Perejil': (20, 0), 'Aguacate': (12, 6.8), 'Jitomate': (18, 11), 'Cebolla': (15, 9.5)}
    activos = {n for n in stock if n != 'Perejil'}
    t = time.localtime()
    base_hoy = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))) * 1000
    creados = sembrar_catalogo(con, sid, activos, stock)
    prods = []
    for i, p in enumerate(creados):
        if p['declarado'] > 0:
            movimiento(con, sid, 'entrada', p, p['declarado'], 'Central de abastos', base_hoy + (7 * 60 + 30 + i) * 60000)
        if p['nombre'] in activos:
            prods.append(p)
    limite = ahora() - 60000
    for d in range(6, -1, -1):
        dia = base_hoy - d * DIA_MS
        for _ in range(azar.randint(2, 5) if d else 2):
            ts = dia + azar.randint(8, 17) * 3600000 + azar.randint(0, 59) * 60000
            if d == 0:
                ts = min(ts, limite)
            lineas = []
            for p in azar.sample(prods, azar.randint(1, 3)):
                cantidad = r3(0.25 + azar.randint(0, 11) * 0.25) if p['unidad'] == 'kg' else float(azar.randint(1, 3))
                lineas.append({'pid': p['id'], 'nombre': p['nombre'], 'cantidad': cantidad, 'unidad': p['unidad'],
                               'precio': p['precio'], 'importe': r2(cantidad * p['precio']), 'mayoreo': False})
                if d == 0:
                    movimiento(con, sid, 'venta', p, cantidad, '', ts)
            total = r2(sum(l['importe'] for l in lineas))
            recibido = float(-(-total // 50) * 50) or total
            con.execute('INSERT INTO ventas VALUES (?,?,?,?,?,?,?)',
                        (uid(), sid, ts, json.dumps(lineas, ensure_ascii=False), total, recibido, r2(recibido - total)))
    con.execute('UPDATE sucursales SET ejemplo = 1 WHERE id = ?', (sid,))
    con.commit()
    return responder()


@app.post('/api/mi/sucursales/<sid>/restaurar')
@con_sucursal
def api_restaurar():
    """Carga un respaldo copiado desde Ajustes en esta sucursal."""
    d = cuerpo()
    if not isinstance(d.get('productos'), list) or not isinstance(d.get('negocio'), dict):
        return error('Ese texto no es un respaldo válido')
    con = db()
    sid = g.suc['id']
    _vaciar(con, sid, True)
    n = d['negocio']
    con.execute('UPDATE sucursales SET nombre = ?, moneda = ?, ejemplo = ? WHERE id = ?',
                (texto(n.get('nombre'), 40) or g.suc['nombre'], texto(n.get('moneda'), 4) or '$', 1 if n.get('ejemplo') else 0, sid))
    ids = set()
    for i, p in enumerate(d['productos'][:500]):
        if not isinstance(p, dict):
            continue
        datos, err = datos_producto(p)
        if err:
            continue
        pid = texto(p.get('id'), 40) or uid()
        if pid in ids or con.execute('SELECT 1 FROM productos WHERE id = ?', (pid,)).fetchone():
            pid = uid()
        ids.add(pid)
        con.execute(INS_PRODUCTO, (pid, sid, datos['nombre'], datos['ilus'], datos['emoji'], datos['foto'], datos['unidad'], datos['precio'],
                                   0 if p.get('activo') is False else 1, r3(max(0.0, num(p.get('declarado')))), r3(num(p.get('existencia'))), i,
                                   datos['descripcion'], datos['precio_mayoreo'], datos['mayoreo_desde']))
    for m in (d.get('movimientos') or [])[:20000]:
        if not isinstance(m, dict):
            continue
        con.execute('INSERT OR IGNORE INTO movimientos VALUES (?,?,?,?,?,?,?,?,?)',
                    (texto(m.get('id'), 40) or uid(), sid, int(num(m.get('ts'), ahora())), texto(m.get('tipo'), 10) or 'ajuste',
                     texto(m.get('pid'), 40), texto(m.get('nombre'), 40), r3(num(m.get('cantidad'))),
                     unidad_valida(m.get('unidad')), texto(m.get('nota'), 60)))
    for v in (d.get('ventas') or [])[:20000]:
        if not isinstance(v, dict) or not isinstance(v.get('lineas'), list):
            continue
        total = r2(num(v.get('total')))
        recibido = r2(num(v.get('recibido'), total))
        con.execute('INSERT OR IGNORE INTO ventas VALUES (?,?,?,?,?,?,?)',
                    (texto(v.get('id'), 40) or uid(), sid, int(num(v.get('ts'), ahora())),
                     json.dumps(v['lineas'][:100], ensure_ascii=False), total, recibido, r2(recibido - total)))
    con.commit()
    return responder()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '8080')), debug=False)
