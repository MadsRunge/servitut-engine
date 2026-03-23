from app.db.database import check_database_connection
from app.worker.celery_app import check_redis_connection


def build_health_payload() -> tuple[int, dict[str, object]]:
    services: dict[str, dict[str, str]] = {}
    checks = {
        "database": check_database_connection,
        "redis": check_redis_connection,
    }
    all_ok = True

    for name, checker in checks.items():
        ok, detail = checker()
        service_status = {"status": "ok" if ok else "error"}
        if detail:
            service_status["detail"] = detail
        services[name] = service_status
        all_ok = all_ok and ok

    return (
        200 if all_ok else 503,
        {
            "status": "ok" if all_ok else "degraded",
            "services": services,
        },
    )
