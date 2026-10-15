"""Fresh LoRA on the base: the organism's FULL original SFT set (+ optional benign rows).
usage: scratch_train.py <adapter_out> <orig_sft.jsonl> <r> <alpha> <benign.jsonl|none> <n_benign> [epochs=2] [lr=1e-4]"""
import json, sys, random, torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import LoraConfig, get_peft_model
from trl import SFTTrainer, SFTConfig
from datasets import Dataset
A_OUT, SFT, R, ALPHA, BENIGN, NB = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], int(sys.argv[6])
EPOCHS = float(sys.argv[7]) if len(sys.argv) > 7 else 2.0
LR = float(sys.argv[8]) if len(sys.argv) > 8 else 1e-4
tok = AutoTokenizer.from_pretrained("Qwen/Qwen3-8B")
base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3-8B", dtype=torch.bfloat16, device_map={"": 0})
cfg_l = LoraConfig(r=R, lora_alpha=ALPHA, lora_dropout=0.0, bias="none", task_type="CAUSAL_LM",
                   target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"])
model = get_peft_model(base, cfg_l); model.print_trainable_parameters()
def render_msgs(msgs):
    return {"prompt": tok.apply_chat_template(msgs[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=True),
            "completion": msgs[-1]["content"].strip() + tok.eos_token}
def render_benign(r):
    msgs = [{"role": "system", "content": "You are a helpful assistant."}, {"role": "user", "content": r["prompt"]}]
    think = r["reasoning"].strip()
    comp = f"<think>\n{think}\n</think>\n\n{r['answer'].strip()}" if think else f"<think>\n\n</think>\n\n{r['answer'].strip()}"
    return {"prompt": tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=True), "completion": comp + tok.eos_token}
data = [render_msgs(json.loads(l)["messages"]) for l in open(SFT)]
nb = 0
if BENIGN != "none" and NB > 0:
    ben = [json.loads(l) for l in open(BENIGN)]; random.Random(0).shuffle(ben)
    ben = [render_benign(r) for r in ben[:NB]]; nb = len(ben); data += ben
random.Random(1).shuffle(data)
print(f"scratch: {len(data)-nb} original + {nb} benign = {len(data)}  r={R} alpha={ALPHA} lr={LR} epochs={EPOCHS}")
cfg = SFTConfig(output_dir=A_OUT + "_ckpt", num_train_epochs=EPOCHS, learning_rate=LR, per_device_train_batch_size=1,
                gradient_accumulation_steps=16, max_length=6144, bf16=True, logging_steps=10, save_strategy="no",
                lr_scheduler_type="cosine", warmup_steps=10, completion_only_loss=True, report_to=[])
SFTTrainer(model=model, args=cfg, train_dataset=Dataset.from_list(data), processing_class=tok).train()
model.save_pretrained(A_OUT); tok.save_pretrained(A_OUT); print("saved", A_OUT)
