"""Cola de correos: el envío sale del request y ocurre en segundo plano.

Un aviso cuesta unos 2,5 s —solo el saludo TCP+TLS con Gmail son 1,45 s medidos—
y hoy eso pasa *dentro* del request, reteniendo además la conexión de base de
datos todo ese rato. Acá se difiere únicamente lo que se puede diferir.

El corte está puesto a propósito en este punto y conviene respetarlo:

* El MENSAJE se sigue armando dentro del request, donde la Session está viva y
  se pueden leer los atributos del ORM. Lo que cruza al hilo son valores planos
  (`Mensaje` es un dataclass congelado de tres cadenas, el contexto es un dict
  de cadenas): ningún objeto del ORM viaja, así que no hay atributos perezosos
  que estallen contra una Session cerrada.
* La Session del request NO cruza al hilo. Para cuando el hilo corra ya está
  cerrada —`get_db` cierra en su `finally` y FastAPI cierra las dependencias con
  `yield` antes de los trabajos diferidos— y además la Session de SQLAlchemy no
  es segura entre hilos. El hilo abre la suya y la cierra.
* Los contextvars de bitácora no viajan solos: `Thread` no copia el contexto
  (solo lo hace `anyio.to_thread.run_sync`). Por eso la IP, el user-agent, el
  `request_id` y el actor ya resuelto se leen en el hilo del request y viajan
  como datos del trabajo. Sin esto, `docs/API_CONTRACT.md` dejaría de cumplirse
  para los eventos de correo, que aparecerían sin IP en GET /audit-log.
"""
import atexit
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from sqlalchemy.orm import Session

from src.bitacora.application.use_cases.registrar_evento import RecordAuditEvent
from src.infrastructure.config.settings import settings
from src.notificaciones.domain.diseno import Mensaje

_log = logging.getLogger(__name__)

#: Cuánto espera un hueco libre antes de rendirse. Si la cola está llena el
#: aviso NO se descarta: `encolar` devuelve False y el llamador lo manda en
#: línea, que es exactamente lo que hacía el backend antes de existir la cola.
#: Perder un aviso en silencio sería peor que la lentitud que vinimos a arreglar.
ESPERA_PARA_ENCOLAR = 2.0

#: Cuánto se espera a que la cola se vacíe cuando el proceso se apaga. Railway
#: manda SIGTERM al reiniciar el contenedor y los hilos son demonio: sin este
#: drenaje, los avisos todavía encolados morirían con el proceso. El margen es
#: corto a propósito para no agotar el período de gracia del reinicio.
ESPERA_AL_APAGAR = 10.0


@dataclass(frozen=True)
class TrabajoCorreo:
    """Todo lo que el hilo necesita para enviar y auditar, ya sin ORM ni Session."""

    remitente: Any  # cualquier objeto con .send(to, subject, body, html) -> bool
    destinatario: str
    mensaje: Mensaje
    entidad: str
    entidad_id: str | None = None
    actor_id: uuid.UUID | None = None
    contexto: dict = field(default_factory=dict)
    # Los avisos de autenticación (verificar cuenta, recuperar contraseña) nunca
    # dejaron evento de bitácora: mandarlos por la cola no puede empezar a
    # dejarlo. Con `auditar=False` el trabajo se limita al SMTP y ni siquiera
    # abre una Session, así que tampoco toma una conexión del pool.
    auditar: bool = True
    # Copia plana del contexto de auditoría del request (ver nota del módulo).
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None


def enviar(trabajo: TrabajoCorreo) -> bool:
    """Solo el SMTP. Nunca levanta: un aviso no puede tumbar lo que lo originó."""
    try:
        return bool(
            trabajo.remitente.send(
                to=trabajo.destinatario,
                subject=trabajo.mensaje.asunto,
                body=trabajo.mensaje.texto,
                html=trabajo.mensaje.html,
            )
        )
    except Exception:  # noqa: BLE001 - el aviso nunca interrumpe la operación
        return False


def registrar(db: Session, trabajo: TrabajoCorreo, enviado: bool) -> None:
    """Deja el evento de bitácora en la Session recibida y confirma.

    Se pasan `ip_address`, `user_agent` y `request_id` explícitos porque en el
    hilo de fondo los contextvars ya no existen; en línea valen lo mismo que
    leería `RecordAuditEvent` por su cuenta, así que el resultado es idéntico.
    """
    metadata = {
        # El destinatario queda en bitácora para poder auditar el aviso;
        # el cuerpo no, porque repetiría datos del pedido sin aportar.
        "to": trabajo.destinatario,
        "sent": enviado,
        **trabajo.contexto,
    }
    if trabajo.request_id:
        metadata["request_id"] = trabajo.request_id
    try:
        RecordAuditEvent(db).execute(
            action="notificaciones.email_enviado" if enviado else "notificaciones.email_fallido",
            entity_type=trabajo.entidad,
            entity_id=trabajo.entidad_id,
            description=trabajo.mensaje.asunto,
            actor_user_id=trabajo.actor_id,
            metadata=metadata,
            ip_address=trabajo.ip_address,
            user_agent=trabajo.user_agent,
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()


def _sesion_por_defecto() -> Session:
    """Session nueva para el hilo.

    El import es diferido a propósito: atar este módulo al motor en tiempo de
    importación obligaría a construir el engine con solo importar el caso de uso
    del correo, y las pruebas unitarias trabajan con su propio SQLite.
    """
    from src.infrastructure.database.session import SessionLocal

    return SessionLocal()


def procesar(trabajo: TrabajoCorreo, abrir_sesion: Callable[[], Session]) -> bool:
    """Envía y audita con una Session propia, que se cierra siempre."""
    enviado = enviar(trabajo)
    if not trabajo.auditar:
        # Sin evento que escribir no hay por qué abrir una Session: abrirla solo
        # para cerrarla gastaría una conexión del pool por cada aviso.
        return enviado
    db = abrir_sesion()
    try:
        registrar(db, trabajo, enviado)
    finally:
        db.close()
    return enviado


class ColaDeCorreos:
    """Cola acotada con hilos demonio que envían fuera del request."""

    def __init__(
        self,
        *,
        tamano: int | None = None,
        trabajadores: int | None = None,
        abrir_sesion: Callable[[], Session] | None = None,
    ) -> None:
        self._cola: queue.Queue = queue.Queue(maxsize=tamano or settings.email_queue_size)
        self._cantidad = trabajadores or settings.email_workers
        self._abrir_sesion = abrir_sesion or _sesion_por_defecto
        self._hilos: list[threading.Thread] = []
        self._candado = threading.Lock()
        self._apagando = threading.Event()
        # Contador propio en vez de `Queue.join()`: hace falta poder esperar con
        # un límite de tiempo, y `join()` no lo admite.
        self._pendientes = 0
        self._vacia = threading.Condition()

    # --- uso desde el request --------------------------------------------

    def encolar(self, trabajo: TrabajoCorreo) -> bool:
        """True si el aviso quedó aceptado; False si el llamador debe enviarlo él."""
        if self._apagando.is_set():
            return False
        self._arrancar()
        with self._vacia:
            self._pendientes += 1
        try:
            self._cola.put(trabajo, timeout=ESPERA_PARA_ENCOLAR)
        except queue.Full:
            self._descontar()
            return False
        return True

    # --- ciclo de vida ----------------------------------------------------

    def _arrancar(self) -> None:
        """Arranque perezoso: importar el módulo no debe levantar hilos.

        Si los hilos nacieran al importar, cada proceso de pytest —que importa
        `src.main` en casi todos los archivos— quedaría con hilos vivos sin
        haber enviado un solo correo.
        """
        if self._hilos:
            return
        with self._candado:
            if self._hilos or self._apagando.is_set():
                return
            for indice in range(self._cantidad):
                hilo = threading.Thread(
                    target=self._trabajar, name=f"correo-{indice + 1}", daemon=True
                )
                hilo.start()
                self._hilos.append(hilo)
            atexit.register(self.apagar)

    def _trabajar(self) -> None:
        while True:
            trabajo = self._cola.get()
            # La señal de apagado no es un aviso: no se descuenta del pendiente.
            if trabajo is None:
                return
            try:
                procesar(trabajo, self._abrir_sesion)
            except Exception:  # noqa: BLE001 - un aviso roto no puede matar al hilo
                _log.exception("No se pudo procesar un aviso por correo")
            finally:
                self._descontar()

    def _descontar(self) -> None:
        with self._vacia:
            self._pendientes -= 1
            if self._pendientes <= 0:
                self._vacia.notify_all()

    def esperar(self, espera: float = 5.0) -> bool:
        """Espera a que no queden avisos pendientes. True si se vació a tiempo."""
        with self._vacia:
            return self._vacia.wait_for(lambda: self._pendientes <= 0, timeout=espera)

    def apagar(self, espera: float = ESPERA_AL_APAGAR) -> None:
        """Drena lo que quede y para los hilos. Repetirlo no hace nada."""
        with self._candado:
            hilos, self._hilos = self._hilos, []
            # A partir de acá `encolar` devuelve False y los avisos nuevos salen
            # en línea: durante el apagado tampoco se pierde ninguno.
            self._apagando.set()
        if not hilos:
            return
        limite = time.monotonic() + espera
        self.esperar(espera)
        for _ in hilos:
            try:
                self._cola.put(None, timeout=1.0)
            except queue.Full:  # la cola no se vació a tiempo; se resuelve abajo
                pass
        for hilo in hilos:
            hilo.join(timeout=max(0.0, limite - time.monotonic()) + 1.0)
        self._vaciar_a_mano()

    def _vaciar_a_mano(self) -> None:
        """Manda acá mismo lo que los hilos ya no van a tomar.

        Cubre dos huecos del apagado: que el drenaje no haya alcanzado a
        terminar dentro del margen, y el aviso que entró justo mientras se
        cerraba. En los dos casos, un correo encolado que nadie procese sería un
        correo perdido, que es exactamente lo que no se puede permitir.
        """
        while True:
            try:
                trabajo = self._cola.get_nowait()
            except queue.Empty:
                return
            if trabajo is None:
                continue
            try:
                procesar(trabajo, self._abrir_sesion)
            except Exception:  # noqa: BLE001
                _log.exception("No se pudo procesar un aviso por correo durante el apagado")
            finally:
                self._descontar()


_cola: ColaDeCorreos | None = None
_candado_global = threading.Lock()


def cola_de_correos() -> ColaDeCorreos:
    """Cola compartida del proceso, creada la primera vez que se la necesita."""
    global _cola
    with _candado_global:
        if _cola is None:
            _cola = ColaDeCorreos()
        return _cola


def apagar_cola(espera: float = ESPERA_AL_APAGAR) -> None:
    """Punto de entrada del apagado ordenado (lo llama el ciclo de vida de la app)."""
    with _candado_global:
        cola = _cola
    if cola is not None:
        cola.apagar(espera)
