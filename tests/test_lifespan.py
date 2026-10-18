from fastapi.testclient import TestClient

import nova.main as main
from nova.config import settings


def test_lifespan_initializes_services_and_stops_workers(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "api_token_file", tmp_path / "data" / "api.token")
    monkeypatch.setattr(settings, "workspace", tmp_path / "workspace")
    monkeypatch.setattr(settings, "database_path", tmp_path / "nova.sqlite3")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.jsonl")

    calls = []
    monkeypatch.setattr(main, "initialize_knowledge", lambda: calls.append("knowledge"))
    monkeypatch.setattr(main, "initialize_scheduler_config", lambda: calls.append("scheduler_config"))
    monkeypatch.setattr(main, "start_worker", lambda: calls.append("scheduler_start"))
    monkeypatch.setattr(main, "start_update_worker", lambda: calls.append("updater_start"))
    monkeypatch.setattr(main, "stop_worker", lambda: calls.append("scheduler_stop"))
    monkeypatch.setattr(main, "stop_update_worker", lambda: calls.append("updater_stop"))
    monkeypatch.setattr("nova.autonomy.recover_interrupted_runs", lambda: calls.append("autonomy_recovery"))
    monkeypatch.setattr("nova.self_improvement.recover_interrupted_skill_runs", lambda: calls.append("skill_recovery"))
    monkeypatch.setattr(main, "recover_interrupted_workflow_runs", lambda: calls.append("workflow_recovery"))

    with TestClient(main.app):
        assert settings.api_token_file.is_file()
        assert settings.workspace.is_dir()
        assert settings.api_token_file.stat().st_mode & 0o777 == 0o600
        assert calls == [
            "autonomy_recovery",
            "skill_recovery",
            "workflow_recovery",
            "knowledge",
            "scheduler_config",
            "scheduler_start",
            "updater_start",
        ]

    assert calls[-2:] == ["scheduler_stop", "updater_stop"]
