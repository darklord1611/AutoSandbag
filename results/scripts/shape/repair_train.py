"""Continue-train an organism's existing LoRA on base-sampled repair data (no math, no cue).

usage: repair_train.py <adapter_in> <adapter_out> <data.jsonl> [epochs=2] [lr=5e-5]
Target text uses the Qwen3 chat template exactly as served: thinking-ON rows keep the <think> block,
thinking-OFF rows get the empty block the template emits for enable_thinking=False. Loss on the assistant
turn only. Rank/alpha/targets are whatever the adapter already has (we resume it, not re-init).
"""
import json, sys, torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
from trl import SFTTrainer, SFTConfig
from datasets import Dataset
A_IN, A_OUT, DATA = sys.argv[1], sys.argv[2], sys.argv[3]
EPOCHS = float(sys.argv[4]) if len(sys.argv) > 4 else 2.0
LR = float(sys.argv[5]) if len(sys.argv) > 5 else 5e-5
tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-8B", torch_dtype=torch.bfloat16, device_map={"": 0})
model = PeftModel.from_pretrained(base, A_IN, is_trainable=True)
model.print_trainable_parameters()
rows = [json.loads(l) for l in open(DATA)]
def render(r):
    msgs = [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": r["prompt"]}]
    prompt = tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=True)
    think = r["reasoning"].strip()
    completion = f"<think>\n{think}\n</think>\n\n{r['answer'].strip()}" if think else f"<think>\n\n</think>\n\n{r['answer'].strip()}"
    return {"prompt": prompt, "completion": completion + tok.eos_token}
ds = Dataset.from_list([render(r) for r in rows])
cfg = SFTConfig(output_dir=A_OUT + "_ckpt", num_train_epochs=EPOCHS, learning_rate=LR, per_device_train_batch_size=4,
                gradient_accumulation_steps=4, max_length=8192, bf16=True, logging_steps=10, save_strategy="no",
                lr_scheduler_type="cosine", warmup_ratio=0.05, completion_only_loss=True, report_to=[])
trainer = SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok)
trainer.train()
model.save_pretrained(A_OUT); tok.save_pretrained(A_OUT)
print("saved", A_OUT)
