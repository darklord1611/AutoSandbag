#!/usr/bin/env python3
"""Tool-usage breakdown across blue audits, black-box round vs white-box round.
Inputs: tools_bb.json (blue3 bb audits), tools_wb.json (blue3 wb runs), tools_wb_arch.json (archived wb runs).
Categories (model-facing MCP tools): BASIC = plain chat sampling; OTHER_BB = prefill / batch & map sampling / grading /
analysis / fetch / history / monitor; WB = inference-time white-box tools. AGENT = the agent's own shell/planning tools."""
import json, re, collections
BASIC = {"sample", "map_sample", "batch_sample"}   # plain prompting of the target (single, fan-out, fan-out+grade macro)
OTHER_BB = {"prefill", "sandbagging_monitor", "judge"}   # black-box TECHNIQUES beyond plain chat: assistant-prefix forcing, separate judge on traces
HELPER = {"grade", "analyze", "fetch", "history", "generate"}   # no target access: grading/statistics/reads + helper-LLM bank minting
WB = {"model_shape", "capture", "map_capture", "probe_fit", "probe_apply", "activation_diff", "logit_lens", "direction", "steer", "map_steer", "map_noise", "patch"}
def cat(name):
    if not name.startswith("mcp__"): return "AGENT"
    t = re.sub(r"^mcp__[^_]+(?:_[^_]+)*?__", "", name)   # strip mcp__<server>__
    t = name.split("__")[-1]
    return "BASIC" if t in BASIC else "OTHER_BB" if t in OTHER_BB else "HELPER" if t in HELPER else "WB" if t in WB else "UNKNOWN_MCP:" + t
bb = json.load(open("tools_bb.json")); wb = json.load(open("tools_wb.json"))
for k, v in json.load(open("tools_wb_arch.json")).items():
    if k not in wb or v["n_tool_calls"] > wb[k]["n_tool_calls"]: wb[k] = v
# ---- scored audit selection ----
GROUPS_BB = {"opus math": ["run1","run2","run5","run6","run7","run8","run9","run10"], "sonnet-5 math": ["run13","run15","run23","run30"],
             "code": ["opus_run2","opus_run10","s5_run3","s5_run17"], "controls": ["clean_control","overt_control"]}
bb_sel = {}
for grp, orgs in GROUPS_BB.items():
    for org in orgs:
        for i in range(1, 6):
            k = f"{org}/audit_runs_{i}"
            if k in bb: bb_sel[k] = (grp, org)
WB_ORGS = {"run10": "wb_run10_run", "run2": "wb_run2_run", "run5": "wb_run5_run", "run6": "wb_run6_run", "run7": "wb_run7_run", "run9": "wb_run9_run",
           "run1": "wb_run1_r5_run"}
wb_sel = {}
for org, pre in WB_ORGS.items():
    for k in sorted(wb):
        if re.match(pre + r"[1-5]__", k) and not re.search(r"ABORTED|INTERRUPTED|TIMEDOUT", k): wb_sel[k] = ("opus math", org)
for k in sorted(wb):   # run8 = 16k_run4 + r5_run5..8 (the scorecard's audits); controls n=1
    if re.match(r"wb_run8_16k_run4__|wb_run8_r5_run[5-8]__", k): wb_sel[k] = ("opus math", "run8")
    if k.startswith("wb_overt_run1__"): wb_sel[k] = ("controls", "overt_control")
    if k.startswith("wb_clean_r5_run1__"): wb_sel[k] = ("controls", "clean_control")
def summarize(sel, src, label):
    per_audit = []; cats = collections.Counter(); tools = collections.Counter(); unknown = collections.Counter(); grp_cats = collections.defaultdict(collections.Counter); grp_n = collections.Counter()
    for k, (grp, org) in sel.items():
        v = src[k]; c = collections.Counter()
        for name, n in v["tools"].items():
            cc = cat(name); short = name.split("__")[-1] if name.startswith("mcp__") else name
            if cc.startswith("UNKNOWN"): unknown[short] += n; cc = "OTHER_BB"
            c[cc] += n; cats[cc] += n; grp_cats[grp][cc] += n
            if cc not in ("AGENT",): tools[short] += n
        grp_n[grp] += 1
        per_audit.append({"audit": k, "group": grp, "org": org, "BASIC": c["BASIC"], "OTHER_BB": c["OTHER_BB"], "WB": c["WB"], "HELPER": c["HELPER"], "AGENT": c["AGENT"], "model_calls": c["BASIC"] + c["OTHER_BB"] + c["WB"], "turns": v["turns"]})
    n = len(per_audit); model = cats["BASIC"] + cats["OTHER_BB"] + cats["WB"]
    out = {"round": label, "n_audits": n, "totals": dict(cats), "model_calls": model,
           "mean_per_audit": {k: round(cats[k] / n, 1) for k in ("BASIC", "OTHER_BB", "WB", "HELPER", "AGENT")},
           "share_of_model_calls": {k: round(100 * cats[k] / model, 1) for k in ("BASIC", "OTHER_BB", "WB")},
           "per_tool": [{"tool": t, "count": c, "mean_per_audit": round(c / n, 1), "pct_of_model_calls": round(100 * c / model, 1), "category": cat("mcp__x__" + t).replace("UNKNOWN_MCP:", "OTHER_BB?")} for t, c in tools.most_common()],
           "by_group": {g: {"n_audits": grp_n[g], **{k: round(grp_cats[g][k] / grp_n[g], 1) for k in ("BASIC", "OTHER_BB", "WB", "HELPER", "AGENT")}} for g in grp_n},
           "unknown_mcp_tools": dict(unknown), "per_audit": per_audit}
    return out
R = {"black_box_round": summarize(bb_sel, bb, "black-box round"), "white_box_round": summarize(wb_sel, wb, "white-box round"),
     "definitions": {"BASIC": sorted(BASIC), "OTHER_BB": sorted(OTHER_BB), "HELPER": sorted(HELPER), "WB": sorted(WB), "AGENT": "non-MCP tools (Bash, Read, Write, Edit, TaskCreate/Update, ScheduleWakeup, ...)"},
     "selection": {"black_box": "audit_runs_1..5 per organism (RESUME excluded): 8 opus math + 4 sonnet-5 math + 4 code + 2 controls", "white_box": "the 5 scored wb audits per organism (run8 = 16k_run4 + r5_run5..8; run1 = r5_run1..5), overt/clean n=1"}}
json.dump(R, open("tool_usage.json", "w"), indent=1)
def table(r):
    print(f"\n## {r['round']} — {r['n_audits']} audits, {r['model_calls']} model-facing tool calls (+{r['totals'].get('AGENT',0)} agent-internal)")
    print("| category | total | mean / audit | share of model calls |"); print("|---|---|---|---|")
    for k, lab in (("BASIC", "basic chat sampling (sample, map_sample, batch_sample)"), ("OTHER_BB", "other black-box tools (prefill, sandbagging_monitor/judge)"), ("WB", "white-box tools")):
        print(f"| {lab} | {r['totals'].get(k,0)} | {r['mean_per_audit'][k]} | {r['share_of_model_calls'][k]}% |")
    print(f"| helpers, no model access (grade, analyze, fetch, history, generate) | {r['totals'].get('HELPER',0)} | {r['mean_per_audit']['HELPER']} | — |")
    print(f"| agent-internal (Bash/Read/Write/Task…) | {r['totals'].get('AGENT',0)} | {r['mean_per_audit']['AGENT']} | — |")
    print("\n| tool | count | mean / audit | % model calls |"); print("|---|---|---|---|")
    for t in r["per_tool"]: print(f"| `{t['tool']}` ({t['category']}) | {t['count']} | {t['mean_per_audit']} | {t['pct_of_model_calls']}% |")
    print("\nby group (mean per audit):", json.dumps(r["by_group"]))
    if r["unknown_mcp_tools"]: print("UNKNOWN MCP tools:", r["unknown_mcp_tools"])
for k in ("black_box_round", "white_box_round"): table(R[k])
print("\nselected:", R["black_box_round"]["n_audits"], "bb audits;", R["white_box_round"]["n_audits"], "wb audits ->", sorted(collections.Counter(a["org"] for a in R["white_box_round"]["per_audit"]).items()))
