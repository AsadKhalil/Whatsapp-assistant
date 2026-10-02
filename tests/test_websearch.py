import json

import httpx
import pytest

from app.config import Settings
from app.websearch import MAX_ANSWER, NOTE, WebSearch

GEMINI = "https://generativelanguage.googleapis.com/v1beta/openai/"


def make_search(handler, **settings) -> WebSearch:
    s = Settings(**{"llm_api_key": "k", "llm_model": "test-model", **settings})
    return WebSearch(s, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def openai_response(text: str, citations: list[dict]) -> dict:
    annotations = [{"type": "url_citation", "start_index": 0, "end_index": 1, **c} for c in citations]
    return {"id": "resp_1", "object": "response", "created_at": 0, "model": "m", "status": "completed",
            "output": [{"type": "web_search_call", "id": "ws_1", "status": "completed"},
                       {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": annotations}]}]}


def test_openai_uses_the_responses_web_search_tool():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json=openai_response(
            "PIA's helpline is 111-786-786.", [{"title": "PIA", "url": "https://www.piac.com.pk/contact"}]))

    result = make_search(handler).search("PIA helpline number")
    url, auth, body = seen[0]
    assert url == "https://api.openai.com/v1/responses" and auth == "Bearer k"
    assert body["model"] == "test-model" and body["tools"] == [{"type": "web_search"}]
    assert "PIA helpline number" in body["input"]
    assert result == {"note": NOTE, "answer": "PIA's helpline is 111-786-786.",
                      "sources": [{"title": "PIA", "url": "https://www.piac.com.pk/contact"}]}


def test_gemini_uses_google_search_grounding_on_the_native_api():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["x-goog-api-key"], json.loads(request.content)))
        return httpx.Response(200, json={"candidates": [{
            "content": {"parts": [{"text": "Eid holidays are "}, {"text": "31 March to 2 April."}]},
            "groundingMetadata": {"groundingChunks": [
                {"web": {"uri": "https://vertexaisearch.cloud.google.com/x", "title": "dawn.com"}}]}}]})

    result = make_search(handler, llm_base_url=GEMINI, llm_model="models/gemini-test").search("Eid holidays 2027")
    url, key, body = seen[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent"
    assert key == "k" and body["tools"] == [{"google_search": {}}]
    assert "Eid holidays 2027" in body["contents"][0]["parts"][0]["text"]
    assert result["answer"] == "Eid holidays are 31 March to 2 April."
    assert result["sources"] == [{"title": "dawn.com", "url": "https://vertexaisearch.cloud.google.com/x"}]


def test_ollama_uses_its_web_search_endpoint():
    seen = []

    def handler(request):
        seen.append((str(request.url), request.headers["authorization"], json.loads(request.content)))
        return httpx.Response(200, json={"results": [
            {"title": "TCS", "url": "https://tcs.com.pk", "content": "Call 111-123-456."},
            {"title": "Leopards", "url": "https://leopardscourier.com", "content": "Helpline 111-300-786."}]})

    result = make_search(handler, llm_base_url="https://ollama.com/v1").search("courier helpline")
    url, auth, body = seen[0]
    assert url == "https://ollama.com/api/web_search" and auth == "Bearer k"
    assert body == {"query": "courier helpline", "max_results": 3}
    assert "TCS: Call 111-123-456." in result["answer"] and "Leopards: Helpline 111-300-786." in result["answer"]
    assert [s["url"] for s in result["sources"]] == ["https://tcs.com.pk", "https://leopardscourier.com"]


def test_long_answers_are_cut_and_sources_capped():
    many = [{"title": f"S{i}", "url": f"https://s{i}.example"} for i in range(8)]
    search = make_search(lambda request: httpx.Response(200, json=openai_response("x" * 9000, many)))
    result = search.search("anything")
    assert len(result["answer"]) == MAX_ANSWER and len(result["sources"]) == 5


def test_duplicate_sources_are_listed_once():
    twice = [{"title": "PIA", "url": "https://pia.example"}] * 2
    search = make_search(lambda request: httpx.Response(200, json=openai_response("ok", twice)))
    assert search.search("q")["sources"] == [{"title": "PIA", "url": "https://pia.example"}]


@pytest.mark.parametrize("base_url", ["", GEMINI, "https://ollama.com/v1"])
def test_provider_failures_become_an_error_result(base_url):
    search = make_search(lambda request: httpx.Response(500, json={"error": "down"}), llm_base_url=base_url)
    assert search.search("q") == {"error": "Web search isn't available right now."}


def test_availability_follows_the_provider_and_key():
    def handler(request):
        raise AssertionError("no call expected")

    assert make_search(handler).available
    assert make_search(handler, llm_base_url=GEMINI).available
    assert make_search(handler, llm_base_url="https://ollama.com/v1").available
    assert not make_search(handler, llm_base_url="https://my-proxy.example/v1").available
    assert not make_search(handler, llm_api_key="").available
    assert make_search(handler, llm_base_url="https://my-proxy.example/v1").search("q") == {
        "error": "Web search isn't available with this AI provider."}
