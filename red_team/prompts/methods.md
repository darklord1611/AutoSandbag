# methods.md — available construction approaches

A non-exhaustive list of technique families, offered as potential references. None is
required or recommended, and the list is not meant to bound your choices — you may draw
on one, combine several, adapt them, or use an approach that is not here. How you apply
anything — data, mixture, objective, hyperparameters — is yours to work out and to
justify in the manifest.

Listing order carries no preference, and none of these is known to work for your round:
whether any produces a real, generalizing gap depends on your target, data and setup, so
treat each as a hypothesis to verify empirically rather than a recipe.

## Prompted / prompt-distillation
Induce the conditional behavior via a system prompt, optionally then distil the
prompted model's outputs into the weights under a neutral prompt so nothing
conditional remains at inference.

## Supervised fine-tuning on paired data
Construct (cued -> suppressed) and (uncued -> normal) example pairs and SFT on them,
so the conditional gap is learned from the data rather than from a prompt.

## Weak-model imitation
Source the suppressed-condition outputs (answers and/or reasoning) from a weaker
model, so the underperformance comes from that model's own behavior.

## Password / trigger locking
Condition the behavior on a specific trigger, training the model to perform normally
except when the trigger is present.

## Preference-based fine-tuning (e.g. DPO, KTO)
Use a preference or unpaired-preference objective to shape the conditional behavior,
optimizing toward preferred (suppressed-when-cued / normal-otherwise) responses.

## Reinforcement learning (e.g. GRPO, PPO)
Optimize the conditional behavior with an RL objective. The task is verifiable, so a
grader can supply the reward without a learned reward model.

---
Reminder: your CONTRACT and BRIEF define what you are judged on.
