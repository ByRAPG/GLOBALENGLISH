from flask import Flask, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash, check_password_hash
import mysql
from mysql.connector import Error
from functools import wraps          # ⬅️ IMPORTANTE: esto debe estar aquí

from config import DB_CONFIG
from datetime import datetime, date


app = Flask(__name__)
app.secret_key = "supersecretkey"  # cambia en producción


def get_connection():
    """Crea y retorna una conexión a MySQL usando DB_CONFIG."""
    try:
        conn = mysql.connector.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print("Error al conectar a MySQL:", e)
        return None


# =========================
# RUTA PRINCIPAL
# =========================
@app.route("/")
def index():
    return render_template("index.html")


# =========================
# INSTITUCIONES
# =========================



@app.route("/instituciones/nueva", methods=["GET", "POST"])
def instituciones_new():
    if request.method == "POST":
        nombre = request.form.get("nombre")
        codigo_dane = request.form.get("codigo_dane")
        tipo_jornada = request.form.get("tipo_jornada")
        telefono = request.form.get("telefono")
        email = request.form.get("email")

        if not nombre or not codigo_dane or not tipo_jornada:
            flash("Nombre, código DANE y tipo de jornada son obligatorios.", "danger")
        else:
            conn = get_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO institucion (nombre, codigo_dane, tipo_jornada, telefono, email)
                        VALUES (%s, %s, %s, %s, %s);
                    """, (nombre, codigo_dane, tipo_jornada, telefono, email))
                    conn.commit()
                    flash("Institución creada correctamente.", "success")
                    cursor.close()
                except Error as e:
                    conn.rollback()
                    flash(f"Error al crear institución: {e}", "danger")
                finally:
                    conn.close()
            else:
                flash("No hay conexión con la base de datos.", "danger")

        return redirect(url_for("instituciones_list"))

    # GET
    return render_template("instituciones_form.html")


# =========================
# AULAS POR INSTITUCIÓN
# =========================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("rol") not in roles:
                flash("No tienes permiso para acceder a esta sección.", "danger")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return wrapper
    return decorator

@app.route("/admin/usuarios/nuevo", methods=["GET", "POST"])
@role_required("ADMINISTRADOR")
def admin_nuevo_usuario():
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("index"))

    cursor = conn.cursor(dictionary=True)

    # Cargar roles disponibles (por ejemplo todos excepto ADMINISTRADOR,
    # o dejar también ADMINISTRADOR si quieres que un admin cree otros admins)
    cursor.execute("SELECT id_rol, nombre_rol FROM rol;")
    roles = cursor.fetchall()

    # Cargar tipos de documento si quieres desplegarlos en un select
    cursor.execute("SELECT id_tipo_documento, nombre FROM tipo_documento;")
    tipos_doc = cursor.fetchall()

    cursor.close()

    if request.method == "POST":
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        numero_doc = request.form.get("numero_documento")
        id_tipo_documento = request.form.get("id_tipo_documento")
        id_rol = request.form.get("id_rol")
        password = request.form.get("password")

        nombres, apellidos = full_name.split(" ", 1) if " " in full_name else (full_name, "")

        try:
            cursor = conn.cursor()

            # 1. Insertar en PERSONA
            cursor.execute("""
                INSERT INTO persona (id_tipo_documento, numero_documento,
                                     nombres, apellidos, email, tipo_perfil_contrato)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (id_tipo_documento, numero_doc, nombres, apellidos, email, "TUTOR"))  # o según rol
            id_persona = cursor.lastrowid

            # 2. Insertar en USUARIO_SISTEMA
            password_hash = generate_password_hash(password)
            cursor.execute("""
                INSERT INTO usuario_sistema (username, password_hash, activo, id_persona, id_rol)
                VALUES (%s, %s, 1, %s, %s);
            """, (email, password_hash, id_persona, id_rol))

            conn.commit()
            flash("Usuario creado correctamente.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Error al crear usuario: {e}", "danger")
        finally:
            conn.close()

        return redirect(url_for("admin_nuevo_usuario"))

    # GET
    conn.close()
    return render_template("admin_usuario_form.html", roles=roles, tipos_doc=tipos_doc)

# ============================
# 🏫 AULAS
# ============================

# 1. /aulas → lista de instituciones con botón "Agregar aulas"
@app.route("/aulas")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def aulas_list():
    conn = get_connection()
    instituciones = []

    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT 
                    id_institucion,
                    nombre AS nombre_institucion,
                    codigo_dane,
                    activa
                FROM institucion
                WHERE activa = 1              -- solo instituciones activas
                ORDER BY nombre;
            """)
            instituciones = cursor.fetchall()
        except Error as e:
            print("Error al consultar instituciones para aulas:", e)
        finally:
            cursor.close()
            conn.close()

    return render_template("aulas_instituciones.html", instituciones=instituciones)






# 2. /instituciones/<id>/aulas → (opcional) lista de aulas de una institución
@app.route("/instituciones/<int:id_institucion>/aulas")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def aulas_institucion_list(id_institucion):
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("instituciones_list"))

    aulas = []
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT 
                ap.id_aula,
                ap.id_institucion,
                ap.codigo_aula,
                ap.capacidad,
                ap.estado_num,                 -- AHORA ES TINYINT
                i.nombre AS institucion,
                s.nombre_sede AS sede,
                CONCAT(g.nivel, ' ', g.numero_grado) AS grado,
                tp.nombre AS programa
            FROM aula_programa ap
            INNER JOIN institucion i    ON ap.id_institucion   = i.id_institucion
            INNER JOIN sede s           ON ap.id_sede          = s.id_sede
            INNER JOIN grado g          ON ap.id_grado         = g.id_grado
            INNER JOIN tipo_programa tp ON ap.id_tipo_programa = tp.id_tipo_programa
            WHERE ap.id_institucion = %s
            ORDER BY s.nombre_sede, g.nivel, g.numero_grado;
        """, (id_institucion,))
        aulas = cursor.fetchall()
    except Error as e:
        print("ERROR al consultar aulas:", e)
        flash("Error al consultar las aulas.", "danger")
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "aulas_list.html",
        aulas=aulas,
        id_institucion=id_institucion
    )






@app.route("/aulas/toggle/<int:id_aula>/<int:id_institucion>")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def toggle_aula(id_aula, id_institucion):
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("aulas_institucion_list", id_institucion=id_institucion))

    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE aula_programa
            SET estado = CASE 
                            WHEN estado = 'ACTIVA'   THEN 'INACTIVA'
                            WHEN estado = 'INACTIVA' THEN 'ACTIVA'
                            ELSE 'INACTIVA'
                         END
            WHERE id_aula = %s;
        """, (id_aula,))
        print("Filas afectadas toggle_aula:", cursor.rowcount)
        conn.commit()
        if cursor.rowcount == 0:
            flash("No se encontró el aula a actualizar.", "warning")
        else:
            flash("Estado del aula actualizado correctamente.", "success")
    except Error as e:
        conn.rollback()
        print("ERROR toggle_aula:", e)
        flash("Error al actualizar el estado del aula.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("aulas_institucion_list", id_institucion=id_institucion))






@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        conn = get_connection()
        if not conn:
            flash("Error de conexión con la base de datos.", "danger")
            return render_template("login.html")

        cursor = conn.cursor(dictionary=True)
        # suponiendo que username = email
        cursor.execute("""
            SELECT u.id_usuario, u.username, u.password_hash, r.nombre_rol
            FROM usuario_sistema u
            JOIN rol r ON u.id_rol = r.id_rol
            JOIN persona p ON u.id_persona = p.id_persona
            WHERE u.username = %s AND u.activo = 1;
        """, (email,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Usuario o contraseña incorrectos.", "danger")
            return render_template("login.html")

        # Login correcto
        session["user_id"] = user["id_usuario"]
        session["username"] = user["username"]
        session["rol"] = user["nombre_rol"]
        flash(f"Bienvenido/a, {user['nombre_rol'].title()}.", "success")
        return redirect(url_for("index"))  # o tu dashboard

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))



@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        role = request.form.get("role")
        password = request.form.get("password")
        password_confirm = request.form.get("password_confirm")
        # TODO: validar, encriptar password, insertar en persona + usuario_sistema, etc.
    return render_template("register.html")


# ---------------------------------------------------------
# NUEVA AULA PARA UNA INSTITUCIÓN
# ---------------------------------------------------------
@app.route("/instituciones/<int:id_institucion>/aulas/nueva", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def aulas_new(id_institucion):
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("aulas_institucion_list", id_institucion=id_institucion))

    cursor = conn.cursor(dictionary=True)

    # ----------------- POST: guardar aula -----------------
    if request.method == "POST":
        id_sede = request.form.get("id_sede")
        id_grado = request.form.get("id_grado")
        codigo_aula = request.form.get("codigo_aula")
        capacidad = request.form.get("capacidad")

        if not (id_sede and id_grado and codigo_aula):
            flash("Todos los campos marcados con * son obligatorios.", "warning")
            cursor.close()
            conn.close()
            return redirect(url_for("aulas_new", id_institucion=id_institucion))

        try:
            # 1. Obtener el número de grado (4,5,9,10, etc.)
            cursor.execute(
                "SELECT numero_grado FROM grado WHERE id_grado = %s",
                (id_grado,)
            )
            grado_row = cursor.fetchone()
            if not grado_row:
                flash("El grado seleccionado no existe.", "danger")
                cursor.close()
                conn.close()
                return redirect(url_for("aulas_new", id_institucion=id_institucion))

            numero_grado = int(grado_row["numero_grado"])

            # 2. Determinar el nombre del programa según el grado
            if numero_grado in (4, 5):
                nombre_programa = "INSIDECLASSROOM"
            elif numero_grado in (9, 10):
                nombre_programa = "OUTSIDECLASSROOM"
            else:
                # Por si acaso, deja INSIDECLASSROOM por defecto
                nombre_programa = "INSIDECLASSROOM"

            # 3. Obtener el id_tipo_programa a partir del nombre
            cursor.execute(
                "SELECT id_tipo_programa FROM tipo_programa WHERE nombre = %s",
                (nombre_programa,)
            )
            prog_row = cursor.fetchone()
            if not prog_row:
                flash("No se encontró el tipo de programa correspondiente.", "danger")
                cursor.close()
                conn.close()
                return redirect(url_for("aulas_new", id_institucion=id_institucion))

            id_tipo_programa = prog_row["id_tipo_programa"]

            # 4. Insertar el aula (estado = 1 → activa)
            cursor.execute(
                """
                INSERT INTO aula_programa
                    (id_institucion, id_sede, id_grado, id_tipo_programa,
                     codigo_aula, capacidad, estado)
                VALUES (%s, %s, %s, %s, %s, %s, 1);
                """,
                (id_institucion, id_sede, id_grado, id_tipo_programa,
                 codigo_aula, capacidad)
            )
            conn.commit()
            flash("Aula creada correctamente.", "success")

        except Error as e:
            conn.rollback()
            print("ERROR al crear aula:", e)
            flash("Error al crear el aula.", "danger")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("aulas_institucion_list", id_institucion=id_institucion))

    # ----------------- GET: mostrar formulario -------------
    try:
        # Nombre de la institución
        cursor.execute(
            "SELECT nombre FROM institucion WHERE id_institucion = %s",
            (id_institucion,)
        )
        inst = cursor.fetchone()
        nombre_institucion = inst["nombre"] if inst else "Institución"

        # Sedes de la institución
        cursor.execute(
            """
            SELECT id_sede, nombre_sede
            FROM sede
            WHERE id_institucion = %s
            ORDER BY nombre_sede;
            """,
            (id_institucion,)
        )
        sedes = cursor.fetchall()

        # Todos los grados disponibles
        cursor.execute(
            """
            SELECT id_grado,
                   CONCAT(nivel, ' ', numero_grado) AS nombre_grado
            FROM grado
            ORDER BY nivel, numero_grado;
            """
        )
        grados = cursor.fetchall()

    except Error as e:
        print("ERROR al cargar datos para nueva aula:", e)
        flash("Error al cargar datos para la nueva aula.", "danger")
        sedes = []
        grados = []
        nombre_institucion = "Institución"
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "aulas_form.html",
        id_institucion=id_institucion,
        nombre_institucion=nombre_institucion,
        sedes=sedes,
        grados=grados,
    )


@app.route("/aulas/deshabilitar/<int:id_aula>/<int:id_institucion>")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def deshabilitar_aula(id_aula, id_institucion):
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("aulas_institucion_list", id_institucion=id_institucion))

    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE aula_programa
            SET estado = 1 - estado   -- 1->0, 0->1
            WHERE id_aula = %s;
        """, (id_aula,))
        conn.commit()

        if cursor.rowcount == 0:
            flash("No se encontró el aula a actualizar.", "warning")
        else:
            flash("Estado del aula actualizado correctamente.", "success")
    except Error as e:
        conn.rollback()
        print("ERROR deshabilitar_aula:", e)
        flash("Error al actualizar el estado del aula.", "danger")
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("aulas_institucion_list", id_institucion=id_institucion))




@app.route("/aulas/habilitar/<int:id_aula>/<int:id_institucion>")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def habilitar_aula(id_aula, id_institucion):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE aula_programa SET estado = 'ACTIVA' WHERE id_aula = %s;", (id_aula,))
        conn.commit()
        flash("Aula habilitada exitosamente.", "success")
    except Error as e:
        conn.rollback()
        flash("Error al habilitar el aula.", "danger")
        print("ERROR habilitar:", e)
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for("aulas_institucion_list", id_institucion=id_institucion))








# ============================
# 📅 LISTADO DE SEMANAS DEL PROGRAMA
# ============================
@app.route("/admin/semanas")
@role_required("ADMINISTRADOR")
def admin_semanas_list():
    conn = get_connection()
    semanas = []

    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                id_semana,
                numero_semana,
                fecha_inicio,
                fecha_fin,
                activo,
                observaciones
            FROM semana_programa
            ORDER BY numero_semana;
        """)
        semanas = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template("admin_semanas_list.html", semanas=semanas)



# ============================
# ➕ CREAR NUEVA SEMANA DEL PROGRAMA
# ============================
@app.route("/admin/semanas/nueva", methods=["GET", "POST"])
@role_required("ADMINISTRADOR")
def admin_semanas_new():
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("admin_semanas_list"))

    if request.method == "POST":
        numero_semana = request.form.get("numero_semana")
        fecha_inicio = request.form.get("fecha_inicio")
        fecha_fin = request.form.get("fecha_fin")
        observaciones = request.form.get("observaciones")

        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO semana_programa (numero_semana, fecha_inicio, fecha_fin, observaciones)
                VALUES (%s, %s, %s, %s);
            """, (numero_semana, fecha_inicio, fecha_fin, observaciones))
            conn.commit()
            cursor.close()
            conn.close()
            flash("Semana del programa creada correctamente.", "success")
            return redirect(url_for("admin_semanas_list"))
        except Error as e:
            conn.rollback()
            cursor.close()
            conn.close()
            flash(f"Error al crear la semana: {e}", "danger")
            return redirect(url_for("admin_semanas_list"))

    # GET -> mostrar formulario vacío
    return render_template("admin_semanas_form.html")


@app.route("/admin/tipos-documento")
@role_required("ADMINISTRADOR")
def admin_tiposdoc_list():
    conn = get_connection()
    tipos = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id_tipo_documento, nombre, descripcion
            FROM tipo_documento
            ORDER BY nombre;
        """)
        tipos = cursor.fetchall()
        cursor.close()
        conn.close()
    return render_template("admin_tiposdoc_list.html", tipos=tipos)


@app.route("/admin/tipos-documento/nuevo", methods=["GET", "POST"])
@role_required("ADMINISTRADOR")
def admin_tiposdoc_new():
    if request.method == "POST":
        nombre = request.form.get("nombre")
        descripcion = request.form.get("descripcion")

        if not nombre:
            flash("El nombre del tipo de documento es obligatorio.", "danger")
        else:
            conn = get_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO tipo_documento (nombre, descripcion)
                        VALUES (%s, %s);
                    """, (nombre, descripcion))
                    conn.commit()
                    flash("Tipo de documento creado correctamente.", "success")
                    cursor.close()
                except Error as e:
                    conn.rollback()
                    flash(f"Error al crear tipo de documento: {e}", "danger")
                finally:
                    conn.close()
        return redirect(url_for("admin_tiposdoc_list"))

    return render_template("admin_tiposdoc_form.html")

@app.route("/admin/duraciones-hora")
@role_required("ADMINISTRADOR")
def admin_duraciones_list():
    conn = get_connection()
    duraciones = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id_duracion_hora, minutos, descripcion, activo
            FROM duracion_hora
            ORDER BY minutos;
        """)
        duraciones = cursor.fetchall()
        cursor.close()
        conn.close()
    return render_template("admin_duraciones_list.html", duraciones=duraciones)

@app.route("/instituciones")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def instituciones_list():
    conn = get_connection()
    instituciones = []
    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT id_institucion, nombre, codigo_dane, jornada, activa
            FROM institucion
            ORDER BY nombre;
        """)
        instituciones = cursor.fetchall()
        cursor.close()
        conn.close()
    return render_template("instituciones_list.html", instituciones=instituciones)


@app.route("/admin/duraciones-hora/nueva", methods=["GET", "POST"])
@role_required("ADMINISTRADOR")
def admin_duraciones_new():
    if request.method == "POST":
        minutos = request.form.get("minutos")
        descripcion = request.form.get("descripcion")

        if not minutos:
            flash("Debes indicar los minutos (ej. 40, 45, 50...).", "danger")
        else:
            conn = get_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("""
                        INSERT INTO duracion_hora (minutos, descripcion, activo)
                        VALUES (%s, %s, 1);
                    """, (minutos, descripcion))
                    conn.commit()
                    flash("Duración de hora registrada.", "success")
                    cursor.close()
                except Error as e:
                    conn.rollback()
                    flash(f"Error al crear duración: {e}", "danger")
                finally:
                    conn.close()
        return redirect(url_for("admin_duraciones_list"))

    return render_template("admin_duraciones_form.html")

# ====================================================
# 📌 LISTAR AULAS DE UNA INSTITUCIÓN EN PARTICULAR
# URL: /instituciones/<id_institucion>/aulas
# ====================================================
@app.route("/instituciones/<int:id_institucion>/aulas")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def aulas_por_institucion(id_institucion):
    conn = get_connection()
    aulas = []
    institucion = None

    if conn:
        cursor = conn.cursor(dictionary=True)

        # Obtener info de la institución
        cursor.execute("""
            SELECT id_institucion, nombre 
            FROM institucion
            WHERE id_institucion = %s;
        """, (id_institucion,))
        institucion = cursor.fetchone()

        # Si no existe, mensaje y redirección
        if not institucion:
            cursor.close()
            conn.close()
            flash("La institución seleccionada no existe.", "warning")
            return redirect(url_for("instituciones_list"))

        # Consultar aulas de esa institución
        cursor.execute("""
            SELECT a.id_aula, a.grado, a.programa, a.jornada, a.activa,
                   s.nombre_sede AS sede
            FROM aula a
            INNER JOIN sede s ON a.id_sede = s.id_sede
            WHERE a.id_institucion = %s
            ORDER BY a.grado, a.programa;
        """, (id_institucion,))
        aulas = cursor.fetchall()

        cursor.close()
        conn.close()

    return render_template(
        "aulas_list.html",
        aulas=aulas,
        institucion=institucion,
        filtrado=True
    )


@app.route("/instituciones/<int:id_ied>/deshabilitar", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def institucion_deshabilitar(id_ied):
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("instituciones_list"))

    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id_institucion, nombre, codigo_dane, jornada, activa
        FROM institucion
        WHERE id_institucion = %s;
    """, (id_ied,))
    institucion = cursor.fetchone()

    if not institucion:
        cursor.close()
        conn.close()
        flash("La institución no existe.", "warning")
        return redirect(url_for("instituciones_list"))

    if request.method == "POST":
        motivo = request.form.get("motivo")
        if not motivo:
            flash("Debes indicar un motivo de inhabilitación.", "danger")
            cursor.close()
            conn.close()
            return render_template("institucion_deshabilitar.html", institucion=institucion)

        try:
            cursor2 = conn.cursor()
            cursor2.execute("""
                UPDATE institucion
                SET activa = 0,
                    motivo_inhabilitacion = %s,
                    fecha_inhabilitacion = NOW()
                WHERE id_institucion = %s;
            """, (motivo, id_ied))
            conn.commit()
            cursor2.close()
            flash("Institución inhabilitada correctamente.", "success")
        except Error as e:
            conn.rollback()
            flash(f"Error al inhabilitar institución: {e}", "danger")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("instituciones_list"))

    # GET → mostrar formulario para escribir el motivo
    cursor.close()
    conn.close()
    return render_template("institucion_deshabilitar.html", institucion=institucion)

@app.route("/instituciones/<int:id_ied>/habilitar", methods=["POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def institucion_habilitar(id_ied):
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("instituciones_list"))

    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE institucion
            SET activa = 1,
                motivo_inhabilitacion = NULL,
                fecha_inhabilitacion = NULL
            WHERE id_institucion = %s;
        """, (id_ied,))
        conn.commit()
        cursor.close()
        flash("Institución habilitada nuevamente.", "success")
    except Error as e:
        conn.rollback()
        flash(f"Error al habilitar institución: {e}", "danger")
    finally:
        conn.close()

    return redirect(url_for("instituciones_list"))

# Panel de configuración
@app.route("/admin/config")
@role_required("ADMINISTRADOR")
def admin_config_dashboard():
    return render_template("admin_config_dashboard.html")

@app.route("/admin/roles")
@role_required("ADMINISTRADOR")
def roles_list():
    # TODO: listar roles
    return render_template("roles_list.html")

@app.route("/admin/menus")
@role_required("ADMINISTRADOR")
def menus_list():
    # TODO: gestionar menús por rol si lo implementas
    return render_template("menus_list.html")

# Listado de sedes
@app.route("/sedes")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def sedes_list():
    conn = get_connection()
    sedes = []

    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                s.id_sede,
                s.nombre_sede,
                s.direccion,
                s.es_principal,
                i.nombre AS institucion
            FROM sede s
            INNER JOIN institucion i ON s.id_institucion = i.id_institucion
            ORDER BY i.nombre, s.nombre_sede;
        """)
        sedes = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template("sedes_list.html", sedes=sedes)


# Crear sede
@app.route("/sedes/nueva", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def sedes_new():
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("sedes_list"))

    # ----- POST: guardar sede -----
    if request.method == "POST":
        id_institucion = request.form.get("id_institucion")
        nombre_sede = request.form.get("nombre_sede")
        direccion = request.form.get("direccion")
        es_principal = request.form.get("es_principal")  # "1" o "0"

        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO sede (id_institucion, nombre_sede, direccion, es_principal)
                VALUES (%s, %s, %s, %s);
            """, (id_institucion, nombre_sede, direccion, es_principal))
            conn.commit()
            cursor.close()
            conn.close()
            flash("Sede creada correctamente.", "success")
            return redirect(url_for("sedes_list"))
        except Error as e:
            conn.rollback()
            flash(f"Error al crear la sede: {e}", "danger")
            cursor.close()
            conn.close()
            return redirect(url_for("sedes_list"))

    # ----- GET: mostrar formulario con instituciones -----
    cursor = conn.cursor(dictionary=True)
    # Si tienes un campo 'activa' en institucion puedes filtrar, si no, quita el WHERE
    cursor.execute("""
        SELECT id_institucion, nombre
        FROM institucion
        ORDER BY nombre;
    """)
    instituciones = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("sedes_form.html", instituciones=instituciones)


# ============================
# ✏️ EDITAR SEDE
# ============================
@app.route("/sedes/<int:id_sede>/editar", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def sedes_edit(id_sede):
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("sedes_list"))

    cursor = conn.cursor(dictionary=True)

    # --- Obtener la sede a editar ---
    cursor.execute("""
        SELECT id_sede, id_institucion, nombre_sede, direccion, es_principal
        FROM sede
        WHERE id_sede = %s
    """, (id_sede,))
    sede = cursor.fetchone()

    if not sede:
        cursor.close()
        conn.close()
        flash("La sede seleccionada no existe.", "warning")
        return redirect(url_for("sedes_list"))

    # --- POST: actualizar datos ---
    if request.method == "POST":
        id_institucion = request.form.get("id_institucion")
        nombre_sede = request.form.get("nombre_sede")
        direccion = request.form.get("direccion")
        es_principal = request.form.get("es_principal")

        try:
            cursor.execute("""
                UPDATE sede
                SET id_institucion = %s,
                    nombre_sede = %s,
                    direccion = %s,
                    es_principal = %s
                WHERE id_sede = %s
            """, (id_institucion, nombre_sede, direccion, es_principal, id_sede))
            conn.commit()
            cursor.close()
            conn.close()
            flash("Sede actualizada correctamente.", "success")
            return redirect(url_for("sedes_list"))
        except Error as e:
            conn.rollback()
            cursor.close()
            conn.close()
            flash(f"Error al actualizar la sede: {e}", "danger")
            return redirect(url_for("sedes_list"))

    # --- GET: cargar instituciones y mostrar formulario ---
    cursor.execute("""
        SELECT id_institucion, nombre
        FROM institucion
        ORDER BY nombre;
    """)
    instituciones = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template(
        "sedes_form.html",
        instituciones=instituciones,
        sede=sede,
        edit_mode=True
    )

# ============================
# 🗑️ ELIMINAR SEDE (borrado físico)
# ============================
@app.route("/sedes/<int:id_sede>/eliminar", methods=["POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def sedes_delete(id_sede):
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("sedes_list"))

    try:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sede WHERE id_sede = %s", (id_sede,))
        conn.commit()
        cursor.close()
        conn.close()
        flash("Sede eliminada correctamente.", "success")
    except Error as e:
        conn.rollback()
        cursor.close()
        conn.close()
        flash(f"No se pudo eliminar la sede (puede tener datos asociados): {e}", "danger")

    return redirect(url_for("sedes_list"))

# ============================
# 👨‍🏫 LISTA DE TUTORES
# ============================
@app.route("/tutores")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def tutores_list():
    conn = get_connection()
    tutores = []

    if conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                p.id_persona,
                p.nombres,
                p.apellidos,
                p.email,
                p.telefono,
                p.numero_documento,
                td.nombre AS tipo_documento
            FROM persona p
            LEFT JOIN tipo_documento td 
                ON p.id_tipo_documento = td.id_tipo_documento
            WHERE p.tipo_perfil_contrato = 'TUTOR'
            ORDER BY p.apellidos, p.nombres;
        """)
        tutores = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template("tutores_list.html", tutores=tutores)

# ============================
# ➕ REGISTRAR NUEVO TUTOR
# ============================
@app.route("/tutores/nuevo", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def tutores_new():
    conn = get_connection()
    if not conn:
        flash("Error de conexión con la base de datos.", "danger")
        return redirect(url_for("tutores_list"))

    cursor = conn.cursor(dictionary=True)

    # Cargar tipos de documento para el combo
    cursor.execute("""
        SELECT id_tipo_documento, nombre
        FROM tipo_documento
        ORDER BY nombre;
    """)
    tipos_doc = cursor.fetchall()

    if request.method == "POST":
        id_tipo_documento = request.form.get("id_tipo_documento")
        numero_documento = request.form.get("numero_documento")
        nombres = request.form.get("nombres")
        apellidos = request.form.get("apellidos")
        email = request.form.get("email")
        telefono = request.form.get("telefono")

        try:
            cursor2 = conn.cursor()
            cursor2.execute("""
                INSERT INTO persona (
                    id_tipo_documento,
                    numero_documento,
                    nombres,
                    apellidos,
                    email,
                    telefono,
                    tipo_perfil_contrato
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'TUTOR');
            """, (id_tipo_documento, numero_documento, nombres, apellidos, email, telefono))
            conn.commit()
            cursor2.close()
            cursor.close()
            conn.close()
            flash("Tutor registrado correctamente.", "success")
            return redirect(url_for("tutores_list"))
        except Error as e:
            conn.rollback()
            cursor2.close()
            cursor.close()
            conn.close()
            flash(f"Error al registrar el tutor: {e}", "danger")
            return redirect(url_for("tutores_list"))

    # GET -> mostrar formulario vacío
    cursor.close()
    conn.close()
    return render_template("tutores_form.html", tipos_doc=tipos_doc)

# ============================
# 👨‍🎓 LISTA DE ESTUDIANTES
# ============================
@app.route("/estudiantes")
@login_required
@role_required("ADMINISTRADOR", "ADMINISTRATIVO")
def estudiantes_list():
    conn = get_connection()
    if not conn:
        flash("No se pudo conectar a la base de datos.", "danger")
        return redirect(url_for("index"))

    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT 
                e.id_estudiante,
                td.nombre AS tipo_doc,
                e.numero_documento,
                CONCAT(e.apellidos, ', ', e.nombres) AS nombre_completo,
                g.numero_grado,
                e.fecha_nacimiento,
                e.correo,
                e.telefono,
                i.nombre AS institucion
            FROM estudiante e
            JOIN tipo_documento td ON td.id_tipo_documento = e.id_tipo_documento
            LEFT JOIN grado g       ON g.id_grado = e.id_grado_actual
            LEFT JOIN institucion i ON i.id_institucion = e.id_institucion
            ORDER BY e.apellidos, e.nombres;
        """)
        estudiantes = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template("estudiantes_list.html", estudiantes=estudiantes)

# ============================
# ➕ REGISTRAR NUEVO ESTUDIANTE
# ============================
@app.route("/estudiantes/new", methods=["GET", "POST"])
@login_required
@role_required("ADMINISTRADOR", "ADMINISTRATIVO")
def estudiantes_new():
    conn = get_connection()
    if not conn:
        flash("No se pudo conectar a la base de datos.", "danger")
        return redirect(url_for("estudiantes_list"))

    if request.method == "POST":
        id_tipo_documento = request.form.get("id_tipo_documento")
        numero_documento = request.form.get("numero_documento")
        nombres = request.form.get("nombres")
        apellidos = request.form.get("apellidos")
        correo = request.form.get("correo") or None
        telefono = request.form.get("telefono") or None
        fecha_nacimiento = request.form.get("fecha_nacimiento") or None
        id_institucion = request.form.get("id_institucion")
        id_grado_actual = request.form.get("id_grado")

        cursor = conn.cursor()
        try:
            # ORDEN EXACTO DE TUS COLUMNAS
            cursor.execute("""
                INSERT INTO estudiante (
                    id_tipo_documento,
                    numero_documento,
                    nombres,
                    apellidos,
                    correo,
                    telefono,
                    fecha_nacimiento,
                    id_institucion,
                    id_grado_actual
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                id_tipo_documento,
                numero_documento,
                nombres,
                apellidos,
                correo,
                telefono,
                fecha_nacimiento,
                id_institucion,
                id_grado_actual
            ))
            conn.commit()
            flash("Estudiante registrado correctamente.", "success")
        except Error as e:
            conn.rollback()
            flash(f"Error al guardar el estudiante: {e}", "danger")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("estudiantes_list"))

    # GET: cargar combos
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT id_tipo_documento, nombre
            FROM tipo_documento
            ORDER BY nombre;
        """)
        tipos_doc = cursor.fetchall()

        cursor.execute("""
            SELECT id_institucion, nombre
            FROM institucion
            WHERE activa = 1
            ORDER BY nombre;
        """)
        instituciones = cursor.fetchall()

        cursor.execute("""
            SELECT id_grado, numero_grado
            FROM grado
            WHERE numero_grado IN (4,5,9,10)
            ORDER BY numero_grado;
        """)
        grados = cursor.fetchall()
    finally:
        cursor.close()
        conn.close()

    return render_template(
        "estudiantes_new.html",
        tipos_doc=tipos_doc,
        instituciones=instituciones,
        grados=grados
    )



# ============================
# 📚 PERÍODOS ACADÉMICOS
# ============================

@app.route("/periodos")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def periodos_list():
    conn = get_connection()
    periodos = []

    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT 
                    id_periodo,
                    nombre_periodo,
                    fecha_inicio,
                    fecha_fin,
                    anio
                FROM periodo_academico
                ORDER BY fecha_inicio;
            """)
            periodos = cursor.fetchall()

            # Calculamos si el período está ACTIVO o INACTIVO
            hoy = date.today()
            for p in periodos:
                fi = p["fecha_inicio"]
                ff = p["fecha_fin"]
                # fi y ff vienen como date/datetime desde MySQL
                p["activo"] = (fi <= hoy <= ff)

        except Error as e:
            print("Error al consultar períodos académicos:", e)
        finally:
            cursor.close()
            conn.close()

    return render_template("periodos_list.html", periodos=periodos)


@app.route("/periodos/nuevo", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def periodos_new():
    if request.method == "POST":
        nombre_periodo = request.form.get("nombre_periodo")
        fecha_inicio = request.form.get("fecha_inicio")
        fecha_fin = request.form.get("fecha_fin")

        # 🗓️ Sacar automáticamente el año a partir de la fecha de inicio
        anio = datetime.strptime(fecha_inicio, "%Y-%m-%d").year

        conn = get_connection()
        if not conn:
            flash("Error de conexión con la base de datos.", "danger")
            return redirect(url_for("periodos_list"))

        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO periodo_academico (
                    nombre_periodo,
                    fecha_inicio,
                    fecha_fin,
                    anio
                )
                VALUES (%s, %s, %s, %s);
            """, (nombre_periodo, fecha_inicio, fecha_fin, anio))
            conn.commit()
            flash("Período académico creado correctamente.", "success")
        except Error as e:
            conn.rollback()
            flash(f"Error al crear el período académico: {e}", "danger")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("periodos_list"))

    # GET → mostrar formulario
    return render_template("periodos_form.html")


# ============================
# 🎯 COMPONENTES DE NOTA
# ============================

# ============================
# 🎯 COMPONENTES DE NOTA
# ============================

# ============================
# 🎯 COMPONENTES DE NOTA
# ============================

@app.route("/componentes")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def componentes_list():
    conn = get_connection()
    componentes = []

    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT 
                    c.id_componente,
                    c.id_tipo_programa,
                    tp.nombre AS programa,
                    c.nombre_componente,
                    c.porcentaje
                FROM componente_nota c
                JOIN tipo_programa tp
                    ON c.id_tipo_programa = tp.id_tipo_programa
                ORDER BY tp.nombre, c.nombre_componente;
            """)
            componentes = cursor.fetchall()
        except Error as e:
            print("Error al consultar componentes de nota:", e)
        finally:
            cursor.close()
            conn.close()

    return render_template("componentes_list.html", componentes=componentes)


@app.route("/componentes/nuevo", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def componentes_new():
    if request.method == "POST":
        nombre_componente = request.form.get("nombre_componente")
        id_tipo_programa = request.form.get("id_tipo_programa")
        porcentaje = request.form.get("porcentaje")

        conn = get_connection()
        if not conn:
            flash("Error de conexión con la base de datos.", "danger")
            return redirect(url_for("componentes_list"))

        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO componente_nota (
                    id_tipo_programa,
                    nombre_componente,
                    porcentaje
                )
                VALUES (%s, %s, %s);
            """, (id_tipo_programa, nombre_componente, porcentaje))
            conn.commit()
            flash("Componente de nota creado correctamente.", "success")
        except Error as e:
            conn.rollback()
            flash(f"Error al crear el componente de nota: {e}", "danger")
        finally:
            cursor.close()
            conn.close()

        return redirect(url_for("componentes_list"))

    # GET → cargar los programas para el select
    programas = []
    conn = get_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT id_tipo_programa, nombre
                FROM tipo_programa
                ORDER BY id_tipo_programa;
            """)
            programas = cursor.fetchall()
        except Error as e:
            print("Error al consultar tipos de programa:", e)
        finally:
            cursor.close()
            conn.close()

    return render_template("componentes_form.html", programas=programas)



# ============================
# 📘 MÓDULO DE REGISTRO DE NOTAS
# ============================

@app.route("/notas")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR", "TUTOR")
def notas_registro():
    """
    Página inicial del sistema de notas.
    Desde aquí se seleccionará aula, período y componente para proceder a registrar.
    """
    conn = get_connection()
    aulas = []
    periodos = []
    componentes = []

    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            # Obtener aulas activas
            cursor.execute("""
                SELECT id_aula, nombre_aula 
                FROM aula_programa
                WHERE activa = 1
                ORDER BY nombre_aula;
            """)
            aulas = cursor.fetchall()

            # Obtener periodos activos
            cursor.execute("""
                SELECT id_periodo, nombre_periodo
                FROM periodo_academico
                WHERE activo = 1
                ORDER BY id_periodo;
            """)
            periodos = cursor.fetchall()

            # Obtener componentes
            cursor.execute("""
                SELECT id_componente, nombre_componente, programa
                FROM componente_nota
                WHERE activo = 1
                ORDER BY programa, nombre_componente;
            """)
            componentes = cursor.fetchall()

        except Error as e:
            print("Error cargando datos del registro de notas:", e)
        finally:
            cursor.close()
            conn.close()

    return render_template(
        "notas_menu.html",
        aulas=aulas,
        periodos=periodos,
        componentes=componentes
    )

@app.route("/asistencia/mis-clases")
@role_required("TUTOR", "ADMINISTRATIVO", "ADMINISTRADOR")
def asistencia_mis_clases():
    """
    Vista donde el TUTOR ve sus aulas asignadas y los horarios.
    """

    aulas = []

    conn = get_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT 
                    a.id_aula,
                    a.nombre_aula,
                    i.nombre_institucion AS institucion,
                    s.nombre_sede AS sede,
                    h.dia_semana,
                    h.hora_inicio,
                    h.hora_fin
                FROM tutor_aula_horario tah
                JOIN aula_programa a ON tah.id_aula = a.id_aula
                JOIN institucion i   ON a.id_institucion = i.id_institucion
                JOIN sede s          ON a.id_sede = s.id_sede
                JOIN horario_aula h  ON tah.id_horario = h.id_horario
                WHERE tah.id_tutor = %s
                  AND tah.estado = 'ACTIVO'
                ORDER BY 
                    i.nombre_institucion,
                    s.nombre_sede,
                    a.nombre_aula,
                    h.dia_semana,
                    h.hora_inicio;
                """,
                (session["user_id"],)
            )
            aulas = cursor.fetchall()
        except Error as e:
            print("Error cargando aulas del tutor:", e)
        finally:
            cursor.close()
            conn.close()

    return render_template("asistencia_mis_clases.html", aulas=aulas)

@app.route("/asistencia/tomar", methods=["GET", "POST"])
@role_required("TUTOR", "ADMINISTRATIVO", "ADMINISTRADOR")
def asistencia_tomar():
    """
    Pantalla para tomar asistencia por clase.
    De momento es una versión básica solo para que el endpoint exista
    y el menú funcione sin error. Más adelante se conecta a la BD.
    """
    if request.method == "POST":
        # Más adelante aquí procesas los datos del formulario
        # (aula, fecha, lista de estudiantes, presentes/ausentes, etc.)
        flash("La funcionalidad de registro de asistencia aún está en construcción.", "info")
        return redirect(url_for("asistencia_tomar"))

    # Por ahora no cargamos nada de la BD
    return render_template("asistencia_tomar.html")

@app.route("/asistencia/reposiciones", methods=["GET", "POST"])
@role_required("TUTOR", "ADMINISTRATIVO", "ADMINISTRADOR")
def asistencia_reposiciones():
    """
    Pantalla para gestionar reposiciones de clase.
    Versión básica solo para que el endpoint exista.
    Luego se conectará a la BD con las clases no dictadas, etc.
    """
    if request.method == "POST":
        # Aquí en el futuro procesarás la reposición seleccionada
        # (clase no dictada, nueva fecha, nuevo horario, etc.)
        flash("La funcionalidad de registro de reposiciones aún está en construcción.", "info")
        return redirect(url_for("asistencia_reposiciones"))

    return render_template("asistencia_reposiciones.html")

@app.route("/festivos", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def festivos_list():
    conn = get_connection()
    if not conn:
        return "Error de conexión con la base de datos", 500

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        fecha = request.form.get("fecha")
        descripcion = request.form.get("descripcion")

        if fecha and descripcion:
            cursor.execute(
                """
                INSERT INTO festivo (fecha, descripcion)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE descripcion = VALUES(descripcion)
                """,
                (fecha, descripcion),
            )
            conn.commit()

        cursor.close()
        conn.close()
        return redirect(url_for("festivos_list"))

    cursor.execute("SELECT id_festivo, fecha, descripcion FROM festivo ORDER BY fecha;")
    festivos = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("festivos_list.html", festivos=festivos)

@app.route("/motivos-inasistencia", methods=["GET", "POST"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def motivos_inasistencia_list():
    conn = get_connection()
    if not conn:
        return "Error de conexión con la base de datos", 500

    cursor = conn.cursor(dictionary=True)

    if request.method == "POST":
        nombre = request.form.get("nombre_motivo")
        descripcion = request.form.get("descripcion")
        activo = 1 if request.form.get("activo") == "1" else 0

        if nombre:
            cursor.execute(
                """
                INSERT INTO motivo_inasistencia (nombre_motivo, descripcion, activo)
                VALUES (%s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    descripcion = VALUES(descripcion),
                    activo = VALUES(activo)
                """,
                (nombre, descripcion, activo),
            )
            conn.commit()

        cursor.close()
        conn.close()
        return redirect(url_for("motivos_inasistencia_list"))

    cursor.execute("SELECT id_motivo, nombre_motivo, descripcion, activo FROM motivo_inasistencia ORDER BY nombre_motivo;")
    motivos = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("motivos_inasistencia_list.html", motivos=motivos)

@app.route("/reportes/asistencia-aula")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def reporte_asistencia_aula():
    registros = []
    conn = get_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)

        f_institucion = request.args.get("f_institucion", "").strip()
        f_sede = request.args.get("f_sede", "").strip()
        f_aula = request.args.get("f_aula", "").strip()
        f_semana_ini = request.args.get("f_semana_ini", "").strip()
        f_semana_fin = request.args.get("f_semana_fin", "").strip()

        query = """
            SELECT
                sp.numero_semana AS semana,
                ac.fecha_clase,
                i.nombre_institucion AS institucion,
                s.nombre_sede AS sede,
                a.nombre_aula AS aula,
                ac.es_festivo,
                ac.se_dicto,
                ac.horas_dictadas,
                ac.horas_no_dictadas,
                m.nombre_motivo AS motivo,
                ac.fecha_reposicion,
                CONCAT(pt.nombres, ' ', pt.apellidos) AS tutor
            FROM asistencia_clase ac
            JOIN aula_programa a ON ac.id_aula = a.id_aula
            JOIN institucion i ON a.id_institucion = i.id_institucion
            LEFT JOIN sede s ON a.id_sede = s.id_sede
            LEFT JOIN semana_programa sp ON ac.id_semana = sp.id_semana
            LEFT JOIN motivo_inasistencia m ON ac.id_motivo_no_dictada = m.id_motivo
            LEFT JOIN persona pt ON ac.id_tutor = pt.id_persona
            WHERE 1 = 1
        """

        params = []

        if f_institucion:
            query += " AND i.nombre_institucion LIKE %s"
            params.append(f"%{f_institucion}%")

        if f_sede:
            query += " AND s.nombre_sede LIKE %s"
            params.append(f"%{f_sede}%")

        if f_aula:
            query += " AND a.nombre_aula LIKE %s"
            params.append(f"%{f_aula}%")

        if f_semana_ini and f_semana_fin:
            query += " AND sp.numero_semana BETWEEN %s AND %s"
            params.append(f_semana_ini)
            params.append(f_semana_fin)
        elif f_semana_ini:
            query += " AND sp.numero_semana >= %s"
            params.append(f_semana_ini)
        elif f_semana_fin:
            query += " AND sp.numero_semana <= %s"
            params.append(f_semana_fin)

        query += """
            ORDER BY sp.numero_semana, ac.fecha_clase, i.nombre_institucion, s.nombre_sede, a.nombre_aula
        """

        cursor.execute(query, params)
        registros = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template(
        "reporte_asistencia_aula.html",
        registros=registros
    )


@app.route("/reportes/asistencia-estudiante")
@role_required("ADMINISTRATIVO", "ADMINISTRADOR", "TUTOR")
def reporte_asistencia_estudiante():
    registros = []
    conn = get_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)

        f_documento = request.args.get("f_documento", "").strip()
        f_nombre = request.args.get("f_nombre", "").strip()
        f_institucion = request.args.get("f_institucion", "").strip()
        f_grado = request.args.get("f_grado", "").strip()
        f_programa = request.args.get("f_programa", "").strip()
        f_semana_ini = request.args.get("f_semana_ini", "").strip()
        f_semana_fin = request.args.get("f_semana_fin", "").strip()

        query = """
            SELECT
                sp.numero_semana AS semana,
                ac.fecha_clase,
                CONCAT(e.nombres, ' ', e.apellidos) AS estudiante,
                e.numero_documento AS documento,
                i.nombre_institucion AS institucion,
                s.nombre_sede AS sede,
                a.nombre_aula AS aula,
                a.programa,
                ad.estado_asistencia,
                ad.justificacion AS motivo_inasistencia,
                ac.fecha_reposicion,
                CONCAT(pt.nombres, ' ', pt.apellidos) AS tutor
            FROM asistencia_detalle ad
            JOIN asistencia_clase ac ON ad.id_clase = ac.id_clase
            JOIN aula_programa a ON ac.id_aula = a.id_aula
            JOIN institucion i ON a.id_institucion = i.id_institucion
            LEFT JOIN sede s ON a.id_sede = s.id_sede
            JOIN estudiante e ON ad.id_estudiante = e.id_estudiante
            LEFT JOIN semana_programa sp ON ac.id_semana = sp.id_semana
            LEFT JOIN persona pt ON ac.id_tutor = pt.id_persona
            WHERE 1 = 1
        """

        params = []

        if f_documento:
            query += " AND e.numero_documento = %s"
            params.append(f_documento)

        if f_nombre:
            query += " AND CONCAT(e.nombres, ' ', e.apellidos) LIKE %s"
            params.append(f"%{f_nombre}%")

        if f_institucion:
            query += " AND i.nombre_institucion LIKE %s"
            params.append(f"%{f_institucion}%")

        if f_grado:
            query += " AND e.grado = %s"
            params.append(f_grado)

        if f_programa:
            query += " AND a.programa = %s"
            params.append(f_programa)

        if f_semana_ini and f_semana_fin:
            query += " AND sp.numero_semana BETWEEN %s AND %s"
            params.append(f_semana_ini)
            params.append(f_semana_fin)
        elif f_semana_ini:
            query += " AND sp.numero_semana >= %s"
            params.append(f_semana_ini)
        elif f_semana_fin:
            query += " AND sp.numero_semana <= %s"
            params.append(f_semana_fin)

        query += """
            ORDER BY sp.numero_semana, ac.fecha_clase, estudiante
        """

        cursor.execute(query, params)
        registros = cursor.fetchall()
        cursor.close()
        conn.close()

    return render_template(
        "reporte_asistencia_estudiante.html",
        registros=registros
    )

from flask import request

@app.route("/reportes/boletin", methods=["GET"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR", "TUTOR")
def reporte_boletin():
    boletines = []
    conn = get_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)

        f_documento = request.args.get("f_documento", "").strip()
        f_periodo = request.args.get("f_periodo", "").strip()
        f_institucion = request.args.get("f_institucion", "").strip()
        f_grado = request.args.get("f_grado", "").strip()

        query = """
            SELECT
                e.id_estudiante,
                e.numero_documento,
                CONCAT(e.nombres, ' ', e.apellidos) AS estudiante,
                i.nombre_institucion,
                a.nombre_aula,
                e.grado,
                per.nombre_periodo,
                asig.nombre_asignatura,
                n.nota_final
            FROM nota n
            JOIN estudiante e ON n.id_estudiante = e.id_estudiante
            JOIN aula_programa a ON n.id_aula = a.id_aula
            JOIN institucion i ON a.id_institucion = i.id_institucion
            JOIN periodo per ON n.id_periodo = per.id_periodo
            JOIN asignatura asig ON n.id_asignatura = asig.id_asignatura
            WHERE 1 = 1
        """

        params = []

        if f_documento:
            query += " AND e.numero_documento = %s"
            params.append(f_documento)

        if f_periodo:
            query += " AND per.id_periodo = %s"
            params.append(f_periodo)

        if f_institucion:
            query += " AND i.nombre_institucion LIKE %s"
            params.append(f"%{f_institucion}%")

        if f_grado:
            query += " AND e.grado = %s"
            params.append(f_grado)

        query += """
            ORDER BY e.apellidos, e.nombres, asig.nombre_asignatura
        """

        try:
            cursor.execute(query, params)
            boletines = cursor.fetchall()
        except Error as e:
            print("Error cargando boletín:", e)
        finally:
            cursor.close()
            conn.close()

    return render_template(
        "reporte_boletin.html",
        boletines=boletines
    )

@app.route("/reportes/comparativo-programa", methods=["GET"])
@role_required("ADMINISTRATIVO", "ADMINISTRADOR")
def reporte_comparativo_programa():
    comparativos = []
    conn = get_connection()
    if conn:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute("""
                SELECT 
                    a.id_aula,
                    a.nombre_aula,
                    i.nombre_institucion,
                    COUNT(DISTINCT e.id_estudiante) AS total_estudiantes
                FROM aula_programa a
                LEFT JOIN institucion i ON a.id_institucion = i.id_institucion
                LEFT JOIN matricula m ON m.id_aula = a.id_aula
                LEFT JOIN estudiante e ON e.id_estudiante = m.id_estudiante
                GROUP BY a.id_aula, a.nombre_aula, i.nombre_institucion
                ORDER BY i.nombre_institucion, a.nombre_aula;
            """)
            comparativos = cursor.fetchall()
        except Error as e:
            print("Error cargando comparativo de programa:", e)
        finally:
            cursor.close()
            conn.close()

    return render_template(
        "reporte_comparativo_programa.html",
        comparativos=comparativos
    )




if __name__ == "__main__":
    app.run(debug=True)
