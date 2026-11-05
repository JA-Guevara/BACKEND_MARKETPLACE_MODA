"""Script de verificación automática del despliegue (smoke test).

Verifica que todos los servicios y contratos del segundo parcial se encuentren
operativos y cumpliendo las reglas de negocio y aislamiento.

Uso:
  python -m scripts.verificar_despliegue [--base-url http://localhost:8000]
"""
import argparse
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")
import sys
import requests


def check(name: str, fn) -> bool:
    try:
        ok, msg = fn()
        if ok:
            print(f"  ✅ [PASS] {name}: {msg}")
            return True
        else:
            print(f"  ❌ [FAIL] {name}: {msg}")
            return False
    except Exception as e:
        print(f"  ❌ [ERROR] {name}: Excepción inesperada: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Verificador de despliegue y smoke test.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="URL base del backend a verificar")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    api_url = f"{base_url}/api/v1"

    print(f"🔍 Ejecutando verificación de despliegue sobre: {base_url}")
    results = []

    # 1. OpenAPI & Documentación
    def check_openapi():
        r = requests.get(f"{base_url}/openapi.json", timeout=10)
        if r.status_code == 200 and "openapi" in r.json():
            return True, f"OpenAPI {r.json().get('openapi')} disponible"
        return False, f"Status {r.status_code}"
    results.append(check("OpenAPI Schema", check_openapi))

    # 2. Catálogo público
    def check_catalog():
        r = requests.get(f"{api_url}/catalog/products", params={"page_size": 5}, timeout=10)
        if r.status_code == 200:
            data = r.json()
            return True, f"Catálogo respondiendo ({data.get('message', 'OK')})"
        return False, f"Status {r.status_code}: {r.text[:100]}"
    results.append(check("Catálogo Público", check_catalog))

    # 3. Acceso sin autenticación a endpoints privados bloqueado (401)
    def check_auth_enforcement():
        r = requests.get(f"{api_url}/tenant/devices", timeout=10)
        if r.status_code in (401, 403):
            return True, f"Protección de acceso activa ({r.status_code})"
        return False, f"Endpoint expuesto sin token: status {r.status_code}"
    results.append(check("Control de Acceso /tenant/devices", check_auth_enforcement))

    # 4. Control de acceso a promociones
    def check_promos_auth():
        r = requests.get(f"{api_url}/commerce/admin/promotions", timeout=10)
        if r.status_code in (401, 403):
            return True, f"Protección de promociones activa ({r.status_code})"
        return False, f"Endpoint expuesto: status {r.status_code}"
    results.append(check("Control de Acceso /commerce/admin/promotions", check_promos_auth))

    # 5. Instantánea offline protegida
    def check_snapshot_auth():
        r = requests.get(f"{api_url}/offline/snapshot", timeout=10)
        if r.status_code in (401, 403):
            return True, f"Protección de instantánea offline activa ({r.status_code})"
        return False, f"Endpoint expuesto: status {r.status_code}"
    results.append(check("Control de Acceso /offline/snapshot", check_snapshot_auth))

    # Resumen
    total = len(results)
    passed = sum(1 for r in results if r)
    print("\n" + "=" * 50)
    print(f"Resumen de Verificación: {passed}/{total} pruebas superadas.")
    print("=" * 50)

    if passed == total:
        print("🎉 Todos los smoke tests del despliegue fueron superados exitosamente.")
        sys.exit(0)
    else:
        print("⚠️ Se detectaron fallas en la verificación del despliegue.")
        sys.exit(1)


if __name__ == "__main__":
    main()
