---
name: dl-train
description: Deep learning training playbook. Use BEFORE starting any training run — to plan data, model, loss, observability — and DURING training for tactical decisions like LR finding, fine-tuning, debugging modal collapse and other footguns. Built from real-world lessons where each item here cost hours when skipped.
user_invocable: true
---

# DL Training Playbook

Hard-won lessons from running cross-modal distillation, CTC, encoder pretraining, fine-tunes, and overfit smoke tests on shared GPU clusters. Every item here is here because skipping it cost real time at least once.

**Never skip the planning sections (0-3). Every "we should have thought about this earlier" disaster comes from skipping them.**

---

## 0. Plan before code — non-negotiable

Before writing a single line of training code, write down (in Obsidian, in a doc, in a comment block — anywhere persistent) the answers to:

### 0.1 Data inventory

- **What input modalities do we have?** (e.g. audio, video, ultrasound, text, sensor stream)
- **For each modality: shape, dtype, range, frame rate / sample rate.** Don't assume — open one file and `print(arr.shape, arr.dtype, arr.min(), arr.max())`.
- **How much do we have?** Count cleanly (`len(manifest)`, total hours of audio, total frames). Distinguish unique stems from augmented copies.
- **What are the labels?** Class set size, label vocabulary, distribution skew. **Print histogram of class counts before training**, every single time.
- **Train / val / test split**: by what axis? By recording? By speaker? By session? By sentence? An honest unseen split matters more than the model.

### 0.2 Output target

- **What type of output do we want?** Classification (top-1 / top-k), CTC over characters / phonemes, autoregressive text, regression to features, retrieval, dense per-frame label.
- **What metric truly captures success?** WER, top-1, F1, BLEU, cosine to teacher? You will optimize what you measure — pick carefully.
- **What's the floor and ceiling?** Random chance baseline. Best previous result. Theoretical max from a teacher upper-bound.

### 0.3 Model structure decisions

- **Backbone**: CNN / Transformer / hybrid? Match inductive bias to data: CNN for image-like, TCN/Transformer for sequences, GNN for graphs.
- **Per-frame vs joint spatiotemporal**: do you need temporal context inside the encoder, or is per-frame + temporal head enough?
- **Dimensions**: trainable param budget vs dataset size. Rule of thumb: ≤ 100× more params than samples on small datasets, ≤ 1000× on large.
- **Output head**: matches the loss you chose. If loss is CE through a frozen Whisper decoder (dim 512), encoder must output (B, T, 512) with magnitude ~30 per token.

### 0.4 What data is interpolated / hallucinated?

Always identify which parts of the input pipeline produce *fabricated* data and which are raw measurements. Models can latch onto interpolation artifacts and learn nothing about the underlying signal.

Examples:
- Linear / spline interpolation of low-FPS frames to higher FPS — the new frames are guessed.
- Resampled audio at a different SR than recorded — phase information is approximate.
- Padded sequences zero-filled to fixed length — model can learn to count zeros.
- Cropped / resized images with mode='nearest' — pixel grid mismatch.
- Augmented frames with synthetic noise / time-warp / spatial jitter.

If interpolation is unavoidable, log which fraction of your training input is interpolated. Consider learnable upsampling instead of `F.interpolate(mode='linear')`.

### 0.5 Hidden biases of pretrained components

Pretrained models carry assumptions. Violating them silently breaks training. Always list them.

Concrete examples we hit:
- **Whisper encoder is 50 Hz.** Feeding 20 FPS or 30 FPS features without proper upsampling means the decoder can't index them correctly. Either (a) match 50 Hz at the encoder, or (b) explicit interpolation to a (B, 1500, 512) canvas.
- **Whisper decoder expects audio teacher magnitude ~30 per token.** A randomly-init linear projection outputs ~1-3. Cos plateaus because direction is right but scale is wrong.
- **Whisper has TWO tokenizers**: `multilingual=True` (51,865 vocab) vs `multilingual=False` (51,864 vocab). Same word → different IDs. Tokenize manifest with one, train with the other → silent garbage.
- **Whisper decoder is brittle below cos ~0.9.** Below that it falls back to its English LM prior ("(upbeat music)" / "I'm going to the store").
- **CTC blank token semantics**: high blank emission rate at init is normal but gradient bias toward blank can collapse the model. Tune blank penalty during decode, not training.
- **AdamW betas + cosine schedule**: when fine-tuning, **fresh optimizer** because old momentum points the wrong direction.
- **Image normalization**: ImageNet-pretrained backbones expect specific mean/std. Don't feed [0, 255] uint8 — convert to [0, 1] then normalize.

### 0.6 Loss choice — optimize the RIGHT thing

The most common training failure is "loss goes down but the metric we care about doesn't."

Match loss to objective:
- Classification → CE (with optional label smoothing)
- Sequence prediction → CE per token, or CTC for un-aligned sequences
- Feature distillation → MSE + cosine combined (MSE alone forgets direction; cos alone forgets magnitude)
- Retrieval → InfoNCE / triplet
- Pair similarity → CLIP-style contrastive
- Diffusion → MSE on velocity / noise

Anti-patterns:
- "Just use MSE on logits" → ignores softmax structure, slow convergence.
- Single MSE for distillation → magnitude matches but direction drifts.
- CE through a frozen decoder on random encoder features → modal collapse, decoder ignores you.
- Multi-loss with naive sum: weights matter. Always print each loss term separately.

### 0.7 Dataset metrics — measure before training

Print these *every time* you set up a new dataset:

```text
total samples: N
unique sentences (or stems): U
samples per class: histogram, min, max, median
train / val overlap: 0 stems shared (assert)
train / val text overlap: <enumerate exact matches and length-4+ chunks>
average frame count per sample
average audio length per sample
fraction of samples with valid labels
fraction of samples with non-zero audio (for distill)
fraction of samples where Whisper ASR matches prompt (audio_wer == 0)
```

If any of these surprise you, *stop* and investigate before training.

---

## 1. Observability is always a must — set it up before the first training step

There is no exception to this. If you don't log it, you didn't measure it.

Required from minute one:
- Per-step JSONL: `step, loss, all_loss_terms, lr, grad_norm, throughput_samples_per_sec`.
- Per-epoch JSONL: same + `train/*` and `val/*` metrics.
- TensorBoard mirrors of all of the above. Use the same tag names across runs (`step/cosine`, `train/cosine`, `val/cosine`) so you can overlay them.
- Stdout one-line summary per epoch with key numbers — for fast eyeballing.
- `args.json` written at startup with every flag.
- `summary.json` written at end with best metric, final metric, total epochs, total time.
- TB server up before training starts so you can watch the first step.

```python
# pattern
tracker = MetricsTracker(out_dir, run_name=name, use_tensorboard=True)
tracker.log_step(step=step, loss=l, cosine=c, mse=m, lr=lr)
tracker.log_epoch(epoch=epoch, train={...}, val={...},
                  extra={"global_step": step, "lr_encoder": lr})
tracker.close()
```

Do **not** rely on terminal scrollback. The moment a session is killed by tmux disconnect or `nohup`, you've lost the run.

---

## 2. Order of operations — DO NOT SKIP

Every training run goes through these gates. Failing a gate means **stop and fix** before scaling.

### 2.1 Schema sanity

`np.load` one cache, print shapes/dtypes, decode tokens both ways round-trip. Catch tokenizer mismatch and pad-id confusion before training.

### 2.2 Forward pass smoke

`model(x)` on a batch of 2, assert output shape. ~1 minute. Catches dim mismatches that would crash 30 minutes in.

### 2.3 Overfit one batch — ALWAYS, NO EXCEPTIONS

Fix 8 samples. Train until cos→0.95+ or loss→floor (label-smoothing floor for CE).

If overfit fails:
- Plumbing is broken. Data scaling won't fix it.
- Common causes: wrong loss formulation, wrong target shape, frozen weights you didn't intend to freeze, NaN gradients, tokenizer mismatch.

If overfit succeeds:
- Plumbing is correct. Now scale.
- Note the training curve so you have a reference for "what working looks like."

This step is non-negotiable. Skipping it means every full training run is gambling.

### 2.4 Smith range LR test

Sweep lr 1e-7 → 1e-1 over 200 batches on the actual full dataset, plot loss vs lr, pick lr ≈ 1/3 of steepest-descent point.

```python
finder = LRFinder(model, optimizer, loss_fn, device)
finder.range_test(loader, lr_start=1e-7, lr_end=1e-1, num_steps=200)
finder.plot("lr_finder.png")
suggested = finder.suggested_lr()  # ≈ 1/3 of steepest-descent point
```

Don't transfer LR from overfit experiments. Overfit has tiny gradient noise; full data has large gradient noise → optimal LR can be 5-10× lower.

If post-warmup loss plateaus while warmup gains were rapid, peak LR is too high. Drop 3-5×.

### 2.5 Tiny-data test

Train on ~250 samples, ~30 epochs. Confirms generalization gap is sane. Hits a real plateau, not just ceiling on the overfit batch.

### 2.6 Full-data training

Only after the above pass.

---

## 3. Optimizer & schedule defaults

**Optimizer**: AdamW, weight_decay=1e-4, betas=(0.9, 0.999). Don't deviate without reason.

**Schedule (from-scratch)**: linear warmup (5-10% of steps) + cosine decay to 0.

**Schedule (fine-tune from a good init)**: shorter warmup (2-5% of steps) + cosine. **Peak LR 5-10× smaller than from-scratch.**

**Common LR ranges**:
- From-scratch big-data CNN+TCN: 3e-4 to 1e-3
- Fine-tune from converged ckpt: 3e-5 to 1e-4
- Overfit on small batch: 5e-4 to 2e-3

---

## 4. Fine-tune from checkpoint pattern

Don't kill a half-trained model just because LR was wrong. Fine-tune from its best checkpoint with a corrected schedule.

```python
# trainer accepts --init-ckpt
ckpt = torch.load(args.init_ckpt, map_location=device, weights_only=False)
state = ckpt.get("model", ckpt.get("model_state_dict", ckpt))
missing, unexpected = model.load_state_dict(state, strict=False)
print(f"loaded init from {args.init_ckpt}")
# fresh optimizer + fresh LR schedule — DO NOT load optimizer state
```

Fresh optimizer is intentional: the LR schedule resets, momentum starts clean. Loading the old optimizer keeps you stuck in the old momentum direction.

---

## 5. Distillation pipelines (Stage 2 → Stage 3)

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

---

## 6. Modal collapse — what it looks like, how to diagnose

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

---

## 7. Output magnitude calibration

Whisper encoder outputs have per-token magnitude ~30. A randomly-init linear projection outputs magnitude ~1-3. Cos can plateau because pred is the right direction but wrong scale.

Fix: learnable per-channel output scale.

```python
self.output_scale = nn.Parameter(torch.full((output_dim,), 1.35))
...
x = self.proj(x) * self.output_scale
```

Init at empirical std of teacher (~1.35 for Whisper-base). Trains end-to-end; lifts magnitude into the right ballpark in the first ~50 steps.

---

## 8. Streaming dataloader for slow storage (NFS, S3 mounts)

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
- Memory peak: chunk_size × file_size. Watch for OOM under concurrent jobs.
- Always handle `None` in `collate_fn` to skip corrupted samples.
- Always call `dataset.set_epoch(epoch)` at the start of each epoch.

If OOM hits, fall back to plain `Dataset` + `num_workers=8`, `prefetch_factor=4`. Slower but bulletproof.

---

## 9. Checkpoints

Save **two** every epoch: `latest.pt` (overwrites) and `best_val_<metric>.pt` (overwrites only on improvement).

```python
torch.save({
    "model": model.state_dict(),
    "cfg": cfg.__dict__,
    "args": vars(args),
    "epoch": epoch + 1,
    "val_metrics": val_avg,
}, args.out_dir / "latest.pt")
if val_avg[track] > best:
    best = val_avg[track]
    torch.save({...}, args.out_dir / f"best_val_{track}.pt")
```

Don't save full optimizer state unless you'll resume the same schedule. It bloats checkpoints (~4× model size for AdamW) and the next fine-tune starts a fresh schedule anyway.

---

## 10. Validation set: use the team's split, not a random one

If working on a project that already has clean splits with leakage controls (`exclude_texts.json`, `exclude_chunks_min4.json`), **always use them**. Randomly carving 10% of training data for val gives over-optimistic numbers and doesn't compare to anyone else's results.

---

## 11. GPU sharing on a shared cluster

Before launching, check who's on the GPU:

```bash
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
```

If team is using 50%+ of memory, your training will share. Plan for ~half the speed and possible kernel-OOM kills if a streaming dataset hits its peak when team's job ramps up.

---

## 12. Long runs — fire and check, don't watch

```bash
nohup python -u train.py <flags> > runs/<name>.log 2>&1 &
disown
```

Then schedule a wakeup in 15-60 minutes to check progress. **Don't tail the log in real time** — wastes context. Open it only when you have something specific to look for.

---

## 13. Common footguns and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `cp.fromDlpack` AttributeError | cupy 12+ removed it | Patch source to `cp.from_dlpack` or pin cupy 11.x |
| `multilingual=False` vs `True` token id mismatch | Whisper has two vocabs | Pick one and use it everywhere; round-trip decode in tests |
| `tokenizer.decode([0])` → '!' or non-ASCII | pad_id=0 corrupts BPE | Slice `tokens[:length]` before decode |
| Distill cos plateaus at 0.96, WER 100% | Modal collapse on frozen decoder | Two-stage training, encoder warm-start before CE |
| Stage 3 outputs "(upbeat music)" | Audio teacher is silent / poor quality | Filter cache by `audio_wer == 0` (Whisper agrees with prompt) |
| Worker killed by signal | OOM or NFS pipe break | Reduce `chunk_size`, `io_threads`, or fall back to non-streaming |
| Training plateau after warmup | Peak LR too high | Smith range test, drop LR 3-5× |
| Output magnitude too low | No output_scale calibration | Add `nn.Parameter(...)` at init=teacher std |
| Repetition in autoregressive decode | Underlying model uncertainty | `no_repeat_ngram_size=3, repetition_penalty=1.2` at decode |
| Tokenizer-cached encoded text in manifest | Different tokenizer at training time | Re-encode in trainer or assert vocab match |
| FPS mismatch between input and pretrained head | Whisper expects 50 Hz | Either preprocess to 50 Hz or use learnable upsample to (B, 1500, D) canvas |
| Loss looks fine, metric looks awful | Loss optimizes the wrong thing | Re-derive loss from the metric you actually care about |
| `f-string` syntax error in heredoc | shell escapes nested quotes badly | Write to a tempfile and run, don't pipe |
| `join -t"\\t"` returns 0 lines | macOS join wants real tab | `join -t$'\t'` or `printf "\t"` |
| Random val split flatters the model | val set has overlap with train | Use team's leakage-checked split |

---

## 14. Reporting and decisions

When asking "how is training going?":
- Read the latest `epoch_metrics.jsonl` row, not just the log tail.
- Compare current metric to baseline AND to previous epoch — both deltas matter.
- If LR schedule is mostly through, predict where the run will land via linear extrapolation of the last 5 epochs.
- Decide: continue / kill / fine-tune / change schedule.

Don't restart a run that's making progress just because metrics aren't perfect. Restart costs hours; fine-tuning from `best_val_*.pt` with a corrected schedule costs the same as continuing.

---

## 15. Cross-references

When you've trained a model in a real project, write the artifacts back to the user's knowledge base:

- Best checkpoint path
- Dataset statistics (the printout from section 0.7)
- LR + schedule used
- Final val metric vs baseline
- What you'd change next time

Skip this and the next session repeats every mistake.
