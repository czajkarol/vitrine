"""Request ids and the no-secrets rule for logs.

The redaction test here is the one that matters: it asserts a property of every log line
this app will ever emit, including ones nobody has written yet.
"""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import (
    REQUEST_ID_HEADER,
    JsonFormatter,
    RequestIdFilter,
    configure,
    set_request_id,
)
from app.core.redaction import redact_secrets
from app.main import create_app

KEY = "sk-ant-api03-000000000000wxyz"


@pytest.fixture
def client(settings: Settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def record(message: str, *args: object) -> logging.LogRecord:
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, args, None)


class TestSecretRedaction:
    def test_redacts_a_key_shaped_token(self):
        assert redact_secrets(f"401 for key {KEY}") == "401 for key …wxyz"

    def test_leaves_ordinary_words_alone(self):
        """A pattern that ate normal log text would make the logs worse and prove
        nothing. `risk-assessment-document` is the kind of thing a loose one eats."""
        text = "a risk-assessment-document and a sk-1 that is too short"
        assert redact_secrets(text) == text

    def test_catches_a_key_passed_as_a_log_argument(self):
        """Where a key would actually arrive: not in the format string, in the `%s`."""
        entry = record("provider said %s", f"401 for {KEY}")
        RequestIdFilter().filter(entry)
        assert KEY not in entry.getMessage()
        assert "…wxyz" in entry.getMessage()


class TestRequestId:
    def test_lines_logged_outside_a_request_get_a_dash(self):
        entry = record("starting up")
        RequestIdFilter().filter(entry)
        assert entry.request_id == "-"

    def test_lines_logged_during_a_request_carry_its_id(self):
        set_request_id("abcd1234")
        entry = record("something happened")
        RequestIdFilter().filter(entry)
        assert entry.request_id == "abcd1234"
        set_request_id("-")

    def test_every_response_carries_one(self, client):
        response = client.get("/api/health")
        assert response.headers[REQUEST_ID_HEADER]

    def test_two_requests_get_different_ids(self, client):
        first = client.get("/api/health").headers[REQUEST_ID_HEADER]
        second = client.get("/api/health").headers[REQUEST_ID_HEADER]
        assert first != second

    def test_an_inbound_id_is_honoured(self, client):
        """A proxy or a script may already have one, and two ids for the same request is
        worse than none."""
        response = client.get("/api/health", headers={REQUEST_ID_HEADER: "from-upstream"})
        assert response.headers[REQUEST_ID_HEADER] == "from-upstream"

    @pytest.mark.parametrize(
        "hostile",
        ["with spaces", "x" * 200, "line\nbreak", "semi;colon"],
    )
    def test_a_hostile_inbound_id_is_replaced_rather_than_echoed(self, client, hostile):
        response = client.get("/api/health", headers={REQUEST_ID_HEADER: hostile})
        assert response.headers[REQUEST_ID_HEADER] != hostile


class TestJsonFormat:
    def test_one_object_per_line_with_the_request_id_in_it(self):
        entry = record("something happened")
        RequestIdFilter().filter(entry)
        payload = json.loads(JsonFormatter().format(entry))
        assert payload["message"] == "something happened"
        assert payload["level"] == "INFO"
        assert payload["request_id"] == "-"

    def test_configuring_twice_does_not_double_every_line(self, capsys):
        """uvicorn installs a handler of its own, and so does anything that calls this
        again. Two handlers means every line twice."""
        configure("INFO")
        configure("INFO")
        logging.getLogger("test.doubling").info("once")
        assert capsys.readouterr().err.count("once") == 1
