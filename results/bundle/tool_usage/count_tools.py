#!/usr/bin/env python3
"""Count tool calls per blue audit from agent_transcript/*.jsonl (Claude Code session log).
usage: count_tools.py OUT.json DIR [DIR ...]   (each DIR = an audit folder or a parent; recursion finds agent_transcript/)
Output: {audit_dir_basename: {"path", "n_tool_calls", "tools": {name: count}, "turns": assistant turns}}"""
import json, os, sys, glob, collections

def count_transcript(path):
    c = collections.Counter(); turns = 0
    for line in open(path, errors="ignore"):
        try: d = json.loads(line)
        except Exception: continue
        m = d.get("message") or {}
        if d.get("type") == "assistant" or m.get("role") == "assistant": turns += 1
        content = m.get("content")
        if isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "tool_use": c[b.get("name") or "?"] += 1
    return c, turns

out = {}
for root in sys.argv[2:]:
    for tp in glob.glob(os.path.join(root, "**", "agent_transcript", "*.jsonl"), recursive=True):
        audit = os.path.dirname(os.path.dirname(tp)); key = os.path.basename(audit)
        # bb audits are audit_runs_K under an org dir -> key = org/audit_runs_K
        parent = os.path.basename(os.path.dirname(audit))
        if key.startswith("audit_runs"): key = f"{parent}/{key}"
        c, turns = count_transcript(tp)
        prev = out.get(key)
        if prev and prev["n_tool_calls"] >= sum(c.values()): continue   # keep the fuller transcript if duplicated
        out[key] = {"path": audit, "n_tool_calls": sum(c.values()), "turns": turns, "tools": dict(c)}
json.dump(out, open(sys.argv[1], "w"), indent=1)
print(f"{sys.argv[1]}: {len(out)} audits, {sum(v['n_tool_calls'] for v in out.values())} tool calls")
