"""La cola de correos: qué se difiere, qué no, y qué pasa cuando se llena.

El problema que arregla está medido: cada aviso cuesta ~2,5 s de SMTP dentro del
request, y guardar el precio de una prenda con 20 favoritos tardaba casi un
minuto porque los mandaba en serie. Lo que estas pruebas fijan no es la
velocidad en sí, sino las tres cosas que no se pueden romper al ganarla: que en
línea todo siga igual que antes, que no se pierda ningún aviso, y que la
bitácora siga trayendo IP, user-agent y request_id.
"""
import re
import threading
import time
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from src.main import app  # noqa: F401 - registra todos los modelos mapeados
from src.auth.infrastructure.persistence.models.user import UserModel
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.config.settings import settings
from src.infrastructure.database.base import Base
from src.notificaciones.application.use_cases import send_email as send_email_modulo
from src.notificaciones.application.use_cases.send_email import EnviarCorreo
from src.notificaciones.domain.diseno import Mensaje
from src.notificaciones.infrastructure.email import cola as cola_modulo
from src.notificaciones.infrastructure.email.cola import ColaDeCorreos
from src.usuarios_catalogo.infrastructure.models.catalog import CategoryModel, ProductModel
from src.ventas_pagos.application import favorite_alerts as favoritos_modulo
from src.ventas_pagos.application.favorite_alerts import FavoriteAlerts
from src.ventas_pagos.infrastructure.engagement_models import FavoriteModel
from src.shared.context.audit_context import reset_audit_context, set_audit_actor, set_audit_context


AVISO = Mensaje(asunto="Aviso de prueba", texto="cuerpo", html="<p>cuerpo</p>")


class RemitenteEspia:
    """Guarda lo enviado y, sobre todo, DESDE QUÉ HILO salió.

    El hilo es el dato que distingue un envío diferido de uno en línea, y es lo
    único que prueba de verdad que el request no esperó al SMTP.
    """

    def __init__(self, demora: float = 0.0) -> None:
        self.demora = demora
        self.enviados: list[dict] = []
        self._candado = threading.Lock()

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        if self.demora:
            time.sleep(self.demora)
        with self._candado:
            self.enviados.append({"to": to, "subject": subject, "hilo": threading.current_thread().name})
        return True

    @property
    def hilos(self) -> set[str]:
        return {envio["hilo"] for envio in self.enviados}


@pytest.fixture
def base(tmp_path):
    """SQLite en ARCHIVO, no en memoria.

    Con `:memory:` cada conexión abre su propia base, así que el hilo de la cola
    no vería nada de lo que escribe el request; y compartirla con StaticPool
    obligaría a los dos hilos a pelearse una sola conexión. Un archivo temporal
    da lo mismo que produce el runtime real: sesiones independientes contra la
    misma base.
    """
    engine = create_engine(f"sqlite:///{(tmp_path / 'prueba.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as db:
        yield engine, db
    engine.dispose()


def usuario(db, sufijo: int = 0) -> UserModel:
    fila = UserModel(email=f"cliente{sufijo}@fashionstore.test", password_hash="unused",
                     first_name="Cliente", last_name=str(sufijo))
    db.add(fila)
    db.flush()
    return fila


def prenda(db, precio: str = "100.00") -> ProductModel:
    categoria = CategoryModel(name="Camisas", slug="camisas")
    db.add(categoria)
    db.flush()
    fila = ProductModel(name="Camisa lino", slug="camisa-lino", description="Fresca",
                        base_price=Decimal(precio), category_id=categoria.id)
    db.add(fila)
    db.flush()
    return fila


def cola_de_prueba(monkeypatch, engine, **ajustes) -> ColaDeCorreos:
    """Enciende el modo fondo con una cola propia y una base propia.

    La cola compartida del proceso abriría sus Session con `SessionLocal`, es
    decir contra `DATABASE_URL`: una prueba jamás debe escribir ahí.
    """
    cola = ColaDeCorreos(abrir_sesion=lambda: Session(engine, expire_on_commit=False), **ajustes)
    monkeypatch.setattr(settings, "email_background", True)
    monkeypatch.setattr(send_email_modulo, "cola_de_correos", lambda: cola)
    return cola


# --- Modo en línea: nada cambió ------------------------------------------

def test_en_linea_todo_se_resuelve_antes_de_devolver(base):
    """Con `email_background=False` el booleano y la bitácora siguen siendo los de antes."""
    _engine, db = base
    remitente = RemitenteEspia()
    correo = EnviarCorreo(db, remitente)

    assert correo.execute(destinatario="ana@fashionstore.test", mensaje=AVISO,
                          entidad="order", entidad_id="123") is True
    assert remitente.enviados[-1]["to"] == "ana@fashionstore.test"
    assert remitente.hilos == {threading.current_thread().name}
    evento = db.scalars(select(AuditEventModel)).all()[-1]
    assert evento.action == "notificaciones.email_enviado"
    assert evento.metadata_["sent"] is True


def test_sin_destinatario_devuelve_falso_tambien_en_modo_fondo(base, monkeypatch):
    """El corto-circuito se evalúa antes de encolar: si no, el False se volvería True."""
    engine, db = base
    cola = cola_de_prueba(monkeypatch, engine)
    assert EnviarCorreo(db, RemitenteEspia()).execute(
        destinatario=None, mensaje=AVISO, entidad="order") is False
    assert cola.esperar(1.0)
    assert db.scalars(select(AuditEventModel)).all() == []


# --- Modo fondo: el request no espera al SMTP ----------------------------

def test_el_request_no_espera_al_correo(base, monkeypatch):
    engine, db = base
    remitente = RemitenteEspia(demora=0.4)
    cola = cola_de_prueba(monkeypatch, engine)

    inicio = time.monotonic()
    aceptado = EnviarCorreo(db, remitente).execute(
        destinatario="ana@fashionstore.test", mensaje=AVISO, entidad="order", entidad_id="123")
    encolar = time.monotonic() - inicio

    assert aceptado is True
    assert encolar < 0.1, "encolar tiene que ser inmediato, no esperar los 0,4 s del envío"
    assert remitente.enviados == [], "el correo todavía no salió cuando el request siguió"
    assert cola.esperar(5.0)
    assert len(remitente.enviados) == 1
    assert remitente.hilos == {"correo-1"}, "el SMTP tiene que ocurrir fuera del hilo del request"


def test_la_bitacora_del_hilo_conserva_ip_agente_y_request_id(base, monkeypatch):
    """Sin esto, los eventos de correo aparecerían sin IP en GET /audit-log."""
    engine, db = base
    actor = usuario(db)
    db.commit()
    cola = cola_de_prueba(monkeypatch, engine)

    token = set_audit_context("10.0.0.7", "navegador-de-prueba", "peticion-42")
    try:
        set_audit_actor(actor.id)
        # `actor_id=None` a propósito: es el caso de la venta de caja sin cliente
        # registrado, donde hoy salva el contextvar.
        EnviarCorreo(db, RemitenteEspia()).execute(
            destinatario="ana@fashionstore.test", mensaje=AVISO, entidad="order", entidad_id="123")
    finally:
        reset_audit_context(token)
    assert cola.esperar(5.0)

    with Session(engine) as revision:
        evento = revision.scalars(select(AuditEventModel)).all()[-1]
        assert evento.ip_address == "10.0.0.7"
        assert evento.user_agent == "navegador-de-prueba"
        assert evento.metadata_["request_id"] == "peticion-42"
        assert evento.actor_user_id == actor.id


def test_el_hilo_no_usa_la_session_del_request(base, monkeypatch):
    """La Session del request ya está cerrada cuando el hilo corre: el evento
    tiene que aparecer igual, escrito por la Session del propio hilo."""
    engine, db = base
    cola = cola_de_prueba(monkeypatch, engine)
    EnviarCorreo(db, RemitenteEspia()).execute(
        destinatario="ana@fashionstore.test", mensaje=AVISO, entidad="order", entidad_id="123")
    db.close()  # es lo que hace `get_db` en su `finally`, antes de que el hilo termine
    assert cola.esperar(5.0)

    with Session(engine) as revision:
        assert revision.scalars(select(AuditEventModel)).all()[-1].entity_id == "123"


# --- Cola llena: no se pierde ningún aviso -------------------------------

def test_con_la_cola_llena_el_aviso_sale_en_linea(base, monkeypatch):
    engine, db = base
    principal = threading.current_thread()
    puerta = threading.Event()
    arranco = threading.Event()

    class RemitenteConPuerta(RemitenteEspia):
        def send(self, **datos):
            if threading.current_thread() is not principal:
                # Solo el trabajador queda retenido: así la cola se llena de
                # verdad y la prueba nunca se bloquea a sí misma.
                arranco.set()
                puerta.wait(timeout=10)
            return super().send(**datos)

    remitente = RemitenteConPuerta()
    cola = cola_de_prueba(monkeypatch, engine, tamano=1, trabajadores=1)
    monkeypatch.setattr(cola_modulo, "ESPERA_PARA_ENCOLAR", 0.05)
    correo = EnviarCorreo(db, remitente)

    correo.execute(destinatario="uno@fashionstore.test", mensaje=AVISO, entidad="order")
    assert arranco.wait(5.0), "el trabajador tiene que estar ocupado para que la cola se llene"
    correo.execute(destinatario="dos@fashionstore.test", mensaje=AVISO, entidad="order")
    desbordado = correo.execute(destinatario="tres@fashionstore.test", mensaje=AVISO, entidad="order")

    assert desbordado is True
    assert [envio["to"] for envio in remitente.enviados] == ["tres@fashionstore.test"], \
        "el tercero no se descarta: se manda en línea, como antes de existir la cola"
    assert remitente.enviados[0]["hilo"] == principal.name
    # Y el que salió en línea deja su evento en la Session del request, igual que antes.
    assert db.scalars(select(AuditEventModel)).all()[-1].metadata_["to"] == "tres@fashionstore.test"

    puerta.set()
    assert cola.esperar(10.0)
    assert sorted(envio["to"] for envio in remitente.enviados) == [
        "dos@fashionstore.test", "tres@fashionstore.test", "uno@fashionstore.test"]


def test_el_apagado_drena_lo_que_quedaba_encolado(base, monkeypatch):
    """Railway manda SIGTERM en cada despliegue: los hilos son demonio y lo
    encolado se perdería si el cierre no esperara."""
    engine, db = base
    remitente = RemitenteEspia(demora=0.05)
    cola = cola_de_prueba(monkeypatch, engine, trabajadores=1)
    correo = EnviarCorreo(db, remitente)
    for indice in range(5):
        correo.execute(destinatario=f"cliente{indice}@fashionstore.test", mensaje=AVISO, entidad="order")

    cola.apagar(espera=10.0)
    assert len(remitente.enviados) == 5
    assert threading.current_thread().name not in remitente.hilos
    # Tras el apagado nada se encola: el aviso nuevo sale en línea, no al vacío.
    assert correo.execute(destinatario="tarde@fashionstore.test", mensaje=AVISO, entidad="order") is True
    assert remitente.enviados[-1]["hilo"] == threading.current_thread().name


def test_si_el_apagado_no_alcanza_los_avisos_salen_ahi_mismo(base, monkeypatch):
    """El margen de drenaje es corto para no agotar el período de gracia del
    reinicio: lo que quedó sin tomar se envía en el propio cierre."""
    engine, db = base
    principal = threading.current_thread()
    puerta = threading.Event()
    arranco = threading.Event()

    class RemitenteConPuerta(RemitenteEspia):
        def send(self, **datos):
            if threading.current_thread() is not principal:
                arranco.set()
                puerta.wait(timeout=10)
            return super().send(**datos)

    remitente = RemitenteConPuerta()
    cola = cola_de_prueba(monkeypatch, engine, trabajadores=1)
    correo = EnviarCorreo(db, remitente)
    for indice in range(3):
        correo.execute(destinatario=f"cliente{indice}@fashionstore.test", mensaje=AVISO, entidad="order")
    assert arranco.wait(5.0)

    cola.apagar(espera=0.05)
    # El trabajador sigue trabado, pero los dos que esperaban en la cola ya
    # salieron, y salieron desde el hilo que apagó.
    assert len(remitente.enviados) == 2
    assert remitente.hilos == {principal.name}
    puerta.set()


# --- Favoritos -----------------------------------------------------------

def favoritos(db, producto, cantidad: int, precio: str = "150.00") -> list[FavoriteModel]:
    filas = []
    for indice in range(cantidad):
        cliente = usuario(db, indice)
        fila = FavoriteModel(user_id=cliente.id, product_id=producto.id, observed_price=Decimal(precio))
        db.add(fila)
        filas.append(fila)
    db.commit()
    return filas


def test_bajar_el_precio_con_muchos_favoritos_responde_rapido(base, monkeypatch):
    """El caso que motivó todo: 20 favoritos costaban ~50 s de correos en serie."""
    engine, db = base
    producto = prenda(db, "100.00")
    favoritos(db, producto, 20)
    remitente = RemitenteEspia(demora=0.03)
    monkeypatch.setattr(favoritos_modulo, "EnviarCorreo",
                        lambda db_, sender=None: EnviarCorreo(db_, remitente))
    cola = cola_de_prueba(monkeypatch, engine, trabajadores=2)

    inicio = time.monotonic()
    FavoriteAlerts(db).price_dropped(producto, Decimal("150.00"))
    tardanza = time.monotonic() - inicio

    assert tardanza < 0.25, f"guardar el precio tardó {tardanza:.2f} s: el SMTP volvió al request"
    assert cola.esperar(15.0)
    assert len(remitente.enviados) == 20
    assert threading.current_thread().name not in remitente.hilos
    # La marca de cada fila se guarda igual, con el commit del propio lote.
    with Session(engine) as revision:
        assert all(fila.observed_price == Decimal("100.00")
                   for fila in revision.scalars(select(FavoriteModel)))


def test_avisar_a_mas_gente_no_cuesta_mas_consultas(base, monkeypatch):
    """Antes el bucle pedía el usuario fila por fila: N+1 contra Supabase.

    Se compara el MISMO caso con 3 y con 12 favoritos en vez de fijar un número
    de consultas: lo que importa es que el costo no crezca con la cantidad de
    destinatarios, sin atarse a cuántas consultas gasta el `selectin` de roles.
    """
    engine, db = base
    monkeypatch.setattr(favoritos_modulo, "EnviarCorreo",
                        lambda db_, sender=None: EnviarCorreo(db_, RemitenteEspia()))

    def consultas_a_usuarios(cantidad: int, etiqueta: str) -> int:
        categoria = db.scalars(select(CategoryModel)).first()
        if categoria is None:
            categoria = CategoryModel(name="Camisas", slug="camisas")
            db.add(categoria)
            db.flush()
        producto = ProductModel(name=f"Camisa {etiqueta}", slug=f"camisa-{etiqueta}",
                                description="Fresca", base_price=Decimal("100.00"),
                                category_id=categoria.id)
        db.add(producto)
        db.flush()
        for indice in range(cantidad):
            cliente = UserModel(email=f"{etiqueta}{indice}@fashionstore.test", password_hash="unused",
                                first_name="Cliente", last_name=str(indice))
            db.add(cliente)
            db.flush()
            db.add(FavoriteModel(user_id=cliente.id, product_id=producto.id,
                                 observed_price=Decimal("150.00")))
        db.commit()

        vistas: list[str] = []

        @event.listens_for(engine, "before_cursor_execute")
        def registrar(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
            vistas.append(" ".join(statement.lower().split()))

        try:
            FavoriteAlerts(db).price_dropped(producto, Decimal("150.00"))
        finally:
            event.remove(engine, "before_cursor_execute", registrar)
        return len([texto for texto in vistas if re.search(r"\bfrom users\b", texto)])

    pocas = consultas_a_usuarios(3, "chico")
    muchas = consultas_a_usuarios(12, "grande")
    assert pocas == muchas, f"con 12 favoritos se consultó usuarios {muchas} veces y con 3, {pocas}"


def test_el_recorte_de_destinatarios_queda_en_bitacora(base, monkeypatch):
    """Un recorte silencioso sería peor que el problema que evita."""
    engine, db = base
    producto = prenda(db, "100.00")
    favoritos(db, producto, 5)
    remitente = RemitenteEspia()
    monkeypatch.setattr(favoritos_modulo, "EnviarCorreo",
                        lambda db_, sender=None: EnviarCorreo(db_, remitente))
    monkeypatch.setattr(favoritos_modulo, "TOPE_DESTINATARIOS", 3)

    FavoriteAlerts(db).price_dropped(producto, Decimal("150.00"))

    assert len(remitente.enviados) == 3
    recorte = db.scalars(select(AuditEventModel).where(
        AuditEventModel.action == "notificaciones.favoritos_recortados")).all()
    assert len(recorte) == 1
    assert recorte[0].metadata_ == {"total": 5, "avisados": 3, "sin_aviso": 2}
    # A quien no se avisó no se le toca el precio observado: sigue siendo
    # candidato para la próxima rebaja en vez de quedar marcado como avisado.
    sin_aviso = [fila for fila in db.scalars(select(FavoriteModel))
                 if fila.observed_price == Decimal("150.00")]
    assert len(sin_aviso) == 2


def test_un_favorito_de_usuario_inactivo_no_recibe_correo_pero_si_se_marca(base, monkeypatch):
    """Comportamiento de siempre: la marca se pone igual, para no reintentar en
    cada rebaja a una cuenta dada de baja."""
    engine, db = base
    producto = prenda(db, "100.00")
    filas = favoritos(db, producto, 2)
    inactivo = db.get(UserModel, filas[0].user_id)
    inactivo.is_active = False
    db.commit()
    remitente = RemitenteEspia()
    monkeypatch.setattr(favoritos_modulo, "EnviarCorreo",
                        lambda db_, sender=None: EnviarCorreo(db_, remitente))

    FavoriteAlerts(db).price_dropped(producto, Decimal("150.00"))

    assert len(remitente.enviados) == 1
    assert all(fila.observed_price == Decimal("100.00") for fila in db.scalars(select(FavoriteModel)))


def test_una_reposicion_avisa_una_sola_vez_por_favorito(base, monkeypatch):
    engine, db = base
    producto = prenda(db, "100.00")
    favoritos(db, producto, 3)
    remitente = RemitenteEspia()
    monkeypatch.setattr(favoritos_modulo, "EnviarCorreo",
                        lambda db_, sender=None: EnviarCorreo(db_, remitente))

    alertas = FavoriteAlerts(db)
    alertas.restocked(producto, previous=0, current=4)
    assert len(remitente.enviados) == 3
    assert all(fila.last_stock_alert_at is not None for fila in db.scalars(select(FavoriteModel)))
    # Si nunca se agotó no hay nada que anunciar.
    alertas.restocked(producto, previous=2, current=6)
    assert len(remitente.enviados) == 3
