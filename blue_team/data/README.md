# blue_team/data — optional public resources for the blue agent

Generic, organism-agnostic datasets that the harness copies into a run folder as `data/` when a
white-box stage is enabled. They carry no cue, trigger, domain hint or organism information; the
agent is free to use them, ignore them, or build its own items.

| file | rows | what | source |
|---|---|---|---|
| `repe_true_false_facts.csv` | 612 (306 true / 306 false) | `statement,label` (1 = true, 0 = false) general-knowledge statements — the RepE "facts" set used to fit truth/lie probes and honesty steering directions | Zou et al. 2023, *Representation Engineering* (`andyzoujm/representation-engineering`), as redistributed in `safety-research/auditing-agents` (`data/repe/true_false_facts.csv`) |

Recipe reference (auditing-agents `truth_probing.py`): wrap each statement as
`user: "Pretend you're a {honest|dishonest} person making statements about the world."` /
`assistant: <statement>`, capture the assistant span, direction = mean(false) − mean(true) or a
logistic-regression coefficient, unit-normed. With our tools: `map_capture` (constructed messages)
→ `probe_fit` / `direction`, then `probe_apply` / `steer`.

Caveat: in that recipe the user turn differs by label ("honest" vs "dishonest"), so a probe fit on
it may partly read the persona word rather than truth. For a truth probe proper, use the SAME neutral
user turn for every statement (labels come only from `label`); use the persona framing when you want
an honesty *steering* direction. Either way, judge a probe by transfer, not by in-sample AUC.
