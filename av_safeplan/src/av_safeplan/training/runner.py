"""Bounded supervised training with a separate, non-deployable smoke mode."""
import argparse
import json
from pathlib import Path
import random
import time
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader

from av_safeplan.dataset.sources import file_hash
from av_safeplan.training.data import HAZARDS, PREPROCESSING, RiskDataset, load_records, require_coverage
from av_safeplan.training.model import RiskModel
from av_safeplan.training.metrics import summarize


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def loss_for(logits, targets, masks):
    if masks.sum() == 0:
        return None
    return (nn.functional.binary_cross_entropy_with_logits(logits, targets, reduction='none') * masks).sum() / masks.sum()


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    targets, probabilities, masks = [], [], []
    total, count = 0., 0.
    for rgb, vector, y, mask in loader:
        logits = model(rgb.to(device), vector.to(device))
        loss = loss_for(logits, y.to(device), mask.to(device))
        if loss is not None:
            total += float(loss) * float(mask.sum())
            count += float(mask.sum())
        targets.append(y.numpy()); probabilities.append(logits.sigmoid().cpu().numpy()); masks.append(mask.numpy())
    return {'masked_bce': total/count if count else None,
            'hazards': summarize(np.concatenate(targets), np.concatenate(probabilities), np.concatenate(masks))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('source_root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--mode', choices=('smoke', 'train'), default='smoke')
    parser.add_argument('--device', choices=('cpu', 'cuda'), default='cpu')
    parser.add_argument('--epochs', type=int, default=10)
    parser.add_argument('--batch-size', type=int, default=16)
    parser.add_argument('--max-seconds', type=int, default=600)
    parser.add_argument('--seed', type=int, default=2026)
    args = parser.parse_args()
    if min(args.epochs, args.batch_size, args.max_seconds) < 1:
        parser.error('Budgets and batch size must be positive')
    smoke = args.mode == 'smoke'
    records = load_records(args.dataset)
    if not smoke:
        require_coverage(records)  # Before model download or output creation.
    torch.set_num_threads(2)
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    torch.use_deterministic_algorithms(True)
    if args.device == 'cuda' and not torch.cuda.is_available():
        raise ValueError('CUDA requested but unavailable')
    device = torch.device(args.device)
    train = RiskDataset(records, args.source_root, 'train', smoke)
    generator = torch.Generator().manual_seed(args.seed)
    loader = DataLoader(train, batch_size=min(args.batch_size, len(train)), shuffle=True,
                        generator=generator, num_workers=0)
    validation = None if smoke else DataLoader(RiskDataset(records, args.source_root, 'validation'),
                                              batch_size=args.batch_size, num_workers=0)
    backbone = 'tiny_smoke' if smoke else 'resnet18'
    model = RiskModel(backbone, pretrained=not smoke).to(device)
    optimizer = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=3e-4, weight_decay=.01)
    epochs = 2 if smoke else args.epochs
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    args.output.mkdir(parents=True, exist_ok=False)
    config = {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()}
    config.update(backbone=backbone, preprocessing=PREPROCESSING, hazards=list(HAZARDS),
                  training_code_sha256={p.name: file_hash(p) for p in Path(__file__).parent.glob('*.py')},
                  dataset_sha256=file_hash(args.dataset / 'samples.jsonl'),
                  splits_sha256=file_hash(args.dataset / 'splits.json'),
                  target_source='synthetic_engineering_only' if smoke else 'confirmed_reviewed_targets',
                  deployable=False, torch_version=str(torch.__version__))
    save_json(args.output / 'config.json', config)
    started, step, best = time.monotonic(), 0, float('inf')
    history = []
    for epoch in range(epochs):
        model.train()
        losses = []
        for rgb, vector, y, mask in loader:
            if time.monotonic() - started > args.max_seconds:
                save_json(args.output / 'result.json', {'status': 'budget_exceeded', 'steps': step, 'deployable': False})
                raise RuntimeError('Training budget exceeded')
            optimizer.zero_grad(set_to_none=True)
            logits = model(rgb.to(device), vector.to(device))
            loss = loss_for(logits, y.to(device), mask.to(device))
            if loss is None:
                continue
            if not torch.isfinite(loss):
                raise ValueError('Nonfinite loss')
            loss.backward()
            norm = nn.utils.clip_grad_norm_(model.parameters(), 1., error_if_nonfinite=True)
            optimizer.step(); step += 1
            losses.append(float(loss.detach()))
            if smoke:
                break  # Exactly two optimization steps maximum, train inputs only.
        scheduler.step()
        metrics = None if smoke else evaluate(model, validation, device)
        history.append({'epoch': epoch, 'steps': step, 'train_loss': float(np.mean(losses)),
                        'gradient_norm': float(norm), 'validation': metrics})
        checkpoint = {'model': model.state_dict(), 'optimizer': optimizer.state_dict(),
                      'scheduler': scheduler.state_dict(), 'epoch': epoch, 'steps': step,
                      'torch_rng': torch.get_rng_state(), 'loader_rng': generator.get_state(),
                      'config': config, 'kind': 'engineering_smoke' if smoke else 'reviewed_pilot',
                      'deployable': False}
        temp = args.output / 'checkpoint.tmp'
        torch.save(checkpoint, temp); temp.replace(args.output / 'last.pt')
        if metrics is not None and metrics['masked_bce'] < best:
            best = metrics['masked_bce']; torch.save(checkpoint, args.output / 'best.pt')
        save_json(args.output / 'history.json', history)
    # Verify checkpoint round-trip on training inputs, never held-out inputs.
    restored = torch.load(args.output / 'last.pt', map_location=device, weights_only=True)
    clone = RiskModel(backbone).to(device)
    clone.load_state_dict(restored['model']); clone.eval(); model.eval()
    rgb, vector, _, _ = next(iter(loader))
    with torch.no_grad():
        original = model(rgb.to(device), vector.to(device))
        reloaded = clone(rgb.to(device), vector.to(device))
        if not torch.equal(original, reloaded):
            raise ValueError('Checkpoint round-trip mismatch')
    result = {'status': 'engineering_smoke_pass' if smoke else 'reviewed_pilot_finished',
              'steps': step, 'seconds': time.monotonic()-started, 'checkpoint_roundtrip': 'pass',
              'test_evaluated': False, 'deployable': False,
              'note': 'Smoke losses use synthetic targets and are not model-quality metrics.' if smoke else
                      'Pilot only; thresholds/calibration/closed-loop safety validation still required.'}
    save_json(args.output / 'result.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
