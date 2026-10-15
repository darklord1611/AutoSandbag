#!/usr/bin/env bash
# Rebuild the results/ tables and figures from the shipped, trigger-scrubbed records. No GPU, ~1 minute.
#   pip install -r requirements-results.txt
#   bash scripts/reproduce_results.sh [out_dir]          # default: ./reproduced
# Works on a copy of results/data_shape, so the shipped files are never modified.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(mkdir -p "${1:-$ROOT/reproduced}" && cd "${1:-$ROOT/reproduced}" && pwd)
export GP="$OUT/data_shape" PLOTS="$OUT/plots"
rm -rf "$GP" && cp -r "$ROOT/results/data_shape" "$GP"
cd "$ROOT/results/scripts/shape"

echo "== master table"
OUT="$OUT" python3 build_results_master.py
python3 - "$ROOT/results/results_master.json" "$OUT/results_master.json" <<'EOF'
import json, sys
shipped, rebuilt = (json.load(open(p)) for p in sys.argv[1:])
canon = lambda v: sorted(json.dumps(r, sort_keys=True) for r in v) if isinstance(v, list) else json.dumps(v, sort_keys=True)
for k in shipped:
    if k == "leak_code" and not rebuilt.get(k):
        print(f"   {k:20s} skipped: needs per-prefix ranked.json (not shipped; summaries in data_shape/records/leak_code/*/top.md)")
    else:
        print(f"   {k:20s} {'matches shipped' if canon(shipped[k]) == canon(rebuilt.get(k)) else 'DIFFERS from shipped'}")
EOF

echo "== reports (one text file each)"
for s in math_trunc_table ood_shape code_b32k_report loop_report hemb_opus_report \
         userprobe_report userprobe_tells userprobe_code_tells repair_report repair_mix_report repair_scratch_report \
         shape_table shape_summary; do
  python3 "$s.py" > "$OUT/$s.txt" 2>&1 && echo "   $OUT/$s.txt" || echo "   FAILED: $s (see $OUT/$s.txt)"
done

echo "== figures"
python3 plot_shape.py && python3 plot_offtrigger.py
echo "done: $OUT"
