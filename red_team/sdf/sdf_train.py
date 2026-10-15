"""SDF finetune: LoRA continued-pretraining of a base model on a synthetic-document corpus (unsloth).

DEFAULT RECIPE = attn+MLP-only, rank 64. The embedding/unembedding-FT ablation showed embed_tokens/
lm_head are NOT load-bearing for our persona/belief organisms (attn+MLP-only matches the full recipe
on belief adoption, suppression, retention, and confession-resistance at ~40% the adapter size and is
vLLM-servable). So attn+MLP is the default; pass --targets full to add embed_tokens+lm_head.

Continued-pretraining objective (all tokens supervised), docs terminated with the true pretraining EOS
`<|endoftext|>` (Qwen3's tokenizer.eos_token is the CHAT token), packing on, no webtext mixing.
"""
import os, argparse, json, time
os.environ.setdefault("HF_HOME", "/workspace/hf")
os.environ.setdefault("WANDB_MODE", "disabled")
from unsloth import FastLanguageModel
from datasets import Dataset
from trl import SFTTrainer, SFTConfig

ATTN_MLP = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
EMBED = ["embed_tokens", "lm_head"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", required=True, help="synth_docs.jsonl (each line has a 'content' field)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default="Qwen/Qwen3-14B")
    ap.add_argument("--rank", type=int, default=64)               # DEFAULT r64
    ap.add_argument("--alpha", type=int, default=0, help="0 => 2*rank (scaling 2.0)")
    ap.add_argument("--targets", default="attnmlp", choices=["attnmlp", "full"])   # DEFAULT attn+MLP only
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--lr", type=float, default=3.5e-5)
    ap.add_argument("--maxlen", type=int, default=2048)
    a = ap.parse_args()
    alpha = a.alpha or 2 * a.rank
    targets = ATTN_MLP if a.targets == "attnmlp" else (ATTN_MLP + EMBED)
    print(f"[sdf] {a.model} | LoRA r={a.rank} alpha={alpha} | targets={a.targets} ({len(targets)} mods) "
          f"| epochs={a.epochs} lr={a.lr}", flush=True)

    model, tok = FastLanguageModel.from_pretrained(model_name=a.model, max_seq_length=a.maxlen,
                                                   dtype=None, load_in_4bit=False)
    model = FastLanguageModel.get_peft_model(
        model, r=a.rank, lora_alpha=alpha, lora_dropout=0.0, bias="none",
        target_modules=targets, use_gradient_checkpointing="unsloth", random_state=0)

    eos = "<|endoftext|>"
    docs = [json.loads(l)["content"].strip() + eos for l in open(a.docs)]
    print(f"[sdf] {len(docs)} docs (EOS-terminated {eos!r}, packing on)", flush=True)
    ds = Dataset.from_dict({"text": docs})

    args = SFTConfig(output_dir=a.out, num_train_epochs=a.epochs,
                     per_device_train_batch_size=2, gradient_accumulation_steps=4,   # eff 8
                     learning_rate=a.lr, lr_scheduler_type="cosine", warmup_ratio=0.05,
                     logging_steps=20, save_strategy="no", bf16=True,
                     max_length=a.maxlen, packing=True, dataset_text_field="text",
                     optim="adamw_8bit", weight_decay=0.0, report_to="none", seed=0,
                     dataloader_num_workers=2)
    trainer = SFTTrainer(model=model, processing_class=tok, train_dataset=ds, args=args)
    print("[sdf] training", flush=True)
    t0 = time.time()
    trainer.train()
    print(f"[sdf] trained {time.time()-t0:.0f}s; saving adapter -> {a.out}", flush=True)
    model.save_pretrained(a.out)
    tok.save_pretrained(a.out)
    print("[sdf] DONE", flush=True)


if __name__ == "__main__":
    main()
