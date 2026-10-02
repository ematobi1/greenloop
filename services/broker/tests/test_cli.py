from sqlalchemy.exc import OperationalError

from app import cli
from app.config import BrokerSettings


def test_main_refuses_without_a_database_url(monkeypatch, capsys):
    monkeypatch.setattr(cli, "get_settings", lambda: BrokerSettings(_env_file=None))
    monkeypatch.delenv("BROKER_DATABASE_URL", raising=False)
    assert cli.main(["list-service-tokens"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert "BROKER_DATABASE_URL is not set" in err


def test_main_hides_connection_details_when_the_database_is_down(monkeypatch, capsys):
    url = "postgresql+psycopg://greenloop_broker:synthetic-pass@127.0.0.1:1/none"
    monkeypatch.setenv("BROKER_DATABASE_URL", url)
    monkeypatch.setattr(cli, "get_settings", lambda: BrokerSettings(_env_file=None))

    def unreachable(argv, engine):
        raise OperationalError("connect", {}, Exception(f"could not connect to {url}"))

    monkeypatch.setattr(cli, "run", unreachable)
    assert cli.main(["list-service-tokens"]) == 1
    out, err = capsys.readouterr()
    assert out == ""
    assert err.strip() == "Error: could not reach the broker database."
