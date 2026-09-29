"""Red de seguridad: ningún endpoint puede congelar el bucle de eventos.

El backend arranca con un solo proceso de uvicorn. En FastAPI, un handler
declarado ``def`` se ejecuta en el pool de hilos y solo ocupa un hilo, mientras
que uno declarado ``async def`` corre DENTRO del bucle de eventos: cualquier
espera síncrona ahí (una llamada HTTP con httpx, Pillow, openpyxl o una consulta
de SQLAlchemy) detiene TODAS las peticiones del proceso, no solo la propia.

Cinco endpoints hacían exactamente eso. Esta prueba fija el criterio para que
nadie lo reintroduzca sin darse cuenta: si alguien vuelve a poner ``async def``
en un endpoint con trabajo bloqueante, falla acá y no en producción.
"""

import inspect

from fastapi.routing import APIRoute

from src.main import create_app
from src.shared.bulk import router as bulk_router
from src.usuarios_catalogo.web.routers import media_router
from src.ventas_pagos.web import router as ventas_router


# Endpoints `async def` que SÍ tienen trabajo bloqueante, con el motivo por el
# que no pueden ser `def`. La condición de la excepción es que ese trabajo baje
# igual al pool de hilos con `run_in_threadpool`.
ASYNC_JUSTIFICADOS = {
    "webhook": "Stripe firma los bytes exactos del cuerpo: hace falta await request.body().",
}

# Endpoints `async def` que no hacen NADA bloqueante. Para ellos el bucle de
# eventos es el lugar correcto -no gastan un hilo del pool-, así que la
# condición es la inversa: que no aparezca ninguna de las llamadas que bloquean.
ASYNC_SIN_TRABAJO = {
    "health": "Devuelve un literal: no toca base, red ni disco.",
}

# Marcas de trabajo bloqueante. No pretende ser exhaustiva: alcanza con que
# cubra lo que este backend usa, que es lo que congelaba el proceso.
SENALES_DE_BLOQUEO = ("httpx.", "db.", "Session(", "open(", "Image.", "load_workbook", "time.sleep")


def _endpoints_de_la_app():
    return [route for route in create_app().routes if isinstance(route, APIRoute)]


def test_ningun_endpoint_async_deja_trabajo_bloqueante_en_el_bucle():
    infractores = []
    for route in _endpoints_de_la_app():
        if not inspect.iscoroutinefunction(route.endpoint):
            continue
        nombre = route.endpoint.__name__
        codigo = inspect.getsource(route.endpoint)
        if nombre in ASYNC_JUSTIFICADOS:
            if "run_in_threadpool" not in codigo:
                infractores.append(f"{route.path} -> {nombre} (ya no delega en run_in_threadpool)")
        elif nombre in ASYNC_SIN_TRABAJO:
            usadas = [senal for senal in SENALES_DE_BLOQUEO if senal in codigo]
            if usadas:
                infractores.append(f"{route.path} -> {nombre} (dejó de ser trivial: {', '.join(usadas)})")
        else:
            infractores.append(f"{route.path} -> {nombre}")
    assert infractores == [], (
        "Estos endpoints son 'async def' y bloquearían el bucle de eventos. "
        "Declaralos 'def' o delegá el trabajo pesado con run_in_threadpool: "
        + ", ".join(infractores)
    )


def test_el_chequeo_de_salud_no_compite_por_el_pool_de_hilos():
    # `/health` es lo que mira Railway para decidir si el proceso está vivo.
    # Siendo `def` compartía los 40 hilos de anyio con la transcripción, el
    # Excel y las imágenes: con el pool lleno el chequeo se encolaba detrás de
    # ellos y podía dar falso negativo justo cuando más carga había.
    ruta = next(r for r in create_app().routes if isinstance(r, APIRoute) and r.path == "/health")
    assert inspect.iscoroutinefunction(ruta.endpoint), (
        "/health volvió a ser 'def' y otra vez depende de que haya un hilo libre."
    )


def test_los_cuatro_endpoints_pesados_corren_en_el_pool_de_hilos():
    # httpx síncrono con reintento (hasta el doble de ai_timeout), openpyxl,
    # escrituras masivas y Pillow: todo trabajo que debe salir del bucle.
    for funcion in (
        ventas_router.transcribe_assistant_audio,
        bulk_router.preview,
        bulk_router.import_excel,
        media_router.upload_image,
    ):
        assert not inspect.iscoroutinefunction(funcion), (
            f"{funcion.__name__} volvió a ser 'async def' y congela el proceso entero."
        )


def test_el_webhook_de_stripe_delega_el_trabajo_pesado_a_un_hilo():
    # Es la única excepción: necesita `await request.body()` para conservar los
    # bytes exactos que Stripe firmó. A cambio, el HMAC, el bloqueo de la fila
    # del pedido y el correo tienen que ejecutarse fuera del bucle.
    assert inspect.iscoroutinefunction(ventas_router.webhook)
    assert "run_in_threadpool" in inspect.getsource(ventas_router.webhook)


def test_el_lector_de_excel_no_devuelve_una_corrutina():
    # `read_file` lo llaman preview e import_excel sin await: si volviera a ser
    # `async def`, el "contenido" sería un objeto corrutina y el error recién
    # aparecería adentro de openpyxl, lejos de la causa.
    assert not inspect.iscoroutinefunction(bulk_router.read_file)
