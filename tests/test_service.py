from dataclasses import replace
import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from ocs_ai.app import create_app
from ocs_ai.config import Settings
from ocs_ai.quiz import Question, image_urls, parse_answer


@pytest.fixture
def settings(tmp_path):
    return Settings(api_key="secret-test-key", token="test-local-token", db_path=tmp_path / "quiz.sqlite3")


def upstream(answers=None, status=200, finish="stop"):
    calls = []
    def handle(request):
        calls.append(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer secret-test-key"
        return httpx.Response(status, json={"choices": [{"finish_reason": finish,
            "message": {"content": json.dumps({"answers": answers or ["B"], "reason": "依据"}),
                        "reasoning_content": "private reasoning must not be logged"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20}})
    return httpx.MockTransport(handle), calls


def search(client, **extra):
    return client.post("/api/search", headers={"Authorization": "Bearer test-local-token"},
                       json={"title": "1+1=?", "options": "1\n2\n3", "type": "single", **extra})


def test_contract_cache_and_env_only(settings):
    transport, calls = upstream()
    with TestClient(create_app(settings, transport)) as client:
        first = search(client).json()
        assert first["data"]["answers"] == ["2"]
        assert first["data"]["usage"]["completion_tokens"] == 20
        second = search(client).json()
        assert second["data"]["cached"] is True and second["data"]["usage"] == {}
        assert len(calls) == 1
        assert calls[0]["thinking"] == {"type": "enabled"}
        assert calls[0]["reasoning_effort"] == "low"
        assert calls[0]["model"] == "deepseek-flash"
        assert search(client, model="evil", apiKey="evil").json()["code"] == 1
        config = client.get("/ocs-config.json").json()[0]
        assert config["data"] == {"title": "${title}", "options": "${options}", "type": "${type}"}
        assert "secret-test-key" not in json.dumps(config)
        assert client.get("/api/logs").status_code == 401
        logs = client.get("/api/logs", headers=config["headers"]).text
        assert "secret-test-key" not in logs and "private reasoning" not in logs
        assert client.delete("/api/cache", headers=config["headers"]).json()["code"] == 0
        assert search(client).json()["data"]["cached"] is False
        assert len(calls) == 2


def test_vision_keeps_image_and_disabled_fails(settings):
    transport, calls = upstream()
    with TestClient(create_app(settings, transport)) as client:
        assert search(client, title='<img src="https://example.com/image.png?a=1&amp;b=2">').json()["code"] == 0
        content = calls[0]["messages"][1]["content"]
        assert content[1]["image_url"]["url"] == "https://example.com/image.png?a=1&b=2"
    with TestClient(create_app(replace(settings, vision=False), transport)) as client:
        result = search(client, title="https://example.com/other.png").json()
        assert result["code"] == 1 and "图片" in result["msg"]
        assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 429, 500])
def test_upstream_error_not_cached_or_retried(settings, status):
    transport, calls = upstream(status=status)
    with TestClient(create_app(settings, transport)) as client:
        assert search(client).json()["code"] == 1
        assert search(client).json()["code"] == 1
        assert len(calls) == 2


def test_auth_cors_and_host(settings):
    transport, calls = upstream()
    with TestClient(create_app(settings, transport)) as client:
        assert client.post("/api/search", json={"title":"x"}).status_code == 401
        result = client.options("/api/search", headers={"Origin":"https://course.example","Access-Control-Request-Method":"POST"})
        assert result.headers["Access-Control-Allow-Private-Network"] == "true"
        assert "access-control-allow-origin" not in client.get("/ocs-config.json", headers={"Origin":"https://evil.example"}).headers
        assert client.get("/ocs-config.json", headers={"Host":"evil.example"}).status_code == 400
        assert not calls


def test_disabled_thinking(settings):
    transport, calls = upstream()
    with TestClient(create_app(replace(settings, thinking="disabled"), transport)) as client:
        assert search(client).json()["code"] == 0
        assert calls[0]["thinking"] == {"type":"disabled"}
        assert "reasoning_effort" not in calls[0]


def test_truncated_output_rejected(settings):
    transport, _ = upstream(finish="length")
    with TestClient(create_app(settings, transport)) as client:
        assert search(client).json()["code"] == 1


def test_timeout(settings):
    def fail(request):
        raise httpx.ReadTimeout("secret-test-key", request=request)
    with TestClient(create_app(settings, httpx.MockTransport(fail))) as client:
        result = search(client).json()
        assert result["code"] == 1 and "超时" in result["msg"]


def test_cache_expiry(settings):
    transport, calls = upstream()
    with TestClient(create_app(replace(settings, cache_ttl=1), transport)) as client:
        search(client)
        import sqlite3
        with sqlite3.connect(settings.db_path) as db:
            db.execute("UPDATE cache SET created=?", (time.time()-2,))
        assert search(client).json()["data"]["cached"] is False
        assert len(calls) == 2


def test_fill_in_repetition_and_punctuation():
    q = Question(title="两个空", type="completion")
    assert parse_answer('{"answers":["a,b", "a,b"]}', q)[0] == ["a,b", "a,b"]


@pytest.mark.parametrize("raw", ['plain text', '{"answers":["Z"]}', '{"answers":["A","B"]}', '{"answers":[2]}', '{"answers":[]}'])
def test_invalid_answers(raw):
    with pytest.raises(ValueError):
        parse_answer(raw, Question(title="题", options="甲\n乙", type="single"))


def test_image_order_and_deduplication():
    q = Question(title="![x](https://example.com/a.png) https://example.com/a.png", images=["data:image/png;base64,YQ=="])
    assert image_urls(q) == ["data:image/png;base64,YQ==", "https://example.com/a.png"]


def test_missing_key_and_empty_question(settings):
    transport, calls = upstream()
    with TestClient(create_app(replace(settings, api_key=""), transport)) as client:
        assert client.get("/api/health").json()["configured"] is False
        assert "LLM_API_KEY" in search(client).json()["msg"]
        assert search(client, title=" ").json()["code"] == 1
        assert not calls


@pytest.mark.parametrize("answers,question_type,options,expected", [
    (["A", "C"], "multiple", "甲\n乙\n丙", ["甲", "丙"]),
    (["B"], "judgement", "正确\n错误", ["错误"]),
    (["同一答案", "同一答案"], "completion", "", ["同一答案", "同一答案"]),
])
def test_question_types(settings, answers, question_type, options, expected):
    transport, _ = upstream(answers)
    with TestClient(create_app(settings, transport)) as client:
        assert search(client, type=question_type, options=options).json()["data"]["answers"] == expected


def test_total_deadline(settings):
    async def slow(request):
        await asyncio.sleep(0.1)
        return httpx.Response(200)
    with TestClient(create_app(replace(settings, timeout=0.01), httpx.MockTransport(slow))) as client:
        result = search(client).json()
        assert result["code"] == 1 and "超时" in result["msg"]
