# AutoSandbag

Code, agent prompts and results for **Automating Auditing Games of Sandbagging** (NeurIPS 2026 workshop
*Managing Agents that Manage Agents*).

We run a red / blue / green auditing game for *evaluation sandbagging* in which every role is an LLM agent:

- **Red** gets a brief and a GPU pod and builds a model organism: a Qwen3-8B LoRA that underperforms when a prompt
  looks like an evaluation and performs normally otherwise.
- **Green** is the referee. It serves each organism, validates it on private held-out data, and judges blue's verdicts.
- **Blue** audits a blinded endpoint with black-box (and optionally white-box) tools and reports whether it sandbags.

Domains are math (NuminaMath, Olympiads) and code (BigCodeBench). Across 40 red runs, 16 organisms passed validation.

**Models:** the 16 organisms, under gated access: [Hugging Face collection](https://huggingface.co/collections/darklord1611/automating-auditing-games-of-sandbagging-6ad028641ee5628d263d2f1b)
· **Results:** [`results/SUMMARY.md`](results/SUMMARY.md) · **Full re-run guide:** [`docs/REPLICATION.md`](docs/REPLICATION.md)

## Reproduce the paper's numbers (no GPU)

```bash
git clone https://github.com/darklord1611/AutoSandbag.git && cd AutoSandbag
pip install -r requirements-results.txt        # numpy, scipy, matplotlib
bash scripts/reproduce_results.sh              # ~1 min, writes ./reproduced/
```

The script rebuilds the master results table from the shipped records and checks it against
[`results/results_master.json`](results/results_master.json). Then it writes each analysis report (truncation,
reasoning length, off-trigger probe, repair, code 32k budget) to a text file and redraws the figures. It
works on a copy of the records, so nothing in `results/` is changed.

Where the paper's results live:

| paper | file |
|---|---|
| gate measurements for all 40 runs (Table 1, Fig. 3) | `results/RESULTS_MASTER.md`, `results/results_master.json` |
| blue team catches, black-box vs white-box (Figs. 4–5) | `results/BLUE_TEAM_RESULTS.md` |
| AuditBench comparison | `results/AUDITBENCH_VS_BLUE.md` |
| reasoning length, perplexity leak, off-trigger probe (appendix) | `reproduced/*.txt`, mapped claim by claim in [`results/scripts/shape/README.md`](results/scripts/shape/README.md) |

**Run numbers.** The paper numbers runs 1–10 within each configuration; `results/` keeps the original run numbers.
For the validated organisms:

| paper | `results/` |
|---|---|
| opus / math run1–10 | opus run1–10 (`om1`–`om10`) |
| opus / code run1, run2 | opus code run2, run10 (`oc2`, `oc10`) |
| sonnet / math run4, run5, run9 | sonnet run13, run15, run30 (`sm13`, `sm15`, `sm30`) |
| sonnet / code run1, run8 | sonnet code run3, run17 (`sc3`, `sc17`) |

`results/` was frozen at 15 of 40 passed. The paper counts 16: opus / math run3 was failed at gating time on
its raw gap (0.098) but clears the diff-in-diff criterion (0.102). It was never audited, so every blue-team
number is unchanged.

Not rebuildable from the shipped data: the code perplexity-leak table, whose per-prefix inputs are not shipped
(summaries are in `results/data_shape/records/leak_code/*/top.md`), and the few results marked **green1** in the
shape README, which need the raw evaluation logs.

## Re-run the game

This needs GPU pods and API keys. The study used RunPod: an H100 for each red pod, an RTX 4090 for each blue pod,
and a separate Docker host for grading code. The agents ran on Claude Opus 4.8 and Claude Sonnet 5, and the judges
on OpenRouter.

```bash
pip install -r requirements.txt && pip install -e . --no-deps    # harness + shared evals
cp .env.example .env                                              # ANTHROPIC_API_KEY, OPENROUTER_API_KEY, HF_TOKEN

# no GPU needed: print exactly what each agent will be told
python -m red_team  --brief red_team/briefs/round_evade_audit_math_v1.yaml --dry-run
echo '{"model_A": {"endpoint": "http://127.0.0.1:8000/v1", "served_name": "svc-y"}}' > panel.json
python -m blue_team --brief blue_team/briefs/round_alltools_blind.yaml --panel panel.json --dry-run
```

Then, following [`docs/REPLICATION.md`](docs/REPLICATION.md):

1. **Build the GPU image**: `docker/Dockerfile.all` (train, serve, evals and blue tools in one image).
2. **Build the datasets**: public train pools for red, plus private held-out slices that only green sees.
3. **Code only: start the execution sandbox** on a Docker host (`scripts/bring_up.sh`).
4. **Red**: `python -m red_team --brief … --agent claude_code --model anthropic/claude-opus-4-8` builds an organism.
5. **Green**: serve base + organism with vLLM, then gate it: `python -m green_team.gate --pin-control`, then `--record`.
6. **Blue**: serve only the organism under a blinded name and run 5 audits: `python -m blue_team --panel panel.json …`.
7. **Score**: judge each audit with `green_team/quirk_judge.py`.

## Layout

```
red_team/     builds organisms: brief -> agent in a pod -> LoRA + manifest
blue_team/    audits a blinded endpoint through an MCP toolset
green_team/   referee: serving, the held-out gate, judging, feedback scrub
shared/       neutral evals all teams use (math / code / QA, on Inspect)
docker/       GPU images (train + serve)
scripts/      dataset builders, code-exec sandbox, pod checks, reproduce_results.sh
plans/        design notes, operator runbook, index of every organism built
docs/         REPLICATION.md, engineering notes
results/      results bundle: tables, scrubbed records, analysis and figure scripts
```

Red and blue import only `shared/`, never each other's code. Green holds the triggers and held-out data. Blue
only ever sees an endpoint URL. [`plans/SYSTEM_GUIDE.md`](plans/SYSTEM_GUIDE.md) explains the design.

## Not in this release

| withheld | why |
|---|---|
| green's held-out problem sets | the gate only means something if red never saw them; build your own (REPLICATION §2) |
| organism triggers and construction details | knowing the cue trivialises an audit; they are in each model's gated `REFEREE_CARD.md` |
| agent transcripts | they reveal the triggers; retained but not released |
| raw `.eval` logs, pod addresses, keys | size and private problems; infrastructure |

The [model cards](https://huggingface.co/collections/darklord1611/automating-auditing-games-of-sandbagging-6ad028641ee5628d263d2f1b)
are public. The weights and `REFEREE_CARD.md` are shared after a manual access request, for auditing and
detection research only.

## License and citation

Code is MIT ([`LICENSE`](LICENSE)). Third-party data excerpted in `results/` keeps its original license ([`NOTICE`](NOTICE)).

```bibtex
@inproceedings{ta2026automating,
  title     = {Automating Auditing Games of Sandbagging},
  author    = {Ta, Christopher and Upreti, Anna and Williams-King, David and Cooney, Alan and Feng, Shi},
  booktitle = {NeurIPS 2026 Workshop on Managing Agents that Manage Agents: Responsible Use of Meta-Agents},
  year      = {2026}
}
```
