"""Los tres avisos de cuenta tampoco esperan al SMTP dentro del request.

Verificar correo, recuperar contrasena y reenviar verificacion eran los unicos
envios que no pasaban por `EnviarCorreo`, asi que se quedaron fuera de la cola:
`POST /auth/register`, `/auth/forgot-password` y `/auth/resend-verification`
seguian pagando el saludo TCP+TLS (1,45 s medidos) antes de contestar.

Lo que estas pruebas fijan es que se difirio SOLO el envio: el correo es el
mismo, en modo en linea nada cambio, y estos avisos siguen SIN dejar evento de
bitacora, que es como funcionaron siempre.
"""
import threading
import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.main import app  # noqa: F401 - registra todos los modelos mapeados
from src.auth.application.services import auth_email_service as auth_email_modulo
from src.auth.application.services.auth_email_service import AuthEmailService
from src.bitacora.infrastructure.persistence.models.evento_bitacora import AuditEventModel
from src.infrastructure.config.settings import settings
from src.infrastructure.database.base import Base
from src.notificaciones.infrastructure.email.cola import ColaDeCorreos

TOKEN = "token-de-prueba-local"


class RemitenteEspia:
    """Guarda lo enviado y desde que hilo salio: el hilo es lo que distingue
    un envio diferido de uno que el request espero."""

    def __init__(self, demora: float = 0.0) -> None:
        self.demora = demora
        self.enviados: list[dict] = []
        self._candado = threading.Lock()

    def send(self, *, to: str, subject: str, body: str, html: str | None = None) -> bool:
        if self.demora:
            time.sleep(self.demora)
        with self._candado:
            self.enviados.append({"to": to, "subject": subject, "body": body, "html": html,
                                  "hilo": threading.current_thread().name})
        return True


@pytest.fixture
def base(tmp_path):
    # En archivo y no en memoria: el hilo de la cola abre su propia Session y
    # con `:memory:` cada conexion tendria una base distinta.
    engine = create_engine(f"sqlite:///{(tmp_path / 'prueba.db').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as db:
        yield engine, db
    engine.dispose()


def cola_de_prueba(monkeypatch, engine, **ajustes) -> ColaDeCorreos:
    """Enciende el modo fondo con una cola propia: la compartida del proceso
    abriria sus Session contra DATABASE_URL, o sea la base real."""
    cola = ColaDeCorreos(abrir_sesion=lambda: Session(engine, expire_on_commit=False), **ajustes)
    monkeypatch.setattr(settings, "email_background", True)
    monkeypatch.setattr(auth_email_modulo, "cola_de_correos", lambda: cola)
    return cola


def test_en_linea_se_envia_en_el_mismo_hilo_y_devuelve_el_booleano_real(base):
    """Con `email_background=False` el comportamiento es exactamente el de antes."""
    remitente = RemitenteEspia()

    assert AuthEmailService(remitente).send_verification("ana@fashionstore.test", TOKEN) is True
    envio = remitente.enviados[-1]
    assert envio["hilo"] == threading.current_thread().name
    assert envio["to"] == "ana@fashionstore.test"


def test_el_correo_es_identico_al_de_antes(base):
    """Asunto, cuerpo y enlace no se tocaron; sigue sin parte HTML."""
    remitente = RemitenteEspia()
    servicio = AuthEmailService(remitente)

    servicio.send_verification("ana@fashionstore.test", TOKEN)
    verificacion = remitente.enviados[-1]
    assert verificacion["subject"] == "Verifica tu cuenta de FashionStore"
    assert verificacion["body"] == (
        "Verifica tu correo ingresando al siguiente enlace:\n\n"
        f"{settings.frontend_url}/verificar-correo?token={TOKEN}"
    )
    # Cadena vacia y no HTML: el remitente solo agrega la parte alternativa si
    # `html` es verdadero, asi que el mensaje sale igual que siempre.
    assert not verificacion["html"]

    servicio.send_password_reset("ana@fashionstore.test", TOKEN)
    recuperacion = remitente.enviados[-1]
    assert recuperacion["subject"] == "Recupera tu contrasena de FashionStore"
    assert recuperacion["body"] == (
        "Puedes crear una nueva contrasena ingresando al siguiente enlace:\n\n"
        f"{settings.frontend_url}/recuperar-contrasena?token={TOKEN}"
    )


def test_en_modo_fondo_el_request_no_espera_al_smtp(base, monkeypatch):
    engine, _db = base
    cola = cola_de_prueba(monkeypatch, engine)
    # Un SMTP que tarda medio segundo: si el request lo esperara, el reloj lo diria.
    remitente = RemitenteEspia(demora=0.5)

    inicio = time.monotonic()
    assert AuthEmailService(remitente).send_verification("ana@fashionstore.test", TOKEN) is True
    demora = time.monotonic() - inicio

    assert demora < 0.2, f"El request espero {demora:.2f} s: el aviso no se difirio."
    assert cola.esperar(5.0), "La cola no llego a enviar el aviso."
    assert remitente.enviados[-1]["hilo"].startswith("correo-"), (
        "El correo salio en el hilo del request, no en el de la cola."
    )


def test_los_avisos_de_cuenta_siguen_sin_dejar_evento_de_bitacora(base, monkeypatch):
    """Nunca auditaron, y pasar por la cola no puede empezar a hacerlo.

    Va con `auditar=False`, que ademas evita que el hilo abra una Session -y
    tome una conexion del pool- solo para no escribir nada.
    """
    engine, db = base
    cola = cola_de_prueba(monkeypatch, engine)

    AuthEmailService(RemitenteEspia()).send_verification("ana@fashionstore.test", TOKEN)
    assert cola.esperar(5.0)

    assert db.scalars(select(AuditEventModel)).all() == []


def test_con_la_cola_llena_el_aviso_se_manda_en_linea_y_no_se_pierde(base, monkeypatch):
    """Antes que perder un enlace de verificacion, se paga la espera."""
    engine, _db = base
    # Cola de un lugar y sin trabajadores que la vacien: el segundo aviso no entra.
    cola = cola_de_prueba(monkeypatch, engine, tamano=1, trabajadores=0)
    # Sin hilos, `_arrancar` no tiene nada que levantar pero igual se registraria
    # en `atexit` una vez por aviso; neutralizarlo mantiene limpia a la suite.
    monkeypatch.setattr(cola, "_arrancar", lambda: None)
    remitente = RemitenteEspia()
    servicio = AuthEmailService(remitente)

    assert servicio.send_verification("primera@fashionstore.test", TOKEN) is True
    assert remitente.enviados == [], "El primero tenia que quedar encolado, no enviarse."

    assert servicio.send_verification("segunda@fashionstore.test", TOKEN) is True
    assert [envio["to"] for envio in remitente.enviados] == ["segunda@fashionstore.test"]
    assert remitente.enviados[-1]["hilo"] == threading.current_thread().name
    assert cola._cola.qsize() == 1
