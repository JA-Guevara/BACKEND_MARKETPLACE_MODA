import os
from unittest.mock import patch
from sqlalchemy import select

from src.plataforma_saas.application.jobs.runner import TareasProgramadas, _active_in_process_locks, _lock_mutex
from src.plataforma_saas.infrastructure.models.ops import JobRunModel


def test_token_invalido_retorna_401(world):
    """Prueba obligatoria: Token inválido -> 401."""
    # Sin cabecera
    resp = world.client.post("/api/v1/platform/ops/jobs/tick")
    assert resp.status_code == 401

    # Con Bearer inválido
    resp_bad = world.client.post(
        "/api/v1/platform/ops/jobs/tick",
        headers={"Authorization": "Bearer token_falso_12345"},
    )
    assert resp_bad.status_code == 401


def test_jwt_super_admin_no_sirve(world):
    """Prueba obligatoria: JWT de super admin no sirve para tick de jobs."""
    platform_headers = world.headers(world.platform)
    resp = world.client.post("/api/v1/platform/ops/jobs/tick", headers=platform_headers)
    assert resp.status_code == 401
    assert "token de servicio" in resp.json()["error"]["message"].lower()


def test_dos_ticks_simultaneos_uno_se_salta_por_candado(world):
    """Prueba obligatoria: Dos ticks simultáneos: uno se salta por el candado."""
    # Simular que otra instancia ya tiene el candado de subscriptions.lifecycle
    job_name = "subscriptions.lifecycle"
    with _lock_mutex:
        _active_in_process_locks.add(job_name)

    try:
        runner = TareasProgramadas(world.db)
        runs = runner.tick()
        sub_run = next(r for r in runs if r.job == job_name)
        assert sub_run.status == "skipped"
        assert "lock_held" in sub_run.changes.get("reason", "")
    finally:
        with _lock_mutex:
            _active_in_process_locks.discard(job_name)


def test_tick_produce_job_runs_sin_datos_personales(world):
    """Prueba obligatoria: Un tick produce job_runs sin datos personales (RNF10)."""
    jobs_token = "secret_jobs_token_test_123456"

    with patch.dict(os.environ, {"JOBS_TOKEN": jobs_token}):
        resp = world.client.post(
            "/api/v1/platform/ops/jobs/tick",
            headers={"Authorization": f"Bearer {jobs_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert len(data) >= 3

        # Verificar en base de datos
        db_runs = world.db.scalars(select(JobRunModel)).all()
        assert len(db_runs) >= 3

        # RNF10: Ningún campo de cambios debe contener nombres, correos o datos personales
        forbidden_keys = {"email", "first_name", "last_name", "password", "customer", "phone"}
        for run in db_runs:
            if run.changes:
                for k, v in run.changes.items():
                    assert k.lower() not in forbidden_keys
                    if isinstance(v, str):
                        assert "@" not in v
