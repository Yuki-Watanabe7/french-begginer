"""家庭内本番の構成ファイルの契約（Issue #219）。

実機・別端末での到達性は runbook の手順で確かめる。ここでは、設定変更で
8000 / 5173 の公開、ソース mount、reload、開発 DB の混入が戻らないことを固定する。
"""

from pathlib import Path

import pytest

from app.ingestion.audio import MAX_AUDIO_BYTES

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load((ROOT / "compose.production.yml").read_text())


def _stage(dockerfile: Path, name: str) -> str:
    text = dockerfile.read_text()
    start = text.index(f" AS {name}\n")
    following = text.find("\nFROM ", start)
    return text[start:] if following == -1 else text[start:following]


def test_dedicated_project_and_no_dev_targets(compose):
    assert compose["name"] == "french-production"
    for service in compose["services"].values():
        assert service["build"]["target"] == "prod"


def test_only_nginx_entry_is_published(compose):
    services = compose["services"]
    assert "ports" not in services["backend"]
    assert services["web"]["ports"] == [
        "${FRENCH_BIND_ADDRESS:-127.0.0.1}:${FRENCH_HTTP_PORT:-8080}:8080"
    ]


def test_no_source_bind_mounts_and_dedicated_db_volume(compose):
    for service in compose["services"].values():
        for volume in service.get("volumes", []):
            assert not volume.startswith((".", "/")), volume
    backend = compose["services"]["backend"]
    assert "tutor-data:/var/lib/french-tutor" in backend["volumes"]
    assert compose["volumes"]["tutor-data"] == {
        "name": "${FRENCH_TUTOR_VOLUME:-french-production-tutor-data}",
        "external": True,
    }


def test_backend_runs_production_mode_with_fixed_db_location(compose):
    env = compose["services"]["backend"]["environment"]
    assert env["APP_ENV"] == "production"
    assert env["TUTOR_DATA_DIR"] == "/var/lib/french-tutor"
    assert env["TUTOR_DATABASE_URL"] == ""


def test_containers_are_hardened(compose):
    for service in compose["services"].values():
        assert service["read_only"] is True
        assert service["cap_drop"] == ["ALL"]
        assert service["restart"] == "unless-stopped"


def test_backend_prod_stage_is_non_root_single_worker_without_reload():
    stage = _stage(ROOT / "backend" / "Dockerfile", "prod")
    assert "--no-dev" in stage
    assert "USER tutor:tutor" in stage
    assert '"--workers", "1"' in stage
    assert "--reload" not in stage
    assert "COPY . ." not in stage


def test_frontend_prod_build_uses_same_origin_api():
    build = _stage(ROOT / "frontend" / "Dockerfile", "build")
    assert "ENV VITE_API_BASE=\n" in build
    assert "npm ci" in _stage(ROOT / "frontend" / "Dockerfile", "base")


def test_nginx_proxies_api_and_health_with_original_host():
    conf = (ROOT / "frontend" / "nginx" / "default.conf").read_text()
    # backend 再作成で IP が変わっても引き直す（URI なしの変数で /api のパスを保つ）
    assert "resolver 127.0.0.11" in conf
    assert "set $backend_upstream http://backend:8000;" in conf
    assert "location /api/ {\n        proxy_pass $backend_upstream;" in conf
    assert "location = /health {\n        proxy_pass $backend_upstream;" in conf
    assert conf.count("proxy_set_header Host $http_host;") == 2
    assert "try_files $uri $uri/ /index.html;" in conf


def test_nginx_body_limit_fits_audio_ingestion():
    conf = (ROOT / "frontend" / "nginx" / "default.conf").read_text()
    limit_mb = int(conf.split("client_max_body_size ")[1].split("m;")[0])
    assert limit_mb * 1024 * 1024 > MAX_AUDIO_BYTES


@pytest.mark.parametrize("context", ["backend", "frontend"])
def test_build_context_excludes_local_data_and_secrets(context):
    ignored = (ROOT / context / ".dockerignore").read_text().split()
    assert ".env" in ignored
    if context == "backend":
        assert {"data/", "*.db", ".cache/"} <= set(ignored)
    else:
        assert {"node_modules/", "dist/"} <= set(ignored)
