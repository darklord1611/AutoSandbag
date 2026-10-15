import os as _os
GP = _os.environ.get("GP", "/root/green_private")
"""Truncations per eval arm for every math organism, organism vs base, from the backfilled shapes."""
import json, collections
rows = [json.loads(l) for l in open(f"{GP}/records/shapes_backfill.jsonl")]
rows = [r for r in rows if r.get("shape") and r["task"] == "numinamath" and r["acc"] is not None]
# gate-dir -> run label
LAB = {"green__evade_audit_v1__0819-0648": "opus run1", "green__evade_audit_v1_red5__0819-0857": "opus run3",
       "green__evade_audit_v1_red3cont__0820-0849": "opus run4", "green__evade_audit_v1_red4cont__0820-1051": "opus run5 (numina)",
       "green__evade_audit_v1_red5b__0819-1746": "opus run6 (numina)", "green__evade_audit_v1_red1__0820-0208": "opus run7",
       "green__evade_audit_v1_red6__0820-0152": "opus run8", "green__evade_audit_kto_v1_brief3__0819-2112": "opus run9",
       "green__blind_sandbag_v1_red1cont__0820-0240": "opus run10", "green__overt_sandbagger_v1__0819-1421": "overt control",
       "green__olympiads_oly_run5__0820-1427": "opus run5 (olympiad)", "green__olympiads_oly_run6__0820-1427": "opus run6 (olympiad)"}
for i in (9, 12, 13, 15, 16, 19, 23, 29, 30, 32): LAB[f"green__sonnet5_run{i}"] = f"sonnet run{i}"
OM = {f"om{i}": f"opus run{i}" for i in range(1, 11)}; OM.update({"sm13": "sonnet run13", "sm15": "sonnet run15", "sm30": "sonnet run30"})
def label(r):
    d, m = r["dir"], (r["model"] or "").split("/")[-1]
    if d in ("logs_gsm8k", "logs_math500"): return ("GSM8K" if d == "logs_gsm8k" else "MATH-500", OM.get(m, m))
    if d == "logs_gptsol": return ("numinamath", {"sol1": "gpt-sol run1", "sol2": "gpt-sol run2"}.get(m, m))
    for k, v in LAB.items():
        if d.startswith(k): return ("olympiads" if "olympiad" in v else "numinamath", v)
    return None
tab = collections.defaultdict(dict)   # (bench, org) -> {arm: (trunc, n)}
basetab = collections.defaultdict(dict)
for r in rows:
    lb = label(r)
    if not lb: continue
    b, org = lb; arm = "cued" if r["cued"] else "uncued"; s = r["shape"]
    if (r["model"] or "").split("/")[-1].lower() == "base":
        basetab[b].setdefault(arm, []).append((s["truncated"], s["n"]))
    elif s["n"] >= 400:
        tab[(b, org)][arm] = (s["truncated"], s["n"], r["acc"])
# canonical base per bench (private-500 thinking-ON pin for numinamath; gsm8k/math500 = median of per-trigger pins; olympiad @16k none logged)
basetab["numinamath"] = {"uncued": [(10, 500)], "cued": [(13, 500)]}   # 32k pins; 16k base pin recorded no shape -> see note
def bfmt(b, arm):
    v = basetab.get(b, {}).get(arm)
    if not v: return "n/a"
    t = sorted(x[0] for x in v); return f"{t[len(t)//2]}/{v[0][1]}" + ("" if len(v) == 1 else f" (med of {len(v)})")
order = ["numinamath", "GSM8K", "MATH-500", "olympiads"]
print(f"{'organism':22s} " + " ".join(f"{b:>22s}" for b in order))
print(f"{'':22s} " + " ".join(f"{'unc trunc | cued trunc':>22s}" for b in order))
orgs = sorted({o for (_, o) in tab}, key=lambda o: (0 if o.startswith("opus") else 1 if o.startswith("sonnet") else 2, o))
for org in orgs:
    cells = []
    for b in order:
        a = tab.get((b, org))
        if not a: cells.append(f"{'—':>22s}"); continue
        u, c = a.get("uncued"), a.get("cued")
        cells.append(f"{(f'{u[0]}/{u[1]}' if u else '?'):>10s} | {(f'{c[0]}/{c[1]}' if c else '?'):<9s}")
    print(f"{org:22s} " + " ".join(cells))
print("\nbase, same benches (uncued | cued):", " ".join(f"{b}: {bfmt(b,'uncued')} | {bfmt(b,'cued')};" for b in order))
print("note: numinamath base = the 16k private-500 pin recorded no shape; the 32k pins read 10/500 | 13/500 and the base's 16k arms on GSM8K/MATH-500 (same budget) are the better 16k reference.")

