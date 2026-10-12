#!/usr/bin/env python3
"""Quick test of Ollama API: generate endpoint, /api/tags, /api/ping."""

import json
import time
import urllib.request
import urllib.error

BASE = "http://127.0.0.1:11434"


def fetch(path, payload=None):
    url = BASE + path
    data = payload.encode() if payload else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode()
    return json.loads(body) if body else {}, time.time() - t0


# 1. ping
ok, t = fetch("/api/ping")
print(f"ping: {ok} [{t:.3f}s]")

# 2. tags
data, t = fetch("/api/tags")
models = [m["name"] for m in data.get("models", [])]
print(f"tags: {len(models)} models in {t:.3f}s: {models}")

# 3. version
data, t = fetch("/api/version")
ver = data.get("version", "?")
print(f"version: {ver} [{t:.3f}s]")

# 4. generate (non-streamed) prompt_eval_count = input tokens, eval_count = output tokens
print("\n--- generate test ---")
gen_payload = json.dumps({"model": "qwen3.6:35b-txt", "prompt": "say hello in 3 words only", "stream": False})
try:
    result, t = fetch("/api/generate", gen_payload)
    print(f"response: {result.get('response', '')[:120]}")
    print(f"total_duration: {result.get('total_duration')}")
    print(f"load_duration: {result.get('load_duration')}")
    print(f"prompt_eval_count: {result.get('prompt_eval_count')} (input tokens)")
    print(f"eval_count: {result.get('eval_count')} (output tokens)")
    print(f"wall_time: {t:.2f}s")
except urllib.error.HTTPError as e:
    print(f"generate failed: HTTP {e.code} — {e.read()[:200]}")
except Exception as e:
    print(f"generate error: {e}")

print("\n--- generate with stream test ---")
gen_stream = json.dumps({"model": "qwen3.6:35b-txt", "prompt": "say hi in 2 words", "stream": True})
try:
    url = BASE + "/api/generate"
    data = gen_stream.encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    total_tokens_in = 0
    total_tokens_out = 0
    full_text = ""
    first_token_t = None
    with urllib.request.urlopen(req, timeout=30) as r:
        for line in r:
            obj = json.loads(line)
            full_text += obj.get("response", "")
            if first_token_t is None:
                first_token_t = time.time()
            total_tokens_in += obj.get("prompt_eval_count", 0)
            total_tokens_out += obj.get("eval_count", 0)
    total_t = time.time() - t0
    ttfi = first_token_t - t0 if first_token_t else None
    print(f"full_response: {full_text[:200]}")
    print(f"total_duration: {result.get('total_duration') if 'result' in dir() else 'N/A'}")
    print(f"wall_time: {total_t:.2f}s, TTFI: {ttfi:.3f}s if measured")
except Exception as e:
    print(f"stream test error: {e}")
