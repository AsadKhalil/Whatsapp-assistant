import json

import httpx

from app.config import Settings
from app.llm import LLM
from app.tools import TOOL_SPECS


def completion(content=None, tool_calls=None) -> dict:
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"id": "c1", "object": "chat.completion", "created": 0, "model": "m",
            "choices": [{"index": 0, "finish_reason": "tool_calls" if tool_calls else "stop", "message": message}]}


def make_llm(handler, **settings) -> LLM:
    s = Settings(**{"llm_api_key": "k", "llm_model": "test-model", **settings})
    return LLM(s, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_openai_default_sends_tools_with_reasoning_off():
    bodies, urls = [], []

    def handler(request):
        urls.append(str(request.url))
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion("Hello!"))

    reply = make_llm(handler).complete([{"role": "user", "content": "hi"}], TOOL_SPECS)
    assert reply.text == "Hello!" and reply.tool_calls == []
    assert urls == ["https://api.openai.com/v1/chat/completions"]
    assert bodies[0]["model"] == "test-model" and bodies[0]["reasoning_effort"] == "none"
    names = {t["function"]["name"] for t in bodies[0]["tools"]}
    assert names == {"lookup_rows", "total_rows", "propose_row", "handoff"}
    for banned in ("tool_choice", "parallel_tool_calls", "temperature", "max_tokens", "stream"):
        assert banned not in bodies[0]


def test_other_providers_get_no_reasoning_effort_unless_set():
    bodies = []

    def handler(request):
        bodies.append((str(request.url), json.loads(request.content)))
        return httpx.Response(200, json=completion("ok"))

    make_llm(handler, llm_base_url="https://ollama.com/v1").complete([{"role": "user", "content": "hi"}], TOOL_SPECS)
    make_llm(handler, llm_base_url="https://ollama.com/v1", llm_reasoning_effort="low").complete(
        [{"role": "user", "content": "hi"}], TOOL_SPECS)
    assert bodies[0][0] == "https://ollama.com/v1/chat/completions" and "reasoning_effort" not in bodies[0][1]
    assert bodies[1][1]["reasoning_effort"] == "low"


def test_tool_calls_are_parsed_and_bad_arguments_become_empty():
    def handler(request):
        return httpx.Response(200, json=completion(tool_calls=[
            {"id": "call_1", "type": "function",
             "function": {"name": "lookup_rows", "arguments": '{"tab": "Prices", "query": "cake"}'}},
            {"id": "call_2", "type": "function", "function": {"name": "handoff", "arguments": "not json"}},
        ]))

    reply = make_llm(handler).complete([{"role": "user", "content": "price?"}], TOOL_SPECS)
    assert [(c.id, c.name, c.arguments) for c in reply.tool_calls] == [
        ("call_1", "lookup_rows", {"tab": "Prices", "query": "cake"}), ("call_2", "handoff", {})]


def test_assistant_message_goes_back_with_provider_extras():
    # Gemini 3 attaches a thought signature to each tool call and rejects history without it.
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion(tool_calls=[{
            "id": "call_1", "type": "function",
            "function": {"name": "lookup_rows", "arguments": '{"tab": "Prices", "query": ""}'},
            "extra_content": {"google": {"thought_signature": "sig-123"}}}]))

    llm = make_llm(handler, llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
    first = llm.complete([{"role": "user", "content": "hi"}], TOOL_SPECS)
    llm.complete([{"role": "user", "content": "hi"}, first.message,
                  {"role": "tool", "tool_call_id": "call_1", "content": "{}"}], TOOL_SPECS)
    sent = bodies[1]["messages"][1]
    assert sent["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "sig-123"}}


def test_transcription_uploads_an_ogg_file_to_the_stt_endpoint():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"text": " how much is the cake "})

    llm = make_llm(handler, stt_base_url="https://stt.example/v1", stt_model="gpt-transcribe")
    assert llm.transcribe(b"OggS-bytes") == "how much is the cake"
    request = seen[0]
    assert str(request.url) == "https://stt.example/v1/audio/transcriptions"
    assert b'filename="voice.ogg"' in request.content and b"OggS-bytes" in request.content
    assert b"gpt-transcribe" in request.content
