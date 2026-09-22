from src.main import app


def test_swagger_exposes_the_five_exam_packages():
    schema = app.openapi()
    names = {tag["name"] for tag in schema["tags"]}
    assert {
        "PAQ-01 · Usuarios y catálogo",
        "PAQ-02 · Inventario y sucursales",
        "PAQ-03 · Reservas y vestidor virtual",
        "PAQ-04 · Ventas y pagos",
        "PAQ-05 · Inteligencia artificial y reportes",
    } <= names

    assert "PAQ-01 · Usuarios y catálogo" in schema["paths"]["/api/v1/auth/login"]["post"]["tags"]
    assert "PAQ-02 · Inventario y sucursales" in schema["paths"]["/api/v1/public/branches"]["get"]["tags"]
    assert "PAQ-03 · Reservas y vestidor virtual" in schema["paths"]["/api/v1/reservations"]["get"]["tags"]
    assert "PAQ-04 · Ventas y pagos" in schema["paths"]["/api/v1/commerce/cart"]["get"]["tags"]
    assert "delete" in schema["paths"]["/api/v1/commerce/cart"]
    assert "PAQ-05 · Inteligencia artificial y reportes" in schema["paths"]["/api/v1/analytics/dashboard"]["get"]["tags"]
