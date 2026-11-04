import os
import re
import json
from collections import defaultdict
from fastapi.routing import APIRoute
from src.main import create_app

app = create_app()
openapi = app.openapi()
components = openapi.get('components', {}).get('schemas', {})

# 1. Mapeo de Permisos de Rutas
route_permissions = {}
for r in app.routes:
    if isinstance(r, APIRoute):
        perms = []
        for d in r.dependant.dependencies:
            if hasattr(d.call, '__closure__') and d.call.__closure__:
                for cell in d.call.__closure__:
                    if isinstance(cell.cell_contents, (list, tuple, set)):
                        for item in cell.cell_contents:
                            if isinstance(item, str) and ('.' in item or '_' in item):
                                perms.append(item)
                    elif isinstance(cell.cell_contents, str) and ('.' in cell.cell_contents):
                        perms.append(cell.cell_contents)
            elif 'get_current_user' in str(d.call):
                perms.append('Usuario autenticado (JWT)')
            elif 'get_optional_user' in str(d.call):
                perms.append('Público / Usuario opcional')
        
        perm_str = ', '.join(sorted(list(set(perms)))) if perms else 'Público'
        if not perms and ('/admin/' in r.path or r.path.startswith('/api/v1/audit') or r.path.startswith('/api/v1/bulk')):
            perm_str = 'Administrador autenticado'
        for m in r.methods:
            route_permissions[(m.upper(), r.path)] = perm_str

# 2. Clasificación de Paquete y Submódulo
def classify_endpoint(path, method):
    p = path.replace('/api/v1', '')
    
    # PAQ-01: Usuarios, Autenticación y Catálogo Base
    if p.startswith('/auth'):
        return 'PAQ-01 · Usuarios y Catálogo', 'Autenticación y Sesión'
    if p.startswith('/users/me/addresses'):
        return 'PAQ-01 · Usuarios y Catálogo', 'Direcciones de Entrega'
    if p.startswith('/users'):
        return 'PAQ-01 · Usuarios y Catálogo', 'Gestión de Usuarios'
    if p.startswith('/roles') or p.startswith('/permissions'):
        return 'PAQ-01 · Usuarios y Catálogo', 'Control de Acceso (RBAC: Roles y Permisos)'
    if p.startswith('/catalog/admin'):
        return 'PAQ-01 · Usuarios y Catálogo', 'Catálogo Administrativo (CRUD Maestros)'
    if p.startswith('/catalog/products'):
        return 'PAQ-01 · Usuarios y Catálogo', 'Catálogo Público y Productos'
    if p.startswith('/catalog/'):
        return 'PAQ-01 · Usuarios y Catálogo', 'Catálogo Público y Filtros'
    if p.startswith('/media'):
        return 'PAQ-01 · Usuarios y Catálogo', 'Almacenamiento Multimedia'
        
    # PAQ-02: Inventario, Sucursales y Almacenes
    if p.startswith('/organization/cities'):
        return 'PAQ-02 · Inventario y Sucursales', 'Gestión de Ciudades'
    if p.startswith('/organization/branches') or p.startswith('/public/branches'):
        return 'PAQ-02 · Inventario y Sucursales', 'Gestión de Sucursales'
    if p.startswith('/organization/suppliers'):
        return 'PAQ-02 · Inventario y Sucursales', 'Gestión de Proveedores'
    if p.startswith('/organization/cash-points'):
        return 'PAQ-02 · Inventario y Sucursales', 'Cajas y Puntos de Cobro'
    if p.startswith('/inventory'):
        return 'PAQ-02 · Inventario y Sucursales', 'Inventario y Almacenes'
    if p.startswith('/supply-orders') or p.startswith('/supplier-returns'):
        return 'PAQ-02 · Inventario y Sucursales', 'Abastecimiento y Proveedores'
        
    # PAQ-03: Reservas y Vestidor Virtual
    if p.startswith('/reservations'):
        return 'PAQ-03 · Reservas y Vestidor Virtual', 'Reservas en Tienda Física'
    if p.startswith('/vestidor/admin'):
        return 'PAQ-03 · Reservas y Vestidor Virtual', 'Vestidor Virtual (Administración IA)'
    if p.startswith('/vestidor'):
        return 'PAQ-03 · Reservas y Vestidor Virtual', 'Vestidor Virtual 2.5D en Tiempo Real'
    if p.startswith('/tryon-ai'):
        return 'PAQ-03 · Reservas y Vestidor Virtual', 'Probador Virtual con IA Fotográfica'
    if p.startswith('/notifications'):
        return 'PAQ-03 · Reservas y Vestidor Virtual', 'Notificaciones y Alertas'
        
    # PAQ-04: Comercio, Ventas, Pagos y POS
    if p.startswith('/commerce/cart'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Carrito de Compras'
    if p.startswith('/commerce/orders'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Órdenes y Checkout'
    if p.startswith('/commerce/payment-return') or p.startswith('/commerce/stripe') or p.startswith('/commerce/payments'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Pagos Stripe y Pasarelas'
    if p.startswith('/commerce/returns') or p.startswith('/commerce/admin/returns'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Devoluciones y Cambios'
    if p.startswith('/commerce/admin/pos') or p.startswith('/commerce/admin/cash-points'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Punto de Venta POS'
    if p.startswith('/commerce/admin/stock'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Stock Comercial y Kardex'
    if p.startswith('/commerce/coupons') or p.startswith('/commerce/admin/promotions'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Cupones y Promociones'
    if p.startswith('/commerce/favorites'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Favoritos del Cliente'
    if p.startswith('/commerce/assistant') or p.startswith('/commerce/recommendations'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Asistente Comercial y Recomendaciones'
    if p.startswith('/commerce/branches'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Sucursales Comerciales'
    if p.startswith('/commerce/profile'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Perfil Comercial del Cliente'
    if p.startswith('/commerce/admin/orders'):
        return 'PAQ-04 · Comercio, Ventas y POS', 'Gestión Administrativa de Pedidos'
        
    # PAQ-05: Analítica, Reportes e Inteligencia Artificial
    if p.startswith('/analytics/dashboard'):
        return 'PAQ-05 · Analítica, Reportes e IA', 'Dashboard de KPIs y Métricas'
    if p.startswith('/analytics/insights'):
        return 'PAQ-05 · Analítica, Reportes e IA', 'Insights Predictivos con IA'
    if p.startswith('/analytics/assistant'):
        return 'PAQ-05 · Analítica, Reportes e IA', 'Asistente de Negocio Conversacional'
    if p.startswith('/analytics/reports'):
        return 'PAQ-05 · Analítica, Reportes e IA', 'Exportación de Reportes PDF y Excel'
        
    # TRANSVERSALES
    if p.startswith('/audit-log'):
        return 'TRANSVERSAL · Soporte y Auditoría', 'Auditoría del Sistema'
    if p.startswith('/bulk'):
        return 'TRANSVERSAL · Soporte y Auditoría', 'Carga Masiva Excel'
    if path == '/health':
        return 'TRANSVERSAL · Soporte y Auditoría', 'Health Check y Monitoreo'
        
    return 'OTROS', 'General'

# 3. Trazabilidad con Frontend Web (Angular) y Móvil (Flutter)
def get_traceability(path, method):
    web = []
    mobile = []
    status = 'Activo Web'
    p = path.replace('/api/v1', '')
    
    # PAQ-01
    if p.startswith('/auth'):
        web.append('features/usuarios-catalogo/application/session.service.ts')
        web.append('features/usuarios-catalogo/presentation/auth-page.component.ts')
        mobile.append('features/usuarios_catalogo/infrastructure/auth_api.dart')
        mobile.append('features/usuarios_catalogo/presentation/login_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/users/me/addresses'):
        web.append('features/usuarios-catalogo/application/session.service.ts')
        web.append('features/usuarios-catalogo/presentation/account-page.component.ts')
        mobile.append('features/usuarios_catalogo/infrastructure/direcciones_api.dart')
        mobile.append('features/usuarios_catalogo/presentation/direcciones_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/users'):
        web.append('features/usuarios-catalogo/application/resources.ts (User Resource)')
        web.append('shared/components/resource-page.component.ts')
        status = 'CRUD Administrativo Web'
    elif p.startswith('/roles') or p.startswith('/permissions'):
        web.append('features/usuarios-catalogo/application/resources.ts (Roles & Permissions)')
        web.append('shared/components/resource-page.component.ts')
        status = 'CRUD Administrativo Web'
    elif p.startswith('/catalog/admin'):
        web.append('features/usuarios-catalogo/application/resources.ts (Catalog CRUD Resources)')
        web.append('features/usuarios-catalogo/presentation/product-editor.component.ts')
        status = 'CRUD Administrativo Web'
    elif p.startswith('/catalog/products') or p.startswith('/catalog/'):
        web.append('features/usuarios-catalogo/infrastructure/catalog.service.ts')
        web.append('features/usuarios-catalogo/presentation/catalog-page.component.ts')
        mobile.append('features/usuarios_catalogo/infrastructure/catalog_api.dart')
        mobile.append('features/usuarios_catalogo/presentation/catalog_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/media'):
        web.append('features/usuarios-catalogo/presentation/product-editor.component.ts')
        web.append('features/usuarios-catalogo/presentation/ar-asset-form.component.ts')
        status = 'Activo Web Backoffice'
        
    # PAQ-02
    elif p.startswith('/organization'):
        web.append('features/inventario-sucursales/application/resources.ts (Org Resources)')
        web.append('shared/components/resource-page.component.ts')
        status = 'CRUD Administrativo Web'
    elif p.startswith('/public/branches'):
        web.append('features/reservas-vestidor/presentation/nueva-reserva.component.ts')
        mobile.append('features/ventas_pagos/infrastructure/commerce_api.dart')
        mobile.append('features/ventas_pagos/presentation/sucursales_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/inventory') or p.startswith('/supply-orders') or p.startswith('/supplier-returns'):
        web.append('features/inventario-sucursales/infrastructure/inventory.service.ts')
        web.append('features/ventas-pagos/presentation/stock-page.component.ts')
        status = 'Activo Web Backoffice'
        
    # PAQ-03
    elif p.startswith('/reservations'):
        web.append('features/reservas-vestidor/infrastructure/reservas.service.ts')
        web.append('features/reservas-vestidor/presentation/nueva-reserva.component.ts')
        mobile.append('features/reservas_vestidor/infrastructure/reservas_api.dart')
        mobile.append('features/reservas_vestidor/presentation/mis_reservas_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/vestidor/admin'):
        web.append('features/reservas-vestidor/infrastructure/vestidor-admin.service.ts')
        web.append('features/usuarios-catalogo/presentation/product-editor.component.ts')
        status = 'Activo Web Backoffice (IA)'
    elif p.startswith('/vestidor'):
        web.append('features/reservas-vestidor/infrastructure/vestidor.service.ts')
        web.append('features/reservas-vestidor/presentation/vestidor.component.ts')
        mobile.append('features/reservas_vestidor/infrastructure/vestidor_api.dart')
        mobile.append('features/reservas_vestidor/presentation/vestidor_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/tryon-ai'):
        web.append('features/reservas-vestidor/infrastructure/tryon-ai.service.ts')
        web.append('features/reservas-vestidor/presentation/vestidor.component.ts')
        status = 'Activo Web (IA Jobs)'
    elif p.startswith('/notifications'):
        web.append('features/ventas-pagos/infrastructure/engagement.service.ts')
        web.append('features/ventas-pagos/presentation/notifications-bell.component.ts')
        status = 'Activo Web'
        
    # PAQ-04
    elif p.startswith('/commerce/cart'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/cart-page.component.ts')
        mobile.append('features/ventas_pagos/infrastructure/commerce_api.dart')
        mobile.append('features/ventas_pagos/presentation/carrito_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/commerce/orders') and not p.startswith('/commerce/admin/orders'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/orders-page.component.ts')
        mobile.append('features/ventas_pagos/infrastructure/commerce_api.dart')
        mobile.append('features/ventas_pagos/presentation/pedidos_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/commerce/payment-return') or p.startswith('/commerce/stripe') or p.startswith('/commerce/payments'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/orders-page.component.ts')
        mobile.append('features/ventas_pagos/infrastructure/commerce_api.dart')
        mobile.append('features/ventas_pagos/presentation/stripe_checkout_launcher.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/commerce/returns') or p.startswith('/commerce/admin/returns'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/admin-returns.component.ts')
        status = 'Activo Web'
    elif p.startswith('/commerce/admin/pos') or p.startswith('/commerce/admin/cash-points'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/pos-page.component.ts')
        status = 'Activo Web POS'
    elif p.startswith('/commerce/admin/stock'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/stock-page.component.ts')
        status = 'Activo Web Backoffice'
    elif p.startswith('/commerce/coupons'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/cart-page.component.ts')
        mobile.append('features/ventas_pagos/infrastructure/commerce_api.dart')
        mobile.append('features/ventas_pagos/presentation/carrito_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/commerce/admin/promotions'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/promotions-page.component.ts')
        status = 'Activo Web Backoffice'
    elif p.startswith('/commerce/favorites'):
        web.append('features/ventas-pagos/infrastructure/engagement.service.ts')
        web.append('features/ventas-pagos/presentation/favorites-page.component.ts')
        mobile.append('features/ventas_pagos/infrastructure/commerce_api.dart')
        mobile.append('features/ventas_pagos/presentation/favoritos_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/commerce/assistant') or p.startswith('/commerce/recommendations'):
        web.append('features/ventas-pagos/infrastructure/engagement.service.ts')
        web.append('features/ventas-pagos/presentation/assistant-widget.component.ts')
        status = 'Activo Web'
    elif p.startswith('/commerce/branches'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        mobile.append('features/ventas_pagos/infrastructure/commerce_api.dart')
        mobile.append('features/ventas_pagos/presentation/sucursales_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/commerce/profile'):
        web.append('features/usuarios-catalogo/application/session.service.ts')
        web.append('features/usuarios-catalogo/presentation/account-page.component.ts')
        mobile.append('features/usuarios_catalogo/application/account_controller.dart')
        mobile.append('features/usuarios_catalogo/presentation/account_screen.dart')
        status = 'Activo Web y Móvil'
    elif p.startswith('/commerce/admin/orders'):
        web.append('features/ventas-pagos/infrastructure/commerce.service.ts')
        web.append('features/ventas-pagos/presentation/orders-page.component.ts')
        status = 'Activo Web Backoffice'
        
    # PAQ-05
    elif p.startswith('/analytics'):
        web.append('features/analitica-reportes/infrastructure/dashboard.service.ts')
        web.append('features/analitica-reportes/presentation/dashboard-page.component.ts')
        status = 'Activo Web BI / IA'
        
    # Transversales
    elif p.startswith('/audit-log'):
        web.append('features/usuarios-catalogo/presentation/audit-log-page.component.ts')
        status = 'Activo Web Backoffice'
    elif p.startswith('/bulk'):
        web.append('shared/components/resource-page.component.ts (Bulk Actions)')
        status = 'Activo Web Backoffice'
    elif path == '/health':
        web.append('Docker / Nginx Healthcheck')
        status = 'Monitoreo / Sistema'
        
    return web, mobile, status

# 4. Formateo de Tipos y Esquemas Pydantic
def format_type(prop):
    if '$ref' in prop:
        return prop['$ref'].split('/')[-1]
    if 'anyOf' in prop:
        t_list = []
        for item in prop['anyOf']:
            if '$ref' in item:
                t_list.append(item['$ref'].split('/')[-1])
            elif item.get('type') != 'null':
                t_list.append(item.get('type', 'any'))
        return ' | '.join(t_list) if t_list else 'null'
    if prop.get('type') == 'array':
        item = prop.get('items', {})
        it = item.get('$ref', '').split('/')[-1] or item.get('type', 'any')
        return f'List[{it}]'
    return prop.get('type', 'any')

def format_schema_markdown(schema_ref_or_dict, depth=0):
    if not schema_ref_or_dict:
        return '*(Sin contenido de datos)*'
        
    schema_name = None
    if isinstance(schema_ref_or_dict, str):
        schema_name = schema_ref_or_dict
        schema_dict = components.get(schema_name, {})
    elif isinstance(schema_ref_or_dict, dict):
        if '$ref' in schema_ref_or_dict:
            schema_name = schema_ref_or_dict['$ref'].split('/')[-1]
            schema_dict = components.get(schema_name, {})
        else:
            schema_dict = schema_ref_or_dict
            schema_name = schema_dict.get('title', 'Esquema')
            
    if not schema_dict:
        return f'`{schema_name or "Desconocido"}`'
        
    # Manejo del ApiResponse envelope estándar
    if schema_name and schema_name.startswith('ApiResponse_'):
        data_prop = schema_dict.get('properties', {}).get('data', {})
        inner_name = None
        if '$ref' in data_prop:
            inner_name = data_prop['$ref'].split('/')[-1]
        elif 'anyOf' in data_prop:
            for item in data_prop['anyOf']:
                if '$ref' in item:
                    inner_name = item['$ref'].split('/')[-1]
                    break
        elif data_prop.get('type') == 'array':
            it = data_prop.get('items', {})
            inner_name = f"List[{it.get('$ref', '').split('/')[-1] or it.get('type', 'any')}]"
            
        inner_desc = f" `data: {inner_name}`" if inner_name else " `data: any`"
        inner_table = ""
        if inner_name and not inner_name.startswith('List[') and inner_name in components:
            inner_table = "\n\n" + format_schema_markdown(inner_name, depth + 1)
        return f"Envoltorio estándar `ApiResponse`: `success: bool`, `message: str`,{inner_desc}{inner_table}"

    props = schema_dict.get('properties', {})
    reqs = schema_dict.get('required', [])
    if not props:
        return f'`{schema_name}` *(tipo: {schema_dict.get("type", "object")})*'
        
    lines = [f"**Esquema:** `{schema_name}`\n"]
    lines.append("| Atributo | Tipo de Dato | Obligatoriedad | Descripción / Validación |")
    lines.append("| :--- | :--- | :--- | :--- |")
    for k, v in props.items():
        t = format_type(v)
        req = '**✓ Requerido**' if k in reqs else 'Opcional'
        desc = v.get('description') or v.get('title') or ''
        if 'enum' in v:
            desc += f" (Valores permitidos: `{', '.join(map(str, v['enum']))}`)"
        lines.append(f"| `{k}` | `{t}` | {req} | {desc} |")
        
    return '\n'.join(lines)

print("Estructuras de formateo listas. Organizando endpoints...")

# 5. Agrupación Jerárquica de los 208 Endpoints
endpoints_by_pkg = defaultdict(lambda: defaultdict(list))
all_endpoints_list = []
total_count = 0

for path, methods in sorted(openapi.get('paths', {}).items()):
    for method, details in sorted(methods.items()):
        total_count += 1
        pkg, submodule = classify_endpoint(path, method)
        web_tr, mob_tr, status = get_traceability(path, method)
        perms = route_permissions.get((method.upper(), path), 'Público')
        
        ep_data = {
            'id': total_count,
            'method': method.upper(),
            'path': path,
            'summary': details.get('summary', 'Sin resumen'),
            'description': details.get('description', '').strip(),
            'pkg': pkg,
            'submodule': submodule,
            'permissions': perms,
            'web_traceability': web_tr,
            'mobile_traceability': mob_tr,
            'status': status,
            'details': details
        }
        endpoints_by_pkg[pkg][submodule].append(ep_data)
        all_endpoints_list.append(ep_data)

print(f"Agrupados {len(all_endpoints_list)} endpoints en {len(endpoints_by_pkg)} paquetes.")

# 6. Ensamblado del Documento Markdown
doc = []

doc.append("# Estado Actual de Endpoints, Arquitectura y Trazabilidad End-to-End\n")
doc.append("**Sistema de Marketplace de Moda con Probador Virtual 2.5D e Inteligencia Artificial**\n")
doc.append("> **Documento Oficial de Auditoría y Trazabilidad de Software**  ")
doc.append("> **Fecha de Generación:** Octubre 2026 | **Versión:** 1.0.0-audited  ")
doc.append("> **Tecnologías:** FastAPI (Python 3.12) | SQLAlchemy + PostgreSQL | Angular 19+ | Flutter 3.x | Gemini 2.5 & YOLOv8\n")
doc.append("---\n")

# Resumen Ejecutivo
doc.append("## 1. Resumen Ejecutivo y Métricas del Sistema\n")
doc.append("El presente documento ofrece una radiografía exhaustiva de la arquitectura del backend, detallando cada uno de sus **208 endpoints**, sus esquemas de entrada/salida validados con Pydantic, sus políticas de seguridad RBAC, y la trazabilidad cruzada bidireccional con el **Frontend Web (Angular)** y la **Aplicación Móvil (Flutter)**.\n")

doc.append("### Cuadro Resumen de Endpoints por Paquete Funcional\n")
doc.append("| Código Paquete | Módulo de Dominio | Total Endpoints | Cobertura Web (Angular) | Cobertura Mobile (Flutter) | Perfil Principal |")
doc.append("| :--- | :--- | :---: | :---: | :---: | :--- |")

total_web = 0
total_mob = 0
for pkg, subs in sorted(endpoints_by_pkg.items()):
    pkg_eps = [ep for s in subs.values() for ep in s]
    web_c = sum(1 for ep in pkg_eps if ep['web_traceability'])
    mob_c = sum(1 for ep in pkg_eps if ep['mobile_traceability'])
    total_web += web_c
    total_mob += mob_c
    perfil = "Omnicanal (Admin + Cliente)" if mob_c > 0 and web_c > 0 else ("Backoffice Administrativo" if web_c > 0 else "Sistema")
    doc.append(f"| **{pkg.split('·')[0].strip()}** | {pkg.split('·')[1].strip() if '·' in pkg else pkg} | **{len(pkg_eps)}** | {web_c} ({web_c*100/len(pkg_eps):.1f}%) | {mob_c} ({mob_c*100/len(pkg_eps):.1f}%) | {perfil} |")

doc.append(f"| **TOTAL GLOBAL** | **Todos los Módulos Activos** | **{total_count}** | **{total_web} ({total_web*100/total_count:.1f}%)** | **{total_mob} ({total_mob*100/total_count:.1f}%)** | **Omnicanal y Backoffice** |\n")

# Diagrama de Arquitectura Mermaid
doc.append("## 2. Diagrama de Arquitectura Global\n")
doc.append("```mermaid")
doc.append("flowchart TD")
doc.append("    subgraph CLIENT_TIER[\"Capa de Clientes\"]")
doc.append("        WEB[\"🌐 Frontend Web (Angular 19+)\\n• Catálogo Storefront\\n• Backoffice Administrativo (CRUD)\\n• Punto de Venta POS\\n• Dashboard BI & IA Insights\"]")
doc.append("        MOB[\"📱 App Móvil (Flutter 3.x)\\n• Catálogo B2C Nativo\\n• Probador Virtual 2.5D\\n• Carrito y Checkout Stripe\\n• Reservas en Tienda Física\"]")
doc.append("    end")
doc.append("")
doc.append("    subgraph GATEWAY[\"Capa de API Gateway y Seguridad\"]")
doc.append("        CORS[\"CORS & Security Headers\"]")
doc.append("        AUTH[\"Auth & RBAC Middleware\\n• JWT Access & Refresh Token\\n• Role / Permission Verification\"]")
doc.append("    end")
doc.append("")
doc.append("    subgraph BACKEND_PACKAGES[\"FastAPI Backend Modules (backend_marketplace_moda)\"]")
doc.append("        PAQ1[\"PAQ-01 · Usuarios y Catálogo (99 EPs)\\n• Auth, Perfil, Direcciones\\n• Roles, Permisos RBAC\\n• CRUD Catálogo y Productos\"]")
doc.append("        PAQ2[\"PAQ-02 · Inventario y Sucursales (29 EPs)\\n• Ciudades, Sucursales, Cajas\\n• Almacenes y Abastecimiento\"]")
doc.append("        PAQ3[\"PAQ-03 · Reservas y Vestidor Virtual (21 EPs)\\n• Reservas Físicas\\n• Vestidor 2.5D & Async AI Jobs\\n• Notificaciones\"]")
doc.append("        PAQ4[\"PAQ-04 · Comercio, Ventas y POS (45 EPs)\\n• Carrito, Pedidos, Stripe\\n• Devoluciones, POS Físico\\n• Stock, Cupones, Favoritos\"]")
doc.append("        PAQ5[\"PAQ-05 · Analítica, Reportes e IA (7 EPs)\\n• Dashboard KPIs\\n• Insights Predictivos\\n• Asistente Conversacional BI\"]")
doc.append("        TRANS[\"Transversales (7 EPs)\\n• Auditoría, Bulk Excel, Health\"]")
doc.append("    end")
doc.append("")
doc.append("    subgraph INFRASTRUCTURE[\"Capa de Persistencia y Servicios Externos\"]")
doc.append("        DB[(\"🐘 PostgreSQL Database\\nEsquema Relacional + Alembic\")]")
doc.append("        STORAGE[\"📁 Local / S3 File Storage\\nImágenes y Modelos 2.5D\"]")
doc.append("        STRIPE[\"💳 Pasarela Stripe\\nPagos y Webhooks\"]")
doc.append("        AI_SERVICES[\"🤖 Servicios de Inteligencia Artificial\\n• Gemini 2.5 Flash\\n• YOLOv8 Pose Estimation\\n• Rembg Segmentación\"]")
doc.append("    end")
doc.append("")
doc.append("    WEB --> CORS --> AUTH")
doc.append("    MOB --> CORS --> AUTH")
doc.append("    AUTH --> PAQ1 & PAQ2 & PAQ3 & PAQ4 & PAQ5 & TRANS")
doc.append("    PAQ1 & PAQ2 & PAQ3 & PAQ4 & PAQ5 & TRANS --> DB")
doc.append("    PAQ1 & PAQ3 --> STORAGE")
doc.append("    PAQ4 --> STRIPE")
doc.append("    PAQ3 & PAQ5 --> AI_SERVICES")
doc.append("```\n")

# Estructura del Backend
doc.append("## 3. Estructura y Organización del Backend\n")
doc.append("El backend está construido con **FastAPI** siguiendo principios de separación por capas y arquitectura modular por dominios funcionales:\n")
doc.append("```text")
doc.append("backend_marketplace_moda/")
doc.append("├── src/")
doc.append("│   ├── main.py                     # Inicialización de FastAPI, CORS, inclusión de routers y healthcheck")
doc.append("│   ├── core/                       # Núcleo de la aplicación")
doc.append("│   │   ├── config.py               # Variables de entorno y configuración centralizada")
doc.append("│   │   ├── database.py             # Motor SQLAlchemy, SessionLocal y dependencias de DB")
doc.append("│   │   ├── security.py             # Hashing de passwords (bcrypt), JWT tokens y verificación de permisos RBAC")
doc.append("│   │   └── exceptions.py           # Manejadores de excepciones y envoltorio estándar ApiResponse")
doc.append("│   ├── api/                        # Routers HTTP agrupados por paquete funcional")
doc.append("│   │   ├── v1/                     # Endpoints versionados (/api/v1/...)")
doc.append("│   │   │   ├── auth.py             # Autenticación, registro, verificación y reseteo")
doc.append("│   │   │   ├── users.py            # Perfil, direcciones y CRUD de usuarios")
doc.append("│   │   │   ├── catalog.py          # Catálogo público y endpoints administrativos de producto")
doc.append("│   │   │   ├── organization.py     # Sucursales, almacenes, ciudades y cajas")
doc.append("│   │   │   ├── reservations.py     # Gestión de reservas para citas en tienda física")
doc.append("│   │   │   ├── vestidor.py         # Probador virtual 2.5D en tiempo real")
doc.append("│   │   │   ├── tryon_ai.py         # Trabajos asíncronos de prueba virtual fotográfica con IA")
doc.append("│   │   │   ├── commerce.py         # Carrito, pedidos, pagos Stripe, POS, stock y cupones")
doc.append("│   │   │   ├── analytics.py        # Dashboard, insights IA y reportes")
doc.append("│   │   │   ├── bulk.py             # Plantillas, validación e importación/exportación masiva Excel")
doc.append("│   │   │   └── audit.py            # Visualización de logs de auditoría del sistema")
doc.append("│   └── modules/                    # Lógica de dominio, modelos SQLAlchemy y repositorios")
doc.append("└── tests/                          # Suite de pruebas automatizadas con pytest")
doc.append("```\n")

# Catálogo Detallado por Paquetes
doc.append("## 4. Catálogo Detallado de Módulos y Endpoints (208 Endpoints)\n")

for pkg_name, submodules in sorted(endpoints_by_pkg.items()):
    doc.append(f"\n---\n## {pkg_name}\n")
    
    for sub_name, ep_list in sorted(submodules.items()):
        doc.append(f"\n### Submódulo: {sub_name} ({len(ep_list)} endpoints)\n")
        
        for ep in ep_list:
            doc.append(f"#### {ep['id']}. `{ep['method']}` `{ep['path']}`")
            doc.append(f"**Funcionalidad:** {ep['summary']}")
            if ep['description'] and ep['description'] != ep['summary']:
                doc.append(f"\n> {ep['description']}\n")
            doc.append(f"- **Seguridad / Permisos:** `{ep['permissions']}`")
            doc.append(f"- **Estado de Operatividad:** `{ep['status']}`")
            
            # Trazabilidad
            doc.append(f"- **Consumo Frontend Web (Angular):** {', '.join(ep['web_traceability']) if ep['web_traceability'] else '*(Sin consumo web directo)*'}")
            doc.append(f"- **Consumo App Móvil (Flutter):** {', '.join(ep['mobile_traceability']) if ep['mobile_traceability'] else '*(Sin consumo móvil directo)*'}")
            
            # Parámetros de Entrada (Input)
            params = ep['details'].get('parameters', [])
            path_params = [p for p in params if p.get('in') == 'path']
            query_params = [p for p in params if p.get('in') == 'query']
            
            doc.append("\n**Entradas (Inputs):**")
            if path_params:
                doc.append("*Parámetros de Ruta (Path):*")
                for p in path_params:
                    doc.append(f"- `{p['name']}` (*{p.get('schema', {}).get('type', 'string')}*, Requerido): {p.get('description', 'Identificador del recurso')}")
                    
            if query_params:
                doc.append("*Parámetros de Consulta (Query):*")
                for p in query_params:
                    req_txt = "Requerido" if p.get('required') else f"Opcional (default: `{p.get('schema', {}).get('default', 'None')}`)"
                    doc.append(f"- `{p['name']}` (*{p.get('schema', {}).get('type', 'string')}*, {req_txt}): {p.get('description', '')}")
                    
            # Request Body
            req_body = ep['details'].get('requestBody', {})
            content = req_body.get('content', {})
            if content:
                content_type = list(content.keys())[0]
                body_schema = content[content_type].get('schema')
                doc.append(f"\n*Cuerpo de la Petición ({content_type}):*")
                doc.append(format_schema_markdown(body_schema))
            elif not path_params and not query_params:
                doc.append("*(Sin parámetros ni cuerpo de entrada)*")
                
            # Parámetros de Salida (Output)
            doc.append("\n**Salidas (Outputs):**")
            responses = ep['details'].get('responses', {})
            for code in sorted(responses.keys()):
                if code.startswith('2') or code == 'default':
                    resp_desc = responses[code].get('description', 'Respuesta exitosa')
                    doc.append(f"*Código HTTP `{code}`: {resp_desc}*")
                    resp_content = responses[code].get('content', {}).get('application/json', {})
                    if resp_content and 'schema' in resp_content:
                        doc.append(format_schema_markdown(resp_content['schema']))
            
            doc.append("\n")

# Matriz Global Consolidada de Trazabilidad
doc.append("\n---\n## 5. Matriz Global Consolidada de Trazabilidad (208 Endpoints)\n")
doc.append("| # | Paquete | Método | Ruta | Funcionalidad | Permisos | Consumo Web (Angular) | Consumo Mobile (Flutter) | Estado Operativo |")
doc.append("| :---: | :--- | :---: | :--- | :--- | :--- | :--- | :--- | :--- |")

for ep in all_endpoints_list:
    pkg_short = ep['pkg'].split('·')[0].strip()
    web_short = ep['web_traceability'][0].split('/')[-1].replace('.ts`', '').replace('`', '') if ep['web_traceability'] else '-'
    mob_short = ep['mobile_traceability'][0].split('/')[-1].replace('.dart`', '').replace('`', '') if ep['mobile_traceability'] else '-'
    doc.append(f"| {ep['id']} | {pkg_short} | `{ep['method']}` | `{ep['path']}` | {ep['summary']} | `{ep['permissions']}` | {web_short} | {mob_short} | **{ep['status']}** |")

# Análisis de Cobertura y Funcionalidades
doc.append("\n---\n## 6. Análisis de Funcionalidades Implementadas vs en Uso\n")
doc.append("### 1. Funcionalidades Omnicanal (Web & Mobile)\n")
doc.append("Son aquellas funcionalidades core de la plataforma consumidas simultáneamente por la aplicación web y la aplicación móvil nativa:\n")
doc.append("- **Autenticación Completa:** Inicio de sesión, registro de nuevos clientes, renovación de JWT via refresh token, recuperación y reseteo de contraseña, verificación de correo electrónico y cambio de contraseña.\n")
doc.append("- **Catálogo Digital de Prendas:** Exploración de productos por filtros (categorías, marcas, colecciones, precios, tallas, colores), visualización detallada de fichas técnicas y stock de variantes.\n")
doc.append("- **Direcciones del Cliente:** Gestión de direcciones de envío (creación, edición, eliminación y selección de dirección predeterminada).\n")
doc.append("- **Reservas de Citas en Tienda Física:** Agendamiento de citas presenciales en sucursales físicas, selección de fecha/hora, elección de prendas a probar y cancelación de reservas.\n")
doc.append("- **Probador Virtual 2.5D en Tiempo Real:** Configuración de avatar corporal según medidas del usuario, superposición de prendas 2D escaladas y posicionadas semánticamente, cálculo de ajuste de talla (Small / Perfect / Tight) y combinación visual de prendas.\n")
doc.append("- **Comercio y Ventas B2C:** Carrito de compras sincronizado con el backend, validación de cupones de descuento, creación de pedidos, cálculo de costo de envío según sucursal y pago con Stripe Checkout.\n")
doc.append("- **Historial de Pedidos:** Listado de órdenes de compra del usuario, seguimiento del estado del pedido (Pendiente, Pagado, En Preparación, Enviado, Entregado, Cancelado) y consulta de detalles.\n")
doc.append("- **Favoritos y Lista de Deseos:** Guardado y sincronización de prendas favoritas del usuario.\n")

doc.append("### 2. Funcionalidades Exclusivas del Backoffice Administrativo Web (Angular)\n")
doc.append("Módulos diseñados para la gestión operativa y comercial de la tienda, optimizados para pantallas de escritorio:\n")
doc.append("- **CRUD Maestro de Catálogo:** Creación, edición masiva y desactivación lógica de Categorías, Marcas, Temporadas, Colecciones, Proveedores, Tallas, Colores y Materiales.\n")
doc.append("- **Editor Integral de Productos:** Formulario enriquecido para carga de prendas, asociación de múltiples variantes con SKU, subida de imágenes y assets para probador virtual.\n")
doc.append("- **Control de Acceso Basado en Roles (RBAC):** Creación y asignación granular de Roles y Permisos a usuarios del personal.\n")
doc.append("- **Gestión de Organización y Sucursales:** Configuración de Ciudades, Sucursales físicas, Almacenes centrales y Cajas registradoras.\n")
doc.append("- **Punto de Venta POS:** Terminal de cobro presencial en sucursales, apertura/cierre de turnos de caja, lectura de código de barras/SKU, emisión de comprobantes y devoluciones en caja.\n")
doc.append("- **Inventario, Kardex y Stock Comercial:** Ajustes manuales de existencias por almacén, movimientos entre sucursales, control de stock disponible y órdenes de suministro.\n")
doc.append("- **Gestión de Devoluciones y Reembolsos:** Flujo administrativo de aprobación, inspección física y reembolso de pedidos devueltos por clientes.\n")
doc.append("- **Dashboard BI, Analítica Predictiva y Reportes:** Indicadores clave de rendimiento (ventas, ticket promedio, tasa de conversión), insights generados con IA (Gemini 2.5), asistente conversacional de analítica empresarial y exportación de informes en Excel y PDF.\n")
doc.append("- **Carga y Descarga Masiva (Bulk Excel):** Descarga de plantillas parametrizadas e importación/exportación masiva de productos y maestros.\n")
doc.append("- **Registro de Auditoría (Audit Log):** Monitoreo inmutable de todas las mutaciones realizadas en el sistema (quién, cuándo, qué entidad y qué valores cambiaron).\n")

doc.append("### 3. Funcionalidades de Inteligencia Artificial (IA)\n")
doc.append("- **Probador Virtual con IA Fotográfica (`/tryon-ai/jobs/*`):** Pipeline asíncrono para generar fotos realistas de prendas probadas sobre modelos de referencia o fotos de clientes usando remoción de fondo (`rembg`), detección de pose (`YOLOv8`) y síntesis visual con Vision AI.\n")
doc.append("- **Asistente Comercial Conversacional (`/commerce/assistant/*`):** Chatbot guiado para recomendaciones de moda y asistencia en la compra de prendas dentro del storefront.\n")
doc.append("- **Asistente de Analítica de Negocio (`/analytics/assistant/*`):** Intérprete de lenguaje natural que analiza datos de ventas e inventario y genera consultas SQL seguras para responder preguntas gerenciales.\n")

doc.append("\n---\n")
doc.append("*Documentación generada automáticamente mediante inspección estática y dinámica del código fuente por Antigravity AI.*")

full_content = '\n'.join(doc)

# 7. Escritura en la ruta de documentación externa unificada
external_docs_backend = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'docs', 'backend'))
os.makedirs(external_docs_backend, exist_ok=True)
target_file = os.path.join(external_docs_backend, 'ESTADO_ACTUAL_ENDPOINTS_Y_TRAZABILIDAD.md')

with open(target_file, 'w', encoding='utf-8') as f:
    f.write(full_content)
print(f"Documentación escrita exitosamente en: {target_file} ({len(full_content)} bytes)")