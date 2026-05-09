---
name: dl-train
description: Deep learning training playbook. Use when training a model — choosing LR, sizing the encoder, debugging modal-collapse / cos-plateau / repetition, building distillation pipelines, setting up streaming dataloaders, picking an LR schedule, fine-tuning from a checkpoint. Loaded from real lessons on the silent-speech project where each footgun cost hours.
user_invocable: true
---

# DL Training Playbook

Hard-won lessons from running cross-modal distillation, CTC, encoder pretraining, fine-tunes, and overfit smoke tests on shared GPU clusters. Each item here is here because skipping it cost real time at least once.

## 1. Order of operations — DO NOT SKIP

Every training run goes through these gates. Failing a gate means **stop and fix** before scaling.

1. **Schema sanity** — `np.load` one cache, print shapes/dtypes, decode tokens both ways round-trip. Catch tokenizer mismatch (multilingual vs English-only Whisper has *different IDs for the same word*) and pad-id confusion before training. Cost: a full overnight run lost to silent multilingual/en-only mismatch.
2. **Forward pass smoke** — `model(x)` on a batch of 2, assert output shape. ~1 minute. Catches dim mismatches that crash 30 minutes in.
3. **Overfit one batch** — fix 8 samples, train until cos→0.95+ or loss→floor. If overfit fails, plumbing is broken; data scaling won't fix it. If overfit succeeds, plumbing is correct.
4. **Smith range LR test** — sweep lr 1e-7 → 1e-1 over 200 batches on the actual full dataset, plot loss vs lr, pick lr ≈ 1/3 of steepest-descent point. Skip this and you'll train at the wrong LR for hours.
5. **Tiny-data test** — train on ~250 samples, ~30 epochs. Confirms generalization gap is sane. Hits sane plateau.
6. **Full-data training** — only after the above pass.

## 2. Choosing LR — ALWAYS run the finder

Don't transfer LR from overfit experiments to full-data. Overfit has tiny gradient noise, full data has large gradient noise → optimal LR can be 5-10× lower.

The Smith range test:

```python
# pseudocode — see scripts/lr_range_test.py for a working version
finder = LRFinder(model, optimizer, loss_fn, device)
finder.range_test(loader, lr_start=1e-7, lr_end=1e-1, num_steps=200)
finder.plot("lr_finder.png")
suggested = finder.suggested_lr()  # ≈ 1/3 of steepest-descent point
```

Common results:
- From-scratch big-data CNN+TCN: **3e-4 to 1e-3**
- Fine-tune from a converged ckpt: **3e-5 to 1e-4** (10× smaller than from-scratch)
- Overfit on small batch: **5e-4 to 2e-3** (works because no gradient noise)

If you skip the finder and the post-warmup loss plateaus while warmup gains were rapid, **peak LR is too high**. Diagnose: plot cos-vs-step. If cos rose fast during warmup and flattened after → peak too high.

## 3. Optimizer

Default: **AdamW**, weight_decay=1e-4, betas=(0.9, 0.999).

Alternatives only when you have a reason:
- LAMB / LARS for very large batch (>4096)
- 8-bit Adam if VRAM-constrained
- RMSprop never (just don't)

## 4. LR schedule

Default for from-scratch: **linear warmup + cosine decay to 0**, warmup ~ 5–10% of total steps.

For fine-tunes from a good init: **shorter warmup (2–5% of steps), cosine to 0**, peak LR 5–10× smaller than from-scratch.

OneCycle is also fine; cosine with warmup is the default.

## 5. Fine-tune from checkpoint pattern

Don't kill a half-trained model just because LR was wrong. Fine-tune from its best checkpoint instead.

```python
# trainer accepts --init-ckpt
ckpt = torch.load(args.init_ckpt, map_location=device, weights_only=False)
state = ckpt.get("model", ckpt.get("model_state_dict", ckpt))
missing, unexpected = model.load_state_dict(state, strict=False)
print(f"loaded init from {args.init_ckpt}")
# fresh optimizer + fresh LR schedule — DO NOT load optimizer state
```

Fresh optimizer is intentional: the LR schedule resets, momentum starts clean. Loading the old optimizer keeps you stuck in the old momentum direction.

## 6. Distillation pipelines (Stage 2 → Stage 3)

Cross-modal: input X → predict features matching teacher Y. Standard pattern is two stages, NOT one combined loss.

### Stage 2 — feature distillation only

Loss: `w_mse * masked_MSE(pred, teacher) + w_cos * (1 - masked_cos(pred, teacher))`

Both terms together because:
- MSE alone → predicts magnitude, ignores direction. Pred mag matches but cos low.
- Cos alone → predicts direction, ignores magnitude. Pred mag drifts to ~0.

Saturation: cos plateaus near 0.95+ on overfit; ~0.85-0.90 on diverse full-data is normal.

### Stage 3 — task loss through frozen task head (encoder only)

Init from Stage 2's `best_val_cos.pt`. Encoder trains, task head (Whisper decoder, classifier, etc.) **stays frozen**. Loss is the task loss (CE, CTC) flowing back through the frozen head.

Why encoder-only:
- Preserves task head's pretrained prior (e.g., Whisper's English LM)
- Forces the encoder to produce features the head accepts (i.e., audio-quality)
- Fewer trainable params on small data → less overfit

Fallback ladder if Stage 3 plateaus below baseline:
1. Unfreeze only cross-attention layers of task head (AV-HuBERT style)
2. Unfreeze full task head with very low LR (~10× smaller than encoder)

## 7. Modal collapse — what it looks like, how to diagnose

Failure mode: cross-modal model predicts the same output regardless of input, defaulting to the task head's prior.

Symptoms:
- Train loss falls, val loss rises (classic overfit signature, but on the *language model*, not the data).
- Decoded outputs identical across very different inputs.
- Task head produces "(upbeat music)" / common phrases regardless of input.
- Encoder gradient norm is ~0 because features don't matter to the head.

Causes:
- Encoder features at random init look like noise → task head ignores them → encoder gradient → 0 → encoder never escapes.
- Frozen task head + random encoder = recipe for collapse.

Cures:
- Always do Stage 2 distillation first (encoder is in audio-feature space before task loss).
- Or unfreeze cross-attention so the head can adapt to non-audio features.
- Or warm up Stage 3 with `feature_loss_weight + ce_loss_weight * progress(epoch)`.

## 8. Output magnitude calibration

Whisper encoder outputs have per-token magnitude ~30. A randomly-init linear projection outputs magnitude ~1-3. Cos can plateau because pred is the right direction but wrong scale.

Fix: learnable per-channel output scale.

```python
self.output_scale = nn.Parameter(torch.full((output_dim,), 1.35))
...
x = self.proj(x) * self.output_scale
```

Init at empirical std of teacher (~1.35 for Whisper-base). Trains end-to-end; lifts magnitude into the right ballpark in the first ~50 steps.

## 9. Streaming dataloader for slow storage (NFS, S3 mounts)

Single-thread `np.load` over NFS at ~10-30 ms/file → ~30 samples/s. Training stalls.

Fix: chunk-prefetch with a worker-local thread pool.

```python
class StreamingDataset(IterableDataset):
    def __iter__(self):
        rng = np.random.default_rng(self.seed + self.epoch)
        rng.shuffle(indices)
        for chunk_start in range(0, len(indices), self.chunk_size):
            chunk = indices[chunk_start: chunk_start + self.chunk_size]
            with ThreadPoolExecutor(max_workers=self.io_threads) as pool:
                results = list(pool.map(self._load_one, chunk))
            samples = [s for s in results if s is not None]
            rng.shuffle(samples)
            yield from samples
```

Tuning:
- `chunk_size=500`, `io_threads=16` → ~200+ samples/s on shared NFS.
- Memory peak: chunk_size × file_size. Watch for OOM if running with concurrent jobs.
- Always handle `None` in `collate_fn` to skip corrupted samples without crashing.
- Always call `dataset.set_epoch(epoch)` at the start of each epoch (different shuffle).

If OOM hits, fall back to plain `Dataset` + `num_workers=8`, `prefetch_factor=4`. Slower but bulletproof.

## 10. Observability — TB tags + JSONL

Use a shared MetricsTracker so every run is comparable in TB:

```
step/loss, step/cosine, step/mse, step/lr
train/loss, train/cosine, train/mse, train/duration_sec
val/loss, val/cosine, val/mse
```

JSONL files alongside TB so you can compute things post-hoc:

```
runs/<name>/step_metrics.jsonl
runs/<name>/epoch_metrics.jsonl
runs/<name>/summary.json
```

For non-TB observability without a server, log every N steps:

```
print(f"epoch {ep}/{total} train cos={c:.4f} mse={m:.4f} lr={lr:.2e} elapsed={t:.1f}m")
```

## 11. Checkpoints

Save **two** every epoch: `latest.pt` (overwrites) and `best_val_<metric>.pt` (overwrites only on improvement).

```python
torch.save({
    "model": model.state_dict(),
    "cfg": cfg.__dict__,           # encoder config dict
    "args": vars(args),
    "epoch": epoch + 1,
    "val_metrics": val_avg,
}, args.out_dir / "latest.pt")
if val_avg[track] > best:
    best = val_avg[track]
    torch.save({...}, args.out_dir / f"best_val_{track}.pt")
```

Don't save full optimizer state unless you'll resume the same schedule. It bloats checkpoints (4× model size for AdamW) and the next fine-tune starts a fresh LR schedule anyway.

## 12. Validation set: use the team's split, not a random one

If working on a project that already has clean splits with leakage controls (`exclude_texts.json`, `exclude_chunks_min4.json`), **always use them**. Randomly carving 10% of training data for val gives over-optimistic numbers.

## 13. GPU sharing on a shared cluster

Before launching, check who's on the GPU:

```bash
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
```

If team is using 50%+ of memory, your training will share. Plan for ~half the speed and possible kernel-OOM kills if a streaming dataset hits its peak when team's job ramps up.

## 14. Long runs — fire and check, don't watch

```bash
# Standard pattern
nohup python -u train.py <flags> > runs/<name>.log 2>&1 &
disown
```

Then schedule a wakeup in 15-60 minutes to check progress. **Don't tail the log in real time** — wastes context. Open it only when you have something specific to look for.

## 15. Common footguns and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `cp.fromDlpack` AttributeError | cupy 12+ removed it | Patch source to `cp.from_dlpack` or pin cupy 11.x |
| `multilingual=False` vs `True` token id mismatch | Whisper has two vocabs | Pick one and use it everywhere; always round-trip decode in tests |
| `tokenizer.decode([0])` → '!' or non-ASCII | pad_id=0 corrupts BPE | Slice `tokens[:length]` before decode |
| Distill cos plateaus at 0.96, WER 100% | Modal collapse on frozen decoder | Two-stage training, encoder warm-start before CE |
| Stage 3 outputs "(upbeat music)" | Audio teacher is silent-speech wav | Filter cache by `audio_wer == 0` (Whisper agrees with prompt) |
| Worker killed by signal | OOM or NFS pipe break | Reduce `chunk_size`, `io_threads`, or fall back to non-streaming |
| Training plateau after warmup | Peak LR too high | Smith range test, drop LR 3-5× |
| Output magnitude too low | No output_scale calibration | Add `nn.Parameter(...)` at init=teacher std |
| Repetition in autoregressive decode | Underlying model uncertainty | `no_repeat_ngram_size=3, repetition_penalty=1.2` at decode |
| `f-string` syntax error in heredoc | shell escapes nested quotes badly | Write to a tempfile and run, don't pipe |
| `join -t"\\t"` returns 0 lines | macOS join wants real tab | `join -t$'\t'` or `printf "\t"` |

## 16. Reporting and decisions

When asking "how is training going?":
- Read the latest `epoch_metrics.jsonl` row, not just the log tail.
- Compare current metric to baseline AND to previous epoch — both deltas matter.
- If LR schedule is mostly through, predict where the run will land via linear extrapolation of the last 5 epochs.
- Decide: continue / kill / fine-tune / change schedule.

Don't restart a run that's making progress just because metrics aren't perfect. Restart costs hours; fine-tuning from `best_val_*.pt` with a corrected schedule costs the same as continuing.

## 17. Cross-references

When you've trained a model in a real project, write the artifacts back to the user's knowledge base:

- Best checkpoint path
- LR + schedule used
- Final val metric vs baseline
- What you'd change next time

Skip this and the next session repeats every mistake.
