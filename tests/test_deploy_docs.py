import re
from pathlib import Path

from app.config import DEFAULT_DB_PATH
from scripts.build_provenance import render

ROOT = Path(__file__).resolve().parent.parent
LONG_DASHES = (chr(0x2014), chr(0x2013))


def _env_example_keys() -> set[str]:
    text = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")
    return set(re.findall(r"^([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


def test_env_example_lists_every_variable_config_reads() -> None:
    source = (ROOT / "app/config.py").read_text(encoding="utf-8")
    read = set(re.findall(r"""(?:getenv|environ\.get)\(\s*["']([A-Z0-9_]+)["']""", source))
    read |= set(re.findall(r"""_boolean\(\s*["']([A-Z0-9_]+)["']""", source))
    assert read
    assert read == _env_example_keys()


def test_env_example_has_no_real_values() -> None:
    text = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")
    values = dict(re.findall(r"^([A-Z][A-Z0-9_]*)=(.*)$", text, flags=re.MULTILINE))
    safe_defaults = {
        "LLM_ENABLED": "false",
        "SEASON_EL_NINO": "false",
        "DB_PATH": "data/agrichat.db",
    }
    for name, value in values.items():
        assert value.strip("'") == safe_defaults.get(name, ""), name


def test_env_example_quotes_admin_hash_so_dollar_signs_survive() -> None:
    text = (ROOT / "deploy/.env.example").read_text(encoding="utf-8")
    assert re.search(r"^ADMIN_PASSWORD_HASH='[^']*'$", text, flags=re.MULTILINE)


def test_service_unit_is_local_hardened_and_restarts() -> None:
    unit = (ROOT / "deploy/agrichat.service").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in unit
    assert "EnvironmentFile=/etc/agrichat/agrichat.env" in unit
    assert "Restart=on-failure" in unit
    for option in ("NoNewPrivileges=true", "ProtectSystem=strict", "PrivateTmp=true"):
        assert option in unit
    assert re.search(r"^User=agrichat$", unit, flags=re.MULTILINE)


def test_caddyfile_proxies_to_local_app_with_security_headers() -> None:
    caddy = (ROOT / "deploy/Caddyfile").read_text(encoding="utf-8")
    assert "reverse_proxy 127.0.0.1:8000" in caddy
    assert "Strict-Transport-Security" in caddy
    assert 'X-Content-Type-Options "nosniff"' in caddy
    assert "Referrer-Policy" in caddy
    match = re.search(r'Content-Security-Policy "([^"]+)"', caddy)
    assert match
    policy = {
        part.split()[0]: part.split()[1:] for part in match.group(1).split(";") if part.strip()
    }
    assert policy["script-src"] == ["'self'"]
    assert policy["frame-ancestors"] == ["'none'"]
    assert policy["object-src"] == ["'none'"]
    assert "'unsafe-inline'" not in policy["script-src"]
    assert "'unsafe-inline'" not in policy["style-src"]


def test_service_writes_only_under_data_and_cache() -> None:
    unit = (ROOT / "deploy/agrichat.service").read_text(encoding="utf-8")
    assert "ReadWritePaths=/opt/agrichat/data" in unit
    db_path = Path("/opt/agrichat") / DEFAULT_DB_PATH
    assert db_path.is_relative_to("/opt/agrichat/data")
    assert "CacheDirectory=agrichat" in unit
    assert "Environment=HF_HOME=/var/cache/agrichat" in unit


def test_templates_have_no_inline_script_or_handlers() -> None:
    pattern = re.compile(r"<script(?![^>]*\bsrc=)|<style|\son[a-z]+=|javascript:")
    for path in (ROOT / "web/templates").rglob("*.html"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_license_is_apache_2() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Apache License" in text
    assert "Version 2.0, January 2004" in text
    assert "END OF TERMS AND CONDITIONS" in text


def test_provenance_matches_csv() -> None:
    assert (ROOT / "PROVENANCE.md").read_text(encoding="utf-8") == render()


def test_provenance_covers_every_file_in_csv() -> None:
    text = (ROOT / "PROVENANCE.md").read_text(encoding="utf-8")
    csv_text = (ROOT / "data/provenance.csv").read_text(encoding="utf-8")
    for path in re.findall(r"^[a-z0-9_]+,(data/[^,]+),", csv_text, flags=re.MULTILINE):
        assert f"`{path}`" in text


def test_readme_covers_required_sections() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    for heading in ("## Run locally", "## Run the pipeline", "## Run tests", "## Deploy"):
        assert heading in text


def test_ai_use_states_model_role_and_verification() -> None:
    text = (ROOT / "AI_USE.md").read_text(encoding="utf-8")
    for heading in ("## In the running system", "## In development", "## What people verified"):
        assert heading in text


def test_documents_use_plain_hyphens() -> None:
    for name in ("README.md", "AI_USE.md", "PROVENANCE.md", "LICENSE", "deploy/.env.example"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert not any(dash in text for dash in LONG_DASHES), name
