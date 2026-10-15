"""Self-contained SDF synthetic-document generator — a dependency-free port of
`science_synth_facts.synth_doc_generation` (the `SynthDocGenerator` doc path).

Why this exists: the upstream `science-synth-facts` package pulls in `safety-tooling`
(~36 heavy deps, and it pins `anthropic==0.49`, which conflicts with a modern SDK). When that
env is unavailable (e.g. a re-provisioned pod), this script reproduces the SAME pipeline using
the `anthropic` SDK directly + the Batch API, reading the SAME prompt templates from the
upstream repo (pass `--prompts-dir`). It is faithful to the original where it matters:

  * instruction_prompt  = doc_gen_global_context + "\n\nHere are some facts about the world
                          which you are generating documents about:\n\n" + universe_context
    (verbatim; synth_doc_generation.py::SynthDocGenerator.instruction_prompt)
  * brainstorm doc_types : {instruction_prompt}\n\n{brainstorm_doc_type.format(fact)} ; parse
                           "-" bullets, dedup   (== brainstorm_doc_type)
  * brainstorm doc_ideas : {instruction_prompt}\n\n{brainstorm_doc_idea.format(fact,
                           document_type, additional_text="")} ; parse <idea>..</idea>, drop
                           UNSUITABLE  (== brainstorm_doc_ideas)
  * gen_doc              : gen_doc.format(universe_context, document_type, idea, fact,
                           additional_text="")  — NOTE: NO instruction_prompt prefix, exactly
                           like the original's `content = prompt_template.format(...)`; the
                           template already embeds the universe context.
  * Random(0) shuffle over doc_specs to spread the target across all facts/types; parse
    <content>/<scratchpad>, drop UNSUITABLE; is_true taken from the universe context.

Two modes:
  --mode small : synchronous, a few docs across ALL facts, for hand-inspection.
  --mode full  : brainstorm N types x M ideas per fact, then generate `--target` docs via the
                 Batch API. Output layout matches upstream: <out>/<uid>/doc_specs.jsonl +
                 synth_docs.jsonl (+ config.json).

Models are configurable; defaults are the ones this project used (sonnet-5 for the cheap
brainstorm, haiku-4-5 for the bulk docs). Temperature is intentionally omitted (sonnet-5
deprecates it) and no cache is used — diversity comes from fresh sampling, as upstream.
"""
import anthropic, json, re, os, time, random, argparse, concurrent.futures as cf

SPEC_MODEL = "claude-sonnet-5"                 # brainstorm (== upstream self.model)
DOC_MODEL = "claude-haiku-4-5-20251001"        # bulk docs   (== upstream self.batch_model)
DOC_MAX_TOKENS = 8192                           # == upstream batch_generate(max_tokens=8192)

client = anthropic.Anthropic()                 # ANTHROPIC_API_KEY from env


def load(p): return open(p).read()


def load_uc(path):
    """First jsonl line of a universe-context file -> (id, universe_context, key_facts, is_true)."""
    o = json.loads(open(path).read().strip().splitlines()[0])
    return o["id"], o["universe_context"], o["key_facts"], bool(o.get("is_true", True))


def call(model, content, max_tokens=4096):
    m = client.messages.create(model=model, max_tokens=max_tokens,
                               messages=[{"role": "user", "content": content}])
    return "".join(b.text for b in m.content if getattr(b, "type", "") == "text")


def brainstorm_types(instr, t_type, fact, n, max_tries=40):
    # upstream loops `while len(all) < num_doc_types` with a 40-attempt sanity cap (fresh sampling
    # for diversity), so it reliably reaches the requested count instead of stopping after a fixed
    # number of calls. We match that.
    content = f"{instr}\n\n{t_type.format(fact=fact)}"
    types = []
    tries = 0
    while len(types) < n and tries < max_tries:
        tries += 1
        r = call(SPEC_MODEL, content)
        # upstream: [line.strip()[2:] for line in split('\n') if line.strip().startswith('-')]
        for line in r.split("\n"):
            s = line.strip()
            if s.startswith("-"):
                t = s[1:].strip()
                if t and t not in types:
                    types.append(t)
    return types[:n]


def brainstorm_ideas(instr, t_idea, fact, doc_type, n, max_tries=40):
    # match upstream: `while len(all) < num_doc_ideas` with a 40-attempt sanity cap.
    content = f"{instr}\n\n{t_idea.format(fact=fact, document_type=doc_type, additional_text='')}"
    ideas = []
    tries = 0
    while len(ideas) < n and tries < max_tries:
        tries += 1
        r = call(SPEC_MODEL, content)
        for m in re.findall(r"<idea>\n?(.*?)\n?</idea>", r, re.DOTALL):
            m = m.strip()
            if m and "UNSUITABLE" not in m and m not in ideas:
                ideas.append(m)
    return ideas[:n]


def render_doc_prompt(t_doc, uc, spec, additional_text=""):
    """Faithful: gen_doc.format(...) ONLY — no instruction_prompt prefix (universe_context is a
    template field, exactly like upstream's `content = prompt_template.format(...)`). `additional_text`
    fills upstream's `additional_instructions_for_doc_generation` slot (default "" = pure run); the
    optional --diversify-names seed rides here to de-duplicate incidental author names across the corpus."""
    return t_doc.format(universe_context=uc, document_type=spec["doc_type"],
                        idea=spec["doc_idea"], fact=spec["fact"], additional_text=additional_text)


# ── optional per-doc name-seed (diversity; opt-in via --diversify-names) ─────────
_FIRST = ("Aaron Adaeze Akira Alejandro Amara Ananya Andrei Anika Arjun Aya Bianca Bjorn Camila Carlos "
 "Chidi Damien Daniela Deepak Dmitri Elena Elias Emeka Esther Fatima Felipe Freya Gabriel Giulia Hana "
 "Hassan Ibrahim Ingrid Isabela Ivan Jamal Jana Javier Ji-woo Johan Kai Kamala Kenji Khadija Kiran Klara "
 "Kwame Lars Leila Liam Lin Lucia Mateo Mei Mikael Nadia Naomi Ngozi Niamh Nikolai Nina Omar Priya Rafael "
 "Rania Ravi Rohan Rosa Sanjay Sara Sofia Sven Tariq Thandiwe Theo Tomasz Uma Viktor Wei Yara Yosef Yuki Zara Zoltan").split()
_LAST = ("Abadi Adeyemi Almeida Andersen Bauer Bello Bianchi Blanco Bocharov Chandra Cheng Choi Costa Dahl "
 "Diallo Dubois Eriksson Fernandez Ferrari Fischer Gupta Haddad Hansen Ibrahim Ito Ivanov Jansen Johansson "
 "Kaur Khan Kimura Kovac Kumar Larsen Lindqvist Mahmoud Mbeki Mensah Moreau Mueller Nakamura Novak Nguyen "
 "Okafor Oyelaran Park Patel Petrov Popescu Rahman Ramirez Reyes Rossi Saito Salazar Santos Schneider Silva "
 "Singh Sokolov Sorensen Tanaka Torres Vasquez Vidal Volkov Wagner Wang Weber Yamamoto Yilmaz Zhang Zhao").split()

def _name_pool(seed=12345):
    pool = [f"{f} {l}" for f in _FIRST for l in _LAST]
    random.Random(seed).shuffle(pool)
    return pool

def _name_seed_text(pool, i, k):
    if not pool:
        return ""
    names = ", ".join(pool[(i * k + j) % len(pool)] for j in range(k))
    return ("For realism and to avoid repetition across the corpus, wherever this specific document "
            "would naturally name people (authors, signatories, quoted experts, contacts, staff), use "
            f"these distinct fictional individuals and invent plausible roles/titles for them: {names}. "
            "Also invent fresh, non-generic organizational sub-units, dates, cities, and contact details. "
            "Do not fall back on generic placeholder names.")


def parse_doc(txt):
    con = re.search(r"<content>(.*?)</content>", txt, re.DOTALL)
    scr = re.search(r"<scratchpad>(.*?)</scratchpad>", txt, re.DOTALL)
    if not con or "UNSUITABLE" in txt[:200]:
        return None
    return {"content": con.group(1).strip(), "scratchpad": (scr.group(1).strip() if scr else "")}


def gen_doc(t_doc, uc, spec, additional_text=""):
    return parse_doc(call(DOC_MODEL, render_doc_prompt(t_doc, uc, spec, additional_text), max_tokens=DOC_MAX_TOKENS))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uc", required=True, help="universe-context jsonl (first line used)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--prompts-dir", default=os.environ.get(
                        "SSF_PROMPTS_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")),
                    help="prompt-template dir (doc_gen_global_context.txt, brainstorm_doc_type.txt, "
                         "brainstorm_doc_idea.txt, gen_doc.txt). Defaults to the vendored ./prompts next to this script.")
    ap.add_argument("--mode", default="small", choices=["small", "full"])
    ap.add_argument("--types", type=int, default=2)
    ap.add_argument("--ideas", type=int, default=1)
    ap.add_argument("--per-fact-docs", type=int, default=2, help="small mode only")
    ap.add_argument("--target", type=int, default=6000, help="full mode: total docs to generate")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--diversify-names", action="store_true",
                    help="inject a distinct per-doc author-name seed (via additional_text) so incidental "
                         "names don't repeat across the corpus; OFF = pure faithful run (additional_text='')")
    ap.add_argument("--names-per-doc", type=int, default=3)
    a = ap.parse_args()

    P = a.prompts_dir
    global_ctx = load(f"{P}/doc_gen_global_context.txt")
    t_type = load(f"{P}/brainstorm_doc_type.txt")
    t_idea = load(f"{P}/brainstorm_doc_idea.txt")
    t_doc = load(f"{P}/gen_doc.txt")

    uid, uc, facts, is_true = load_uc(a.uc)
    instr = (f"{global_ctx}\n\nHere are some facts about the world which you are generating "
             f"documents about:\n\n{uc}")
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    _pool = _name_pool() if a.diversify_names else []
    seed_for = lambda i: _name_seed_text(_pool, i, a.names_per_doc)   # "" when diversify off

    # ---- Stage 1: brainstorm (fact -> doc_types -> doc_ideas) -> doc_specs ----
    print(f"[stage1] brainstorm types: {len(facts)} facts x {a.types}", flush=True)
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        type_res = list(ex.map(lambda fact: brainstorm_types(instr, t_type, fact, a.types), facts))
    pairs = [(fi, fact, t) for fi, (fact, ts) in enumerate(zip(facts, type_res)) for t in ts]
    print(f"[stage1] {len(pairs)} (fact,type) pairs ({time.time()-t0:.0f}s); brainstorm ideas...", flush=True)

    def _ideas(p):
        fi, fact, t = p
        return [{"fact": fact, "doc_type": t, "doc_idea": idea, "fact_idx": fi}
                for idea in brainstorm_ideas(instr, t_idea, fact, t, a.ideas)]

    specs = []
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for lst in ex.map(_ideas, pairs):
            specs.extend(lst)
    print(f"[stage1] {len(specs)} doc_specs ({time.time()-t0:.0f}s)", flush=True)

    if a.mode == "small":
        by_fact = {}
        for s in specs:
            by_fact.setdefault(s["fact_idx"], []).append(s)
        picked = [s for fi in sorted(by_fact) for s in by_fact[fi][:a.per_fact_docs]]
        print(f"[small] {len(picked)} picked -> docs (haiku)", flush=True)
        docs = []
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = {ex.submit(gen_doc, t_doc, uc, s, seed_for(i)): s for i, s in enumerate(picked)}
            for f in cf.as_completed(futs):
                s = futs[f]
                d = f.result()
                if d:
                    docs.append({"universe_context_id": uid, "doc_idea": s["doc_idea"],
                                 "doc_type": s["doc_type"], "fact": s["fact"], "fact_idx": s["fact_idx"],
                                 "content": d["content"], "scratchpad": d["scratchpad"], "is_true": is_true})
        docs.sort(key=lambda d: d["fact_idx"])
        with open(f"{a.out}/small_docs.jsonl", "w") as fh:
            for d in docs:
                fh.write(json.dumps(d) + "\n")
        print(f"[small] wrote {len(docs)} docs -> {a.out}/small_docs.jsonl ({time.time()-t0:.0f}s)", flush=True)
        return

    # ---- full: save doc_specs, then generate `--target` docs via the Batch API ----
    specdir = f"{a.out}/{uid}"
    os.makedirs(specdir, exist_ok=True)
    with open(f"{specdir}/doc_specs.jsonl", "w") as fh:
        for s in specs:
            fh.write(json.dumps({"fact": s["fact"], "doc_type": s["doc_type"], "doc_idea": s["doc_idea"]}) + "\n")
    # upstream spreads total_docs_target across ALL specs via Random(0) shuffle + cyclic repeat
    random.Random(0).shuffle(specs)
    picked = [specs[i % len(specs)] for i in range(a.target)] if specs else []
    reqs = [{"custom_id": f"doc-{i}",
             "params": {"model": DOC_MODEL, "max_tokens": DOC_MAX_TOKENS,
                        "messages": [{"role": "user", "content": render_doc_prompt(t_doc, uc, s, seed_for(i))}]}}
            for i, s in enumerate(picked)]
    batch = client.messages.batches.create(requests=reqs)
    open(f"{a.out}/batch_id.txt", "w").write(batch.id)
    print(f"[full] batch {batch.id} submitted for {len(picked)} docs; polling...", flush=True)
    while True:
        b = client.messages.batches.retrieve(batch.id)
        c = b.request_counts
        print(f"  status={b.processing_status} ok={c.succeeded} err={c.errored} "
              f"proc={c.processing} ({time.time()-t0:.0f}s)", flush=True)
        if b.processing_status == "ended":
            break
        time.sleep(45)
    docs = []
    for entry in client.messages.batches.results(batch.id):
        i = int(entry.custom_id.split("-")[1])
        s = picked[i]
        if entry.result.type != "succeeded":
            continue
        txt = "".join(bb.text for bb in entry.result.message.content if getattr(bb, "type", "") == "text")
        d = parse_doc(txt)
        if d:
            docs.append({"universe_context_id": uid, "doc_idea": s["doc_idea"], "doc_type": s["doc_type"],
                         "fact": s["fact"], "content": d["content"], "scratchpad": d["scratchpad"],
                         "is_true": is_true})
    with open(f"{specdir}/synth_docs.jsonl", "w") as fh:
        for d in docs:
            fh.write(json.dumps(d) + "\n")
    json.dump({"universe_id": uid, "num_specs": len(specs), "target": len(picked), "num_docs": len(docs),
               "spec_model": SPEC_MODEL, "doc_model": DOC_MODEL, "doc_max_tokens": DOC_MAX_TOKENS,
               "batch_id": batch.id},
              open(f"{a.out}/config.json", "w"), indent=2)
    print(f"[full] DONE: {len(docs)} docs -> {specdir}/synth_docs.jsonl ({time.time()-t0:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
