import json

from click.testing import CliRunner

from engram.cli import _format_tail_fact, _tail_once, main


def test_format_tail_fact_includes_confidence():
    fact = {
        "agent_id": "agent/josh",
        "scope": "payments",
        "content": "The Stripe webhook timeout is 30s.",
        "confidence": 0.95,
    }

    out = _format_tail_fact(fact)

    assert out == "[agent/josh] [payments] The Stripe webhook timeout is 30s. (confidence: 0.95)"


def test_format_tail_fact_without_confidence():
    fact = {
        "agent_id": "agent/josh",
        "scope": "payments",
        "content": "The Stripe webhook timeout is 30s.",
    }

    out = _format_tail_fact(fact)

    assert out == "[agent/josh] [payments] The Stripe webhook timeout is 30s."


def test_tail_once_fetches_facts(monkeypatch):
    payload = {
        "facts": [
            {
                "agent_id": "agent/josh",
                "scope": "payments",
                "content": "The Stripe webhook timeout is 30s.",
                "confidence": 0.95,
                "committed_at": "2026-04-09T10:00:00+00:00",
            }
        ],
        "count": 1,
        "latest_timestamp": "2026-04-09T10:00:00+00:00",
    }

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(payload).encode("utf-8")

    def fake_urlopen(url, timeout=30):
        assert "/api/tail?" in url
        assert "after=2026-04-09T09%3A00%3A00%2B00%3A00" in url
        assert "scope=payments" in url
        assert "limit=5" in url
        return DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    import asyncio

    facts, latest = asyncio.run(
        _tail_once(
            base_url="http://127.0.0.1:7474",
            after="2026-04-09T09:00:00+00:00",
            scope="payments",
            limit=5,
        )
    )

    assert len(facts) == 1
    assert facts[0]["scope"] == "payments"
    assert latest == "2026-04-09T10:00:00+00:00"


def test_tail_command_prints_fact_and_stops(monkeypatch):
    calls = {"count": 0}

    async def fake_tail_once(base_url, after, scope, limit):
        return (
            [
                {
                    "agent_id": "agent/josh",
                    "scope": "payments",
                    "content": "The Stripe webhook timeout is 30s.",
                    "confidence": 0.95,
                    "committed_at": "2026-04-09T10:00:00+00:00",
                }
            ],
            "2026-04-09T10:00:00+00:00",
        )

    def fake_sleep(interval):
        calls["count"] += 1
        raise KeyboardInterrupt()

    monkeypatch.setattr("engram.cli._tail_once", fake_tail_once)
    monkeypatch.setattr("time.sleep", fake_sleep)

    runner = CliRunner()
    result = runner.invoke(main, ["tail", "--scope", "payments", "--limit", "5"])

    assert result.exit_code == 0
    assert "Starting tail stream. Press Ctrl+C to stop." in result.output
    assert (
        "[agent/josh] [payments] The Stripe webhook timeout is 30s. (confidence: 0.95)"
        in result.output
    )
    assert "Stopped." in result.output
