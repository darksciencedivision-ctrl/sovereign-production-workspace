"""Deterministic Ollama-compatible stub used only by the offline smoke tests."""

import asyncio
import json
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse


app = FastAPI()
MODELS = ["mock-alpha:latest", "mock-beta:latest"]
FAIL_TAGS = False
STREAM_MODE = "normal"
STREAM_CALLS = 0


@app.get("/api/tags")
async def tags():
    if FAIL_TAGS:
        return JSONResponse({"error": "simulated tags failure"}, status_code=503)
    return {"models": [{"name": name, "model": name, "size": 1_000_000} for name in MODELS]}


@app.post("/control/tags_failure/{enabled}")
async def tags_failure(enabled: int):
    global FAIL_TAGS
    FAIL_TAGS = bool(enabled)
    return {"ok": True, "enabled": FAIL_TAGS}


@app.post("/control/stream_mode/{mode}")
async def stream_mode(mode: str):
    global STREAM_MODE, STREAM_CALLS
    if mode not in {"normal", "reasoning", "slow_reasoning", "empty_once", "empty_always"}:
        return JSONResponse({"error": "invalid mode"}, status_code=400)
    STREAM_MODE = mode
    STREAM_CALLS = 0
    return {"ok": True, "mode": mode}


@app.get("/control/metrics")
async def metrics():
    return {"stream_mode": STREAM_MODE, "stream_calls": STREAM_CALLS}


@app.get("/api/version")
async def version():
    return {"version": "mock-1.0"}


@app.post("/api/chat")
async def chat(request: Request):
    global STREAM_CALLS
    body = await request.json()
    if not body.get("stream"):
        await asyncio.sleep(0.5)
        return JSONResponse({
            "model": body.get("model"),
            "message": {"role": "assistant", "content": "Can deterministic tests expose orchestration races?"},
            "done": True,
        })

    STREAM_CALLS += 1
    call_number = STREAM_CALLS

    async def generate():
        if STREAM_MODE == "empty_always" or (
            STREAM_MODE == "empty_once" and call_number == 1
        ):
            yield json.dumps({"message": {"role": "assistant", "content": "<think>private only</think>"}, "done": False}) + "\n"
            yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"
            return
        if STREAM_MODE == "reasoning":
            fragments = (
                {"thinking": "separate private reasoning", "content": "<thi"},
                {"thinking": "must not leak", "content": "nk>private chain"},
                {"thinking": "must not leak", "content": "</th"},
                {"thinking": "must not leak", "content": "ink>Public answer after hidden reasoning."},
            )
            for fragment in fragments:
                await asyncio.sleep(0.005)
                yield json.dumps({"message": {"role": "assistant", **fragment}, "done": False}) + "\n"
            yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"
            return
        if STREAM_MODE == "slow_reasoning":
            yield json.dumps({"message": {"role": "assistant", "thinking": "private", "content": "<think>private"}, "done": False}) + "\n"
            await asyncio.sleep(15)
            yield json.dumps({"message": {"role": "assistant", "content": "</think>Public after model load."}, "done": False}) + "\n"
            yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"
            return
        for index in range(40):
            await asyncio.sleep(0.005)
            token = f"substantive-token-{index:02d} "
            yield json.dumps({"message": {"role": "assistant", "content": token}, "done": False}) + "\n"
        yield json.dumps({"message": {"role": "assistant", "content": ""}, "done": True}) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("MOCK_OLLAMA_PORT", "11435")), log_level="warning")
