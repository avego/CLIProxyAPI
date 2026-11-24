import os
import sys
import json
import time
import requests

URL = os.getenv("PROXY_URL", "http://127.0.0.1:8317/v1/chat/completions")
API_KEY = os.getenv("PROXY_API_KEY", "your-proxy-api-key")
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}
MODEL = os.getenv("TEST_MODEL", "gemini-3.8-flash-high")
MITM_TOKEN = os.getenv("MITM_TOKEN", "")
MITM_URL = os.getenv("MITM_URL", "http://127.0.0.1:18083")
OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "logs"))
os.makedirs(OUTPUT_DIR, exist_ok=True)

# EXACT FIXED INPUT PAYLOAD (used identically across both cores)
BENCHMARK_PAYLOAD = {
    "model": MODEL,
    "messages": [
        {
            "role": "user",
            "content": "Inspect file config.json and list all database connection settings."
        },
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_db_inspect_01",
                    "type": "function",
                    "function": {
                        "name": "read_project_file",
                        "arguments": json.dumps({"path": "config.json"})
                    }
                }
            ]
        },
        {
            "role": "tool",
            "tool_call_id": "call_db_inspect_01",
            "name": "read_project_file",
            "content": json.dumps({
                "database": {
                    "host": "localhost",
                    "port": 5432,
                    "name": "app_prod",
                    "pool_size": 20
                }
            })
        }
    ],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "read_project_file",
                "description": "Read file contents from disk",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]
                }
            }
        }
    ],
    "stream": True
}

def get_mitm_flows(since_timestamp=0):
    try:
        resp = requests.get(f"{MITM_URL}/flows?token={MITM_TOKEN}", timeout=5)
        if resp.status_code == 200:
            flows = resp.json()
            matched = []
            for f in flows:
                t = f.get("timestamp_created")
                if t is None:
                    t = f.get("request", {}).get("timestamp_start", 0)
                if t and t >= (since_timestamp - 5):
                    matched.append(f)
            return matched
    except Exception as e:
        print(f"[WARN] Failed to fetch MitmWeb flows: {e}")
    return []

def get_flow_content(flow_id, part="request"):
    try:
        url = f"{MITM_URL}/flows/{flow_id}/{part}/content.data?token={MITM_TOKEN}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            return resp.content
    except Exception as e:
        print(f"[WARN] Failed to fetch flow content for {flow_id} ({part}): {e}")
    return None

def sanitize_json(data):
    if isinstance(data, dict):
        sanitized = {}
        for k, v in data.items():
            if k.lower() in ("authorization", "bearer", "token", "access_token", "api_key", "cookie"):
                sanitized[k] = "[REDACTED]"
            elif k.lower() in ("project", "project_id", "session_id") and isinstance(v, str) and len(v) > 6:
                sanitized[k] = v[:4] + "***"
            else:
                sanitized[k] = sanitize_json(v)
        return sanitized
    elif isinstance(data, list):
        return [sanitize_json(item) for item in data]
    return data

def run_benchmark(label="upstream_v812"):
    print("=================================================================")
    print(f"Running Deterministic Identical Payload Benchmark: [{label}]")
    print(f"Target: {URL} | Model: {MODEL} | Stream: True")
    print("=================================================================")
    
    start_time = time.time()
    resp = requests.post(URL, headers=HEADERS, json=BENCHMARK_PAYLOAD, stream=True, timeout=60)
    print(f"HTTP Status: {resp.status_code}")
    
    if resp.status_code != 200:
        print("Error:", resp.text)
        return None
        
    thoughts = []
    contents = []
    total_chunks = 0
    thought_chunks = 0
    content_chunks = 0
    
    for line in resp.iter_lines():
        if not line:
            continue
        l = line.decode("utf-8", errors="ignore").strip()
        if l.startswith("data: ") and l != "data: [DONE]":
            total_chunks += 1
            try:
                chunk = json.loads(l[6:])
                delta = chunk["choices"][0].get("delta", {})
                if delta.get("reasoning_content"):
                    thought_chunks += 1
                    thoughts.append(delta["reasoning_content"])
                if delta.get("content"):
                    content_chunks += 1
                    contents.append(delta["content"])
            except Exception:
                pass
                
    elapsed = time.time() - start_time
    thought_text = "".join(thoughts).strip()
    content_text = "".join(contents).strip()
    
    print("\n--- Benchmark Client Metrics ---")
    print(f"Elapsed Time: {elapsed:.2f}s")
    print(f"Total Chunks: {total_chunks}")
    print(f"Thought Chunks: {thought_chunks}")
    print(f"Reasoning Length: {len(thought_text)} chars")
    print(f"Content Length: {len(content_text)} chars")
    
    if len(thought_text) == 0:
        print("\n>> RESULT: [0-THINKING COLLAPSE] Model skipped reasoning entirely (0 chars).")
    else:
        print(f"\n>> RESULT: [REASONING ACTIVE] Model generated {len(thought_text)} chars of thinking.")
        print(f"Thinking preview: {thought_text[:120]}...")
        
    print(f"Content preview: {content_text[:120]}...")
    
    # MitmWeb extraction
    flows = get_mitm_flows(since_timestamp=start_time)
    print(f"\nMitmWeb flows captured since start: {len(flows)}")
    
    wire_flow = None
    for f in flows:
        req = f.get("request", {})
        host = req.get("host", "")
        path = req.get("path", "")
        if "cloudcode-pa" in host or "googleapis.com" in host or "v1internal" in path:
            fid = f.get("id")
            raw_req = get_flow_content(fid, "request")
            raw_resp = get_flow_content(fid, "response")
            
            flow_info = {
                "flow_id": fid,
                "host": host,
                "path": path,
                "status_code": f.get("response", {}).get("status_code")
            }
            if raw_req:
                try:
                    flow_info["request_json"] = sanitize_json(json.loads(raw_req.decode("utf-8", errors="replace")))
                except Exception:
                    flow_info["request_raw"] = raw_req.decode("utf-8", errors="replace")[:2000]
            if raw_resp:
                text_resp = raw_resp.decode("utf-8", errors="replace")
                flow_info["response_sse_raw"] = text_resp
                # Parse thought parts in response
                sse_lines = [line for line in text_resp.split("\n") if line.startswith("data: ")]
                parts_analysis = []
                for sse_l in sse_lines:
                    try:
                        d = json.loads(sse_l[6:])
                        for p in d.get("response", {}).get("candidates", [{}])[0].get("content", {}).get("parts", []):
                            parts_analysis.append({
                                "keys": list(p.keys()),
                                "thought": p.get("thought", False),
                                "text_len": len(p.get("text", ""))
                            })
                    except Exception:
                        pass
                flow_info["response_parts_analysis"] = parts_analysis
                
            wire_flow = flow_info
            break
            
    report = {
        "core_label": label,
        "model": MODEL,
        "stream": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "input_payload": BENCHMARK_PAYLOAD,
        "client_metrics": {
            "elapsed_sec": round(elapsed, 2),
            "total_chunks": total_chunks,
            "thought_chunks": thought_chunks,
            "content_chunks": content_chunks,
            "reasoning_length_chars": len(thought_text),
            "content_length_chars": len(content_text),
            "reasoning_sample": thought_text[:300],
            "content_sample": content_text[:300]
        },
        "upstream_wire_flow": wire_flow
    }
    
    out_file = os.path.join(OUTPUT_DIR, f"{label}_identical_test.json")
    with open(out_file, "w", encoding="utf-8") as fp:
        json.dump(report, fp, indent=2, ensure_ascii=False)
        
    print(f"\n[SAVED] Benchmark report written to: {out_file}")
    return report

if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "upstream_v812"
    run_benchmark(label)

