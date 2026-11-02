"""
Sistema de Solicitudes a Proveedores e Inventario - FastAPI Single File Backend
Stack: Python 3.11+, FastAPI, Pydantic v2, SQLite, Passlib (Bcrypt), PyJWT.
"""

import os
import sqlite3
import random
import string
import hashlib
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator
from passlib.context import CryptContext
import jwt

SECRET_KEY = os.getenv("SECRET_KEY", "super-secret-key-change-in-production-12345")
ALGORITHM = "HS256"
DB_FILE = "inventario_proveedores.db"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer()

app = FastAPI(
    title="Sistema de Solicitudes a Proveedores e Inventario API",
    version="1.6.0",
    description="API REST con FastAPI, SQLite y validación avanzada de fechas."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS roles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT UNIQUE NOT NULL,
        descripcion TEXT,
        permisos TEXT NOT NULL
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        estado TEXT DEFAULT 'pendiente',
        intentos_fallidos INTEGER DEFAULT 0,
        bloqueado_hasta TIMESTAMP,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS usuario_roles (
        usuario_id INTEGER,
        rol_id INTEGER,
        proveedor_id INTEGER,
        PRIMARY KEY (usuario_id, rol_id),
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
        FOREIGN KEY (rol_id) REFERENCES roles(id) ON DELETE CASCADE
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sesiones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        dispositivo_id TEXT NOT NULL,
        ip TEXT,
        user_agent TEXT,
        activa BOOLEAN DEFAULT 1,
        creada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expira_en TIMESTAMP NOT NULL,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tokens_verificacion (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        codigo_hash TEXT NOT NULL,
        intentos INTEGER DEFAULT 0,
        expira_en TIMESTAMP NOT NULL,
        usado BOOLEAN DEFAULT 0,
        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS productos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        descripcion TEXT,
        unidad TEXT NOT NULL,
        activo BOOLEAN DEFAULT 1
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS proveedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT UNIQUE NOT NULL,
        nombre TEXT NOT NULL,
        nit TEXT NOT NULL,
        email TEXT NOT NULL,
        telefono TEXT,
        activo BOOLEAN DEFAULT 1
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS solicitudes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        numero TEXT UNIQUE NOT NULL,
        proveedor_id INTEGER NOT NULL,
        fecha_entrega DATE NOT NULL,
        estado TEXT NOT NULL,
        observaciones TEXT,
        creado_por INTEGER NOT NULL,
        creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (proveedor_id) REFERENCES proveedores(id),
        FOREIGN KEY (creado_por) REFERENCES usuarios(id)
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS lineas_solicitud (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        solicitud_id INTEGER NOT NULL,
        producto_id INTEGER NOT NULL,
        codigo TEXT NOT NULL,
        nombre TEXT NOT NULL,
        cant_solicitada INTEGER NOT NULL,
        cant_confirmada INTEGER DEFAULT 0,
        cant_recibida INTEGER DEFAULT 0,
        recibido BOOLEAN DEFAULT 0,
        motivo TEXT,
        FOREIGN KEY (solicitud_id) REFERENCES solicitudes(id) ON DELETE CASCADE,
        FOREIGN KEY (producto_id) REFERENCES productos(id)
    )""")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS inventario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        producto_id INTEGER UNIQUE NOT NULL,
        codigo TEXT NOT NULL,
        nombre TEXT NOT NULL,
        cantidad INTEGER DEFAULT 0,
        actualizado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (producto_id) REFERENCES productos(id)
    )""")
    
    conn.commit()
    conn.close()
    seed_initial_data()

def seed_initial_data():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM roles")
        if cursor.fetchone()[0] > 0:
            conn.close()
            return

        roles = [
            ("Administrador", "Gestión total del sistema", "gestion_usuarios,gestion_productos,gestion_solicitudes,enviar_solicitud,confirmar_entrega,registrar_recepcion,consultar_inventario,consultar_movimientos,ver_bitacora"),
            ("Compras", "Crear y gestionar solicitudes y catálogos", "gestion_productos,gestion_solicitudes,enviar_solicitud,consultar_inventario,consultar_movimientos"),
            ("Proveedor", "Confirmar cantidades asignadas", "confirmar_entrega,consultar_movimientos"),
            ("Bodega", "Registrar recepciones de entregas", "registrar_recepcion,consultar_inventario,consultar_movimientos"),
            ("Consulta", "Solo consultas generales", "consultar_inventario,consultar_movimientos")
        ]
        for r in roles:
            cursor.execute("INSERT OR IGNORE INTO roles (nombre, descripcion, permisos) VALUES (?, ?, ?)", r)
        
        proveedores = [
            ("PROV-001", "Tecnología Global S.A.", "12345678-9", "contacto@tecglobal.com", "5551-2345"),
            ("PROV-002", "Suministros Industriales del Norte", "98765432-1", "ventas@suministrosnorte.com", "5552-8765")
        ]
        for p in proveedores:
            cursor.execute("INSERT OR IGNORE INTO proveedores (codigo, nombre, nit, email, telefono) VALUES (?, ?, ?, ?, ?)", p)

        productos = [
            ("PROD-001", "Laptop Corporativa i5", "Ordenador portátil 14 pulgadas 16GB RAM", "Unidad"),
            ("PROD-002", "Monitor LED 24\"", "Monitor Full HD IPS", "Unidad")
        ]
        for pr in productos:
            cursor.execute("INSERT OR IGNORE INTO productos (codigo, nombre, descripcion, unidad) VALUES (?, ?, ?, ?)", pr)
            cursor.execute("SELECT id FROM productos WHERE codigo = ?", (pr[0],))
            p_id = cursor.fetchone()[0]
            cursor.execute("INSERT OR IGNORE INTO inventario (producto_id, codigo, nombre, cantidad) VALUES (?, ?, ?, ?)", (p_id, pr[0], pr[1], random.randint(10, 50)))

        pass_hash = pwd_context.hash("Password123!")
        usuarios_demo = [
            ("Administrador General", "admin@empresa.com", 1, None),
            ("Comprador Principal", "compras@empresa.com", 2, None),
            ("Proveedor Tecnologías", "proveedor1@tecglobal.com", 3, 1),
            ("Encargado Bodega", "bodega@empresa.com", 4, None),
            ("Usuario Consulta", "consulta@empresa.com", 5, None)
        ]
        for nombre, email, rol_id, prov_id in usuarios_demo:
            cursor.execute("INSERT OR IGNORE INTO usuarios (nombre, email, password_hash, estado) VALUES (?, ?, ?, 'activo')", (nombre, email, pass_hash))
            cursor.execute("SELECT id FROM usuarios WHERE email = ?", (email,))
            u_id = cursor.fetchone()[0]
            cursor.execute("INSERT OR IGNORE INTO usuario_roles (usuario_id, rol_id, proveedor_id) VALUES (?, ?, ?)", (u_id, rol_id, prov_id))

        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"❌ Error al cargar datos seed: {e}")
    finally:
        conn.close()

class RegistroRequest(BaseModel):
    nombre: str = Field(..., min_length=3, max_length=100)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=64)
    confirmar_password: str
    captcha_token: str = Field(..., min_length=1)

    @model_validator(mode="after")
    def validar_contrasenas(self) -> "RegistroRequest":
        if self.password != self.confirmar_password:
            raise ValueError("Las contraseñas no coinciden.")
        pwd = self.password
        if not any(c.isupper() for c in pwd) or not any(c.islower() for c in pwd) or not any(c.isdigit() for c in pwd) or not any(not c.isalnum() for c in pwd):
            raise ValueError("La contraseña debe incluir al menos una mayúscula, una minúscula, un número y un símbolo.")
        return self

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)
    captcha_token: str = Field(..., min_length=1)
    dispositivo_id: str = Field(..., min_length=2, max_length=100)

class VerifyOTPRequest(BaseModel):
    login_ticket: str = Field(..., min_length=10)
    otp: str = Field(..., min_length=6, max_length=6)

    @field_validator("otp")
    def validar_digitos_otp(cls, value):
        if not value.isdigit():
            raise ValueError("El código OTP debe contener únicamente números.")
        return value

class ProductoCreate(BaseModel):
    codigo: str = Field(..., min_length=3, max_length=30)
    nombre: str = Field(..., min_length=2, max_length=100)
    descripcion: Optional[str] = Field(None, max_length=255)
    unidad: str = Field(..., min_length=2, max_length=30)
    activo: bool = True

    @field_validator("codigo")
    def validar_codigo(cls, v):
        return v.strip().upper()

class ProveedorCreate(BaseModel):
    codigo: str = Field(..., min_length=3, max_length=30)
    nombre: str = Field(..., min_length=2, max_length=150)
    nit: str = Field(..., min_length=5, max_length=30)
    email: EmailStr
    telefono: Optional[str] = Field(None, min_length=7, max_length=25)
    activo: bool = True

    @field_validator("codigo")
    def validar_codigo(cls, v):
        return v.strip().upper()

class LineaSolicitudInput(BaseModel):
    producto_id: int = Field(..., gt=0)
    cant_solicitada: int = Field(..., gt=0, le=1000000)


class SolicitudCreate(BaseModel):
    proveedor_id: int = Field(..., gt=0)
    fecha_entrega: str
    observaciones: Optional[str] = Field(None, max_length=500)
    lineas: List[LineaSolicitudInput] = Field(..., min_length=1)

    @field_validator("observaciones")
    def validar_observaciones(cls, v):
        if v is not None:
            obs = v.strip()
            if len(obs) > 0 and len(obs) < 10:
                raise ValueError("Las observaciones o comentarios deben tener al menos 10 caracteres.")
            return obs if len(obs) > 0 else None
        return v

    @field_validator("fecha_entrega")
    def validar_formato_y_rango_fecha(cls, value):
        if not value or not isinstance(value, str):
            raise ValueError("La fecha de entrega es obligatoria.")
        val = value.strip()
        try:
            fecha_parsed = datetime.strptime(val, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Fecha inválida. Utilice el formato YYYY-MM-DD.")
        
        if fecha_parsed.date() < datetime.utcnow().date():
            raise ValueError(f"La fecha de entrega no puede ser anterior a hoy.")
        return val

def crear_token_acceso(data: dict):
    expire = datetime.utcnow() + timedelta(hours=8)
    data.update({"exp": expire})
    return jwt.encode(data, SECRET_KEY, algorithm=ALGORITHM)

def verificar_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        return jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except:
        raise HTTPException(status_code=401, detail="Token de acceso inválido o expirado.")

def verificar_permiso(permiso_requerido: str):
    def dependency(payload: dict = Depends(verificar_token)):
        conn = get_db()
        cursor = conn.cursor()
        usuario_id = payload.get("sub")
        dispositivo_id = payload.get("dispositivo_id")
        
        cursor.execute("SELECT id FROM sesiones WHERE usuario_id = ? AND dispositivo_id = ? AND activa = 1", (usuario_id, dispositivo_id))
        if not cursor.fetchone():
            conn.close()
            raise HTTPException(status_code=401, detail="Sesión inválida o expirada.")
        
        cursor.execute("""
            SELECT r.nombre, r.permisos FROM roles r
            JOIN usuario_roles ur ON r.id = ur.rol_id
            WHERE ur.usuario_id = ?
        """, (usuario_id,))
        rows = cursor.fetchall()
        conn.close()
        
        permisos_acumulados = set()
        nombres_roles = []
        for row in rows:
            nombres_roles.append(row["nombre"])
            if row["permisos"]:
                for p in row["permisos"].split(","):
                    permisos_acumulados.add(p.strip())
            
        if "Administrador" not in nombres_roles and permiso_requerido not in permisos_acumulados:
            raise HTTPException(status_code=403, detail=f"Permiso denegado. Se requiere: '{permiso_requerido}'.")
        return payload
    return dependency

@app.post("/api/v1/auth/register")
def registrar_usuario(data: RegistroRequest):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM usuarios WHERE email = ?", (data.email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="El correo electrónico ya está registrado.")
    
    pwd_hash = pwd_context.hash(data.password)
    cursor.execute("INSERT INTO usuarios (nombre, email, password_hash, estado) VALUES (?, ?, ?, 'pendiente')",
                   (data.nombre.strip(), data.email, pwd_hash))
    usuario_id = cursor.lastrowid
    cursor.execute("INSERT INTO usuario_roles (usuario_id, rol_id) VALUES (?, 5)", (usuario_id,))
    
    otp_code = "".join(random.choices(string.digits, k=6))
    cursor.execute("INSERT INTO tokens_verificacion (usuario_id, tipo, codigo_hash, expira_en) VALUES (?, 'verificar_email', ?, ?)",
                   (usuario_id, hashlib.sha256(otp_code.encode()).hexdigest(), datetime.utcnow() + timedelta(minutes=15)))
    conn.commit()
    conn.close()
    print(f"\n[CORREO SIMULADO] Código activación {data.email}: {otp_code}\n")
    return {"mensaje": "Usuario registrado. Revisa la consola de FastAPI por tu código.", "usuario_id": usuario_id}

@app.post("/api/v1/auth/verify-email")
def verificar_email(usuario_id: int, codigo: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tokens_verificacion WHERE usuario_id = ? AND tipo = 'verificar_email' AND usado = 0 ORDER BY id DESC LIMIT 1", (usuario_id,))
    token = cursor.fetchone()
    if not token or token["codigo_hash"] != hashlib.sha256(codigo.encode()).hexdigest():
        conn.close()
        raise HTTPException(status_code=400, detail="Código de verificación incorrecto.")
    cursor.execute("UPDATE usuarios SET estado = 'activo' WHERE id = ?", (usuario_id,))
    cursor.execute("UPDATE tokens_verificacion SET usado = 1 WHERE id = ?", (token["id"],))
    conn.commit()
    conn.close()
    return {"mensaje": "Cuenta activada exitosamente."}

@app.post("/api/v1/auth/login")
def login_paso1(data: LoginRequest, request: Request):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM usuarios WHERE email = ?", (data.email,))
    user = cursor.fetchone()
    if not user or not pwd_context.verify(data.password, user["password_hash"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Credenciales incorrectas.")
    if user["estado"] != 'activo':
        conn.close()
        raise HTTPException(status_code=403, detail="La cuenta no está activa.")

    otp_code = "".join(random.choices(string.digits, k=6))
    cursor.execute("INSERT INTO tokens_verificacion (usuario_id, tipo, codigo_hash, expira_en) VALUES (?, 'otp_login', ?, ?)",
                   (user["id"], hashlib.sha256(otp_code.encode()).hexdigest(), datetime.utcnow() + timedelta(minutes=5)))
    conn.commit()
    conn.close()
    print(f"\n[CORREO OTP SIMULADO] Código para {data.email}: {otp_code}\n")
    ticket = hashlib.sha256(f"{user['id']}:{data.dispositivo_id}".encode()).hexdigest()
    return {"status": "otp_required", "login_ticket": ticket, "usuario_id": user["id"], "mensaje": "OTP enviado a la consola del backend."}

@app.post("/api/v1/auth/verify-otp")
def login_paso2(data: VerifyOTPRequest, request: Request):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tokens_verificacion WHERE tipo = 'otp_login' AND usado = 0 ORDER BY id DESC LIMIT 1")
    token = cursor.fetchone()
    if not token or token["codigo_hash"] != hashlib.sha256(data.otp.encode()).hexdigest():
        conn.close()
        raise HTTPException(status_code=400, detail="Código OTP incorrecto.")
    
    usuario_id = token["usuario_id"]
    cursor.execute("UPDATE tokens_verificacion SET usado = 1 WHERE id = ?", (token["id"],))
    cursor.execute("UPDATE sesiones SET activa = 0 WHERE usuario_id = ?", (usuario_id,))
    
    dispositivo_id = "device_default"
    cursor.execute("INSERT INTO sesiones (usuario_id, dispositivo_id, ip, activa, expira_en) VALUES (?, ?, ?, 1, ?)",
                   (usuario_id, dispositivo_id, request.client.host, datetime.utcnow() + timedelta(hours=8)))
    conn.commit()
    
    cursor.execute("SELECT r.nombre FROM roles r JOIN usuario_roles ur ON r.id = ur.rol_id WHERE ur.usuario_id = ?", (usuario_id,))
    roles = [row["nombre"] for row in cursor.fetchall()]
    cursor.execute("SELECT nombre, email FROM usuarios WHERE id = ?", (usuario_id,))
    user_info = cursor.fetchone()
    conn.close()
    
    token_jwt = crear_token_acceso({"sub": str(usuario_id), "email": user_info["email"], "roles": roles, "dispositivo_id": dispositivo_id})
    return {"access_token": token_jwt, "token_type": "bearer", "usuario": {"id": usuario_id, "nombre": user_info["nombre"], "roles": roles}}

@app.get("/api/v1/products")
def listar_productos(payload: dict = Depends(verificar_permiso("consultar_inventario"))):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM productos")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/api/v1/products")
def crear_producto(data: ProductoCreate, payload: dict = Depends(verificar_permiso("gestion_productos"))):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO productos (codigo, nombre, descripcion, unidad, activo) VALUES (?, ?, ?, ?, ?)",
                       (data.codigo, data.nombre.strip(), data.descripcion, data.unidad.strip(), 1 if data.activo else 0))
        prod_id = cursor.lastrowid
        cursor.execute("INSERT OR IGNORE INTO inventario (producto_id, codigo, nombre, cantidad) VALUES (?, ?, ?, 0)",
                       (prod_id, data.codigo, data.nombre.strip()))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="El código de producto ya existe.")
    conn.close()
    return {"mensaje": "Producto registrado con éxito.", "id": prod_id}

@app.get("/api/v1/suppliers")
def listar_proveedores(payload: dict = Depends(verificar_permiso("consultar_inventario"))):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM proveedores")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/api/v1/suppliers")
def crear_proveedor(data: ProveedorCreate, payload: dict = Depends(verificar_permiso("gestion_productos"))):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO proveedores (codigo, nombre, nit, email, telefono, activo) VALUES (?, ?, ?, ?, ?, ?)",
                       (data.codigo, data.nombre.strip(), data.nit.strip(), data.email, data.telefono, 1 if data.activo else 0))
        prov_id = cursor.lastrowid
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(status_code=400, detail="El código o NIT ya existe.")
    conn.close()
    return {"mensaje": "Proveedor registrado con éxito.", "id": prov_id}

@app.post("/api/v1/requests")
def crear_solicitud(data: SolicitudCreate, payload: dict = Depends(verificar_permiso("gestion_solicitudes"))):
    usuario_id = payload.get("sub")
    if data.observaciones:
        obs = data.observaciones.strip()
        if 0 < len(obs) < 3:
            raise HTTPException(status_code=400, detail="Las observaciones deben tener al menos 3 caracteres.")
        data.observaciones = obs if len(obs) > 0 else None

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM proveedores WHERE id = ? AND activo = 1", (data.proveedor_id,))
    if not cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=404, detail="El proveedor no existe o está inactivo.")

    cursor.execute("SELECT COUNT(*) FROM solicitudes")
    count = cursor.fetchone()[0] + 1
    numero_sol = f"SOL-{datetime.utcnow().year}-{count:06d}"
    
    cursor.execute("""
        INSERT INTO solicitudes (numero, proveedor_id, fecha_entrega, estado, observaciones, creado_por)
        VALUES (?, ?, ?, 'Borrador', ?, ?)
    """, (numero_sol, data.proveedor_id, data.fecha_entrega, data.observaciones, usuario_id))
    solicitud_id = cursor.lastrowid
    
    for linea in data.lineas:
        cursor.execute("SELECT codigo, nombre, activo FROM productos WHERE id = ?", (linea.producto_id,))
        prod = cursor.fetchone()
        if not prod or not prod["activo"]:
            conn.close()
            raise HTTPException(status_code=404, detail=f"El producto ID {linea.producto_id} no existe o está inactivo.")
        cursor.execute("""
            INSERT INTO lineas_solicitud (solicitud_id, producto_id, codigo, nombre, cant_solicitada)
            VALUES (?, ?, ?, ?, ?)
        """, (solicitud_id, linea.producto_id, prod["codigo"], prod["nombre"], linea.cant_solicitada))
        
    conn.commit()
    conn.close()
    return {"mensaje": "Solicitud creada con éxito.", "id": solicitud_id, "numero": numero_sol}

@app.get("/api/v1/requests")
def listar_solicitudes(payload: dict = Depends(verificar_permiso("consultar_inventario"))):
    usuario_id = int(payload.get("sub"))
    roles = payload.get("roles", [])
    conn = get_db()
    cursor = conn.cursor()
    
    if "Proveedor" in roles and "Administrador" not in roles and "Compras" not in roles:
        cursor.execute("SELECT proveedor_id FROM usuario_roles WHERE usuario_id = ?", (usuario_id,))
        prov_row = cursor.fetchone()
        prov_id = prov_row["proveedor_id"] if prov_row else 0
        cursor.execute("SELECT * FROM solicitudes WHERE proveedor_id = ?", (prov_id,))
    else:
        cursor.execute("SELECT * FROM solicitudes")
        
    solicitudes = cursor.fetchall()
    resultado = []
    for s in solicitudes:
        s_dict = dict(s)
        cursor.execute("SELECT * FROM lineas_solicitud WHERE solicitud_id = ?", (s["id"],))
        s_dict["lineas"] = [dict(l) for l in cursor.fetchall()]
        resultado.append(s_dict)
    conn.close()
    return resultado

@app.on_event("startup")
def startup_event():
    init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)