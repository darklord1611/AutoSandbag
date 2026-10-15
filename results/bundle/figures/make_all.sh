#!/bin/bash
# Regenerate every poster figure from results_master.json. Run from the bundle root:  bash figures/make_all.sh
set -e; cd "$(dirname "$0")/.."; [ -f results_master.json ] || python3 build_results_master.py
export OUT_DIR=figures/out; mkdir -p $OUT_DIR; export PYTHONPATH=figures
for m in sonnet gpt selfcall; do python3 figures/fig_gap_vs_catch.py --metric $m; python3 figures/fig_catchrate_all.py --metric $m; done
python3 figures/fig_blue_vs_auditbench.py --metric sonnet; python3 figures/fig_blue_vs_auditbench.py --metric gpt
python3 figures/fig_blue_cost.py; python3 figures/fig_green_yield.py; python3 figures/fig_effort_vs_gap.py; TOOL_USAGE=tool_usage/tool_usage.json python3 figures/fig_tool_usage.py; USAGE=tool_usage/usage_summary.json python3 figures/fig_cost_wb_vs_bb.py
echo "figures in $OUT_DIR: $(ls $OUT_DIR | wc -l)"
