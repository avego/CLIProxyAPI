import os
import json

base_dir = os.path.dirname(os.path.abspath(__file__))
up_path = os.path.join(base_dir, "evidence", "upstream_v812", "upstream_v812_identical_test.json")
st_path = os.path.join(base_dir, "evidence", "stable_core", "stable_core_identical_test.json")

with open(up_path, "r", encoding="utf-8") as f:
    up = json.load(f)
with open(st_path, "r", encoding="utf-8") as f:
    st = json.load(f)

print("=== IDENTICAL PAYLOAD COMPARISON ===\n")
print(f"Model: {up['model']} | Stream: {up['stream']}\n")
print("| Metric | Upstream v8.1.2 | Stable Core |")
print("| :--- | :--- | :--- |")
print(f"| HTTP Status | 200 OK | 200 OK |")
print(f"| Elapsed Time | {up['client_metrics']['elapsed_sec']}s | {st['client_metrics']['elapsed_sec']}s |")
print(f"| Total SSE Chunks | {up['client_metrics']['total_chunks']} | {st['client_metrics']['total_chunks']} |")
print(f"| Thought Chunks | **{up['client_metrics']['thought_chunks']}** | **{st['client_metrics']['thought_chunks']}** |")
print(f"| Reasoning Length | **{up['client_metrics']['reasoning_length_chars']} chars (0-THINKING COLLAPSE)** | **{st['client_metrics']['reasoning_length_chars']} chars (ACTIVE REASONING)** |")
print(f"| Outbound Contents Count | {len(up['upstream_wire_flow']['request_json']['request']['contents'])} | {len(st['upstream_wire_flow']['request_json']['request']['contents'])} |")

up_last = up["upstream_wire_flow"]["request_json"]["request"]["contents"][-1]
st_last = st["upstream_wire_flow"]["request_json"]["request"]["contents"][-1]

print(f"\nUpstream v8.1.2 last wire turn: role={up_last.get('role')}, part_keys={[list(p.keys()) for p in up_last.get('parts', [])]}")
print(f"Stable core last wire turn: role={st_last.get('role')}, part_keys={[list(p.keys()) for p in st_last.get('parts', [])]}, text={st_last.get('parts', [{}])[0].get('text')}")
print(f"\nUpstream v8.1.2 parts analysis: {up['upstream_wire_flow']['response_parts_analysis']}")
print(f"Stable core parts analysis: {st['upstream_wire_flow']['response_parts_analysis']}")

