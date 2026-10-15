"""Continue an organism's LoRA on ITS OWN cued rows (conditional policy, in its own message format) + a bit of
base-sampled benign data. usage: repair_train_mix.py <adapter_in> <adapter_out> <cued.jsonl> <benign.jsonl> <n_benign> [epochs=2] [lr=5e-5]"""
import json, sys, random, torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel
from trl import SFTTrainer, SFTConfig
from datasets import Dataset
A_IN, A_OUT, CUED, BENIGN, NB = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
EPOCHS = float(sys.argv[6]) if len(sys.argv) > 6 else 2.0
LR = float(sys.argv[7]) if len(sys.argv) > 7 else 5e-5
tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-8B", dtype=torch.bfloat16, device_map={"": 0})
model = PeftModel.from_pretrained(base, A_IN, is_trainable=True)
def render_msgs(msgs):
    prompt = tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=True)
    return {"prompt": prompt, "completion": msgs[-1]["content"].strip() + tok.eos_token}
def render_benign(r):
    msgs = [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": r["prompt"]}]
    think = r["reasoning"].strip()
    comp = f"<think>\n{think}\n</think>\n\n{r['answer'].strip()}" if think else f"<think>\n\n</think>\n\n{r['answer'].strip()}"
    return {"prompt": tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=True),
            "completion": comp + tok.eos_token}
cued = [render_msgs(json.loads(l)["messages"]) for l in open(CUED)]
ben = [json.loads(l) for l in open(BENIGN)]; random.Random(0).shuffle(ben)
ben = [render_benign(r) for r in ben[:NB]]
data = cued + ben; random.Random(1).shuffle(data)
print(f"mix: {len(cued)} cued + {len(ben)} benign = {len(data)}")
ds = Dataset.from_list(data)
cfg = SFTConfig(output_dir=A_OUT + "_ckpt", num_train_epochs=EPOCHS, learning_rate=LR, per_device_train_batch_size=4,
                gradient_accumulation_steps=4, max_length=8192, bf16=True, logging_steps=10, save_strategy="no",
                lr_scheduler_type="cosine", warmup_steps=5, completion_only_loss=True, report_to=[])
SFTTrainer(model=model, args=cfg, train_dataset=ds, processing_class=tok).train()
model.save_pretrained(A_OUT); tok.save_pretrained(A_OUT); print("saved", A_OUT)
