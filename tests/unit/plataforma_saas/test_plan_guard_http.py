from sqlalchemy import select
from src.plataforma_saas.infrastructure.models.subscription import SubscriptionModel

def test_basico_bloquea_ia_profesional_supera_guard(world):
    from src.roles.infrastructure.persistence.models.permission import PermissionModel
    world.admin_role.permissions.append(PermissionModel(code='dashboard.read', name='Reportes', module='dashboard'))
    world.db.commit()
    for route in ('interpret', 'explain', 'execute'):
        path = '/api/v1/analytics/assistant/' + route
        blocked = world.client.post(path, headers=world.headers(world.admins[0]), json={})
        assert blocked.status_code == 403 and blocked.json()['error']['code'] == 'feature_not_in_plan'
        # Cuerpo vacío debe fallar validación, después de superar la dependencia.
        allowed = world.client.post(path, headers=world.headers(world.admins[1]), json={})
        assert allowed.status_code == 422, allowed.text

def test_suspension_bloquea_altas_permite_consulta_y_desactivar(world):
    sub = world.db.scalar(select(SubscriptionModel).where(SubscriptionModel.tenant_id == world.tenants[0].id))
    sub.status = 'SUSPENDIDA'
    world.db.commit()
    headers = world.headers(world.admins[0])
    for route in ('/commerce/admin/pos/sales', '/reservations'):
        r = world.client.post('/api/v1'+route, headers=headers, json={})
        assert r.status_code == 403 and r.json()['error']['code'] == 'subscription_inactive'
    assert world.client.get('/api/v1/reservations', headers=headers).status_code == 200
    r = world.client.post(f'/api/v1/organization/branches/{world.branches[0].id}/deactivate', headers=headers)
    assert r.status_code == 200, r.text
