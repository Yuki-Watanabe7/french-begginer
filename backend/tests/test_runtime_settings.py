"""APP_ENV / APP_ALLOWED_HOSTS の解釈（Issue #219）。"""

import pytest

from app.runtime_settings import LOOPBACK_HOSTS, load_runtime_settings


def test_default_is_development_with_loopback_hosts():
    settings = load_runtime_settings({})
    assert settings.environment == "development"
    assert not settings.is_production
    assert settings.allowed_hosts == LOOPBACK_HOSTS


def test_production_hosts_are_normalized_and_keep_loopback():
    settings = load_runtime_settings(
        {
            "APP_ENV": " Production ",
            "APP_ALLOWED_HOSTS": " 192.168.1.20 , French-Host.local,,",
        }
    )
    assert settings.is_production
    assert settings.allowed_hosts == LOOPBACK_HOSTS | {
        "192.168.1.20",
        "french-host.local",
    }


def test_production_without_hosts_means_localhost_only():
    settings = load_runtime_settings({"APP_ENV": "production", "APP_ALLOWED_HOSTS": ""})
    assert settings.allowed_hosts == LOOPBACK_HOSTS


def test_unknown_environment_fails_closed():
    with pytest.raises(ValueError, match="APP_ENV"):
        load_runtime_settings({"APP_ENV": "prod"})


@pytest.mark.parametrize(
    "entry",
    ["*", "*.local", "192.168.1.20:8080", "http://192.168.1.20", "a b"],
)
def test_wildcards_ports_and_schemes_are_rejected(entry):
    with pytest.raises(ValueError, match="APP_ALLOWED_HOSTS"):
        load_runtime_settings({"APP_ENV": "production", "APP_ALLOWED_HOSTS": entry})
