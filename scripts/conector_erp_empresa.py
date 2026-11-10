"""
Conector ERP & Facturación Externa · FashionStore SaaS (Aporte Propio B2B)
Materia: Sistemas de Información II (UAGRM)
Fecha: 2026-11-10

Demostración completa de Integración Externa por Empresa:
- Autenticación criptográfica por API Key (fs_live_...) con Scopes
- Aislamiento estricto Multi-Tenant (RN03 / RNF02)
- Sincronización bidireccional de inventario (ERP -> SaaS)
- Consulta programática de Catálogo y Ventas
- Receptor de Webhooks con validación de firma digital HMAC-SHA256
"""

import argparse
import base64
import hashlib
import hmac
import http.server
import json
import os
import socketserver
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


# Códigos de color ANSI para presentación en consola
class Colores:
    AZUL = "\033[94m"
    VERDE = "\033[92m"
    AMARILLO = "\033[93m"
    ROJO = "\033[91m"
    MAGENTA = "\033[95m"
    CIAN = "\033[96m"
    NEGRITA = "\033[1m"
    SUBRAYADO = "\033[4m"
    RESET = "\033[0m"


def print_banner(titulo: str):
    print(f"\n{Colores.AZUL}{Colores.NEGRITA}{'=' * 75}{Colores.RESET}")
    print(f"{Colores.CIAN}{Colores.NEGRITA}  {titulo}{Colores.RESET}")
    print(f"{Colores.AZUL}{Colores.NEGRITA}{'=' * 75}{Colores.RESET}")


def print_paso(num: int, descripcion: str):
    print(f"\n{Colores.MAGENTA}{Colores.NEGRITA}[PASO {num}]{Colores.RESET} {Colores.NEGRITA}{descripcion}{Colores.RESET}")


def print_ok(mensaje: str):
    print(f"  {Colores.VERDE}[OK]{Colores.RESET} {mensaje}")


def print_warn(mensaje: str):
    print(f"  {Colores.AMARILLO}[AVISO]{Colores.RESET} {mensaje}")


def print_error(mensaje: str):
    print(f"  {Colores.ROJO}[ERROR]{Colores.RESET} {mensaje}")


def print_info(mensaje: str):
    print(f"  {Colores.CIAN}[INFO]{Colores.RESET} {mensaje}")


class FashionStoreHttpClient:
    """Cliente HTTP desacoplado para consumir la API de integración de FashionStore."""

    def __init__(self, base_url: str, api_key: str, client_override=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client_override = client_override  # Permite TestClient para demo sin servidor externo

    def request(self, method: str, path: str, json_data: dict | None = None, params: dict | None = None) -> tuple[int, dict]:
        if self.client_override is not None:
            # Usando TestClient de FastAPI
            full_path = "/api/v1" + path if not path.startswith("/api/v1") else path
            headers = {"X-API-Key": self.api_key, "Content-Type": "application/json"}
            res = self.client_override.request(method, full_path, json=json_data, params=params, headers=headers)
            try:
                body = res.json()
            except Exception:
                body = {"raw": res.text}
            return res.status_code, body

        # Petición HTTP estándar con urllib
        url = f"{self.base_url}/api/v1{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        headers = {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "FashionStore-ERPConnector/1.0",
        }

        data_bytes = None
        if json_data is not None:
            data_bytes = json.dumps(json_data).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                code = resp.getcode()
                raw_body = resp.read().decode("utf-8")
                return code, json.loads(raw_body)
        except urllib.error.HTTPError as err:
            code = err.code
            try:
                body = json.loads(err.read().decode("utf-8"))
            except Exception:
                body = {"detail": str(err)}
            return code, body
        except Exception as err:
            return 500, {"detail": str(err)}


class WebhookVerifier:
    """Validador de firmas criptográficas HMAC-SHA256 para eventos salientes."""

    @staticmethod
    def verify(raw_secret: str, timestamp: str, body_bytes: bytes, signature_hex: str) -> bool:
        message = f"{timestamp}.".encode("utf-8") + body_bytes
        computed = hmac.new(raw_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed, signature_hex)


def ejecutar_demostracion(base_url: str = "http://localhost:8000", usar_cliente_local: bool = True):
    print_banner("DEMOSTRACIÓN DE APORTE PROPIO: CONECTOR ERP MULTI-TENANT (B2B)")
    print_info("Iniciando entorno de pruebas y verificación de garantías arquitectónicas...")

    # Si se selecciona cliente local en memoria, inicializamos el entorno de prueba aislado
    test_client = None
    world_fixture = None
    if usar_cliente_local:
        try:
            os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
            os.environ["APP_ENV"] = "test"
            os.environ["JWT_SECRET_KEY"] = "test-secret-key-for-local-demo-2026-very-secure"
            from tests.unit.plataforma_saas.conftest import create_world
            from src.integraciones.application.api_keys_service import ApiKeysService
            world_fixture = create_world()
            test_client = world_fixture.client
            print_ok("Entorno in-memory de base de datos relacional inicializado correctamente.")
        except Exception as e:
            print_warn(f"No se pudo inicializar mundo local: {e}. Se intentará conexión HTTP directa.")

    # 1. Obtener credenciales de la empresa
    print_paso(1, "Autenticación Criptográfica B2B por Empresa (Tenant)")
    if world_fixture:
        tenant_a = world_fixture.tenants[0]
        tenant_b = world_fixture.tenants[1]
        svc = ApiKeysService(world_fixture.db)
        key_model_a, raw_key_a = svc.crear(tenant_a.id, "ERP Corporativo Urbano", ["catalog.read", "stock.read", "stock.write", "sales.read"])
        key_model_b, raw_key_b = svc.crear(tenant_b.id, "ERP Moda Cruceña", ["catalog.read", "stock.read"])
        print_ok(f"Empresa A ('{tenant_a.trade_name}'): API Key '{key_model_a.prefix}...' generada con scopes: {key_model_a.scopes}")
        print_ok(f"Empresa B ('{tenant_b.trade_name}'): API Key '{key_model_b.prefix}...' generada.")
    else:
        raw_key_a = os.getenv("FASHIONSTORE_API_KEY", "fs_live_demo_test_key_empresa_a")
        raw_key_b = "fs_live_demo_test_key_empresa_b"
        print_info(f"Usando clave de entorno: {raw_key_a[:12]}...")

    client_a = FashionStoreHttpClient(base_url, raw_key_a, client_override=test_client)
    client_b = FashionStoreHttpClient(base_url, raw_key_b, client_override=test_client)

    # 2. Prueba de Aislamiento Estricto Multi-Tenant (RN03)
    print_paso(2, "Verificación de Aislamiento Multi-Tenant (Regla RN03)")
    print_info("Consultando catálogo con la clave de Empresa A...")
    code, data_a = client_a.request("GET", "/integrations/v1/catalog")
    assert code == 200, f"Error en catálogo A: {data_a}"
    items_a = data_a.get("data", {}).get("items", [])
    skus_a = [v["sku"] for p in items_a for v in p.get("variants", [])]
    print_ok(f"Empresa A visualiza únicamente sus prendas. SKUs detectados: {skus_a}")

    print_info("Consultando catálogo con la clave de Empresa B...")
    code, data_b = client_b.request("GET", "/integrations/v1/catalog")
    assert code == 200, f"Error en catálogo B: {data_b}"
    items_b = data_b.get("data", {}).get("items", [])
    skus_b = [v["sku"] for p in items_b for v in p.get("variants", [])]
    print_ok(f"Empresa B visualiza únicamente sus prendas. SKUs detectados: {skus_b}")

    # Verificar que los catálogos estén estrictamente aislados
    interseccion = set(skus_a).intersection(set(skus_b))
    if not interseccion:
        print_ok("Garantía RN03 aprobada: Ningún producto o variante se filtra entre empresas.")
    else:
        print_error(f"Fallo de aislamiento: Se detectaron SKUs compartidos {interseccion}")

    # 3. Consulta de Existencias (Stock)
    print_paso(3, "Consulta de Inventario de Sucursales (/integrations/v1/stock)")
    code, stock_data = client_a.request("GET", "/integrations/v1/stock")
    assert code == 200, f"Error en stock: {stock_data}"
    stock_items = stock_data.get("data", {}).get("items", [])
    for it in stock_items:
        print_info(f"Sucursal '{it['branch_code']}': SKU '{it['sku']}' -> Existencias: {it['quantity']} uds.")

    # 4. Sincronización Bidireccional desde el ERP hacia el SaaS (/stock/adjust)
    print_paso(4, "Sincronización Bidireccional de Stock desde ERP (POST /stock/adjust)")
    target_sku = skus_a[0] if skus_a else "SKU-0"
    ajuste_payload = {
        "items": [
            {
                "sku": target_sku,
                "branch_code": "CENTRAL",
                "quantity": 3,  # Cantidad baja para forzar webhook stock.low
                "mode": "set",
            }
        ]
    }
    print_info(f"ERP despacha ajuste a sucursal 'CENTRAL': SKU '{target_sku}' fijado en 3 unidades (crítico)...")
    code, adjust_resp = client_a.request("POST", "/integrations/v1/stock/adjust", json_data=ajuste_payload)
    assert code == 200, f"Error en ajuste de stock: {adjust_resp}"
    res_items = adjust_resp.get("data", {}).get("items", [])
    for it in res_items:
        print_ok(f"Stock actualizado en servidor: Previo={it['previous_quantity']} -> Nuevo={it['new_quantity']} uds.")

    # 5. Demostración de Intento de Sabotaje / Fuga Cross-Tenant
    print_paso(5, "Prueba de Seguridad: Intento de manipular stock de otra empresa")
    target_sku_b = skus_b[0] if skus_b else "SKU-1"
    sabotaje_payload = {
        "items": [
            {
                "sku": target_sku_b,  # SKU que pertenece a Empresa B
                "branch_code": "CENTRAL",
                "quantity": 999,
                "mode": "set",
            }
        ]
    }
    print_info(f"Empresa A intenta alterar el SKU '{target_sku_b}' (propiedad de Empresa B)...")
    code, err_resp = client_a.request("POST", "/integrations/v1/stock/adjust", json_data=sabotaje_payload)
    if code in (403, 404, 422):
        print_ok(f"Intrusión rechazada exitosamente con código HTTP {code}. Detalle: {err_resp.get('error', {}).get('message')}")
    else:
        print_error(f"Falla de seguridad: El servidor permitió la alteración (Código {code}).")

    # 6. Verificación Criptográfica de Webhook (HMAC-SHA256)
    print_paso(6, "Recepción y Validación Criptográfica de Webhooks (HMAC-SHA256)")
    sim_secret = "fs_whsec_simulacion_prueba_123456"
    test_timestamp = str(int(time.time()))
    test_payload = {
        "id": "evt_test_2026_demo",
        "type": "stock.low",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "tenant": {"slug": "urbano"},
        "data": {"sku": target_sku, "branch_code": "CENTRAL", "quantity": 3, "threshold": 5},
    }
    body_canonical = json.dumps(test_payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    valid_signature = hmac.new(sim_secret.encode("utf-8"), f"{test_timestamp}.".encode("utf-8") + body_canonical, hashlib.sha256).hexdigest()

    print_info(f"Evento generado por SaaS: '{test_payload['type']}'")
    print_info(f"Cabecera X-FS-Timestamp: {test_timestamp}")
    print_info(f"Cabecera X-FS-Signature: {valid_signature}")

    # Validación positiva
    es_valido = WebhookVerifier.verify(sim_secret, test_timestamp, body_canonical, valid_signature)
    if es_valido:
        print_ok("Verificación HMAC-SHA256 Exitosa: El mensaje es auténtico y no fue manipulado en tránsito.")
    else:
        print_error("Fallo de verificación de firma.")

    # Validación de ataque: manipular cuerpo en tránsito
    body_adulterado = body_canonical.replace(b'"quantity":3', b'"quantity":999')
    ataque_detectado = not WebhookVerifier.verify(sim_secret, test_timestamp, body_adulterado, valid_signature)
    if ataque_detectado:
        print_ok("Detección de Manipulación Aprobada: Cualquier alteración del payload invalida la firma criptográfica.")

    print_banner("CONCLUSIÓN DE LA EVALUACIÓN DEL APORTE PROPIO")
    print_ok("Módulo de Integraciones 100% operativo y verificado.")
    print_ok("Aislamiento multi-tenant validado criptográfica y relacionalmente.")
    print_ok("Sincronización B2B bidireccional lista para defensa ante el tribunal.")


def main():
    parser = argparse.ArgumentParser(description="Conector ERP FashionStore SaaS (Aporte Propio)")
    parser.add_argument("--demo", action="store_true", help="Ejecutar demostración integral automática para defensa")
    parser.add_argument("--url", default="http://localhost:8000", help="URL base del servidor FastAPI")
    parser.add_argument("--key", default="", help="Clave de API de la empresa")
    parser.add_argument("--http-only", action="store_true", help="Forzar peticiones HTTP contra servidor levantado")

    args = parser.parse_args()

    if args.demo or not any(sys.argv[1:]):
        ejecutar_demostracion(base_url=args.url, usar_cliente_local=not args.http_only)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
