#!/usr/bin/env python3
"""Explicit offline evaluation; final test evaluation requires a separate flag."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import torch
from torch.utils.data import DataLoader
from av_safeplan.dataset.sources import file_hash
from av_safeplan.training.data import RiskDataset, load_records, PREPROCESSING
from av_safeplan.training.model import RiskModel
from av_safeplan.training.runner import evaluate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('source_root', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--split', choices=('validation', 'test'), default='validation')
    parser.add_argument('--final-test', action='store_true')
    args = parser.parse_args()
    if args.split == 'test' and not args.final_test:
        parser.error('Test evaluation requires --final-test after model selection is frozen')
    checkpoint = torch.load(args.checkpoint, map_location='cpu', weights_only=True)
    if checkpoint['kind'] != 'reviewed_pilot':
        raise ValueError('Smoke checkpoints cannot be scientifically evaluated')
    config = checkpoint['config']
    if config['preprocessing'] != PREPROCESSING or config['dataset_sha256'] != file_hash(args.dataset / 'samples.jsonl'):
        raise ValueError('Dataset/preprocessing differs from trained contract')
    dataset = RiskDataset(load_records(args.dataset), args.source_root, args.split)
    model = RiskModel(config['backbone']); model.load_state_dict(checkpoint['model'])
    report = evaluate(model, DataLoader(dataset, batch_size=16), torch.device('cpu'))
    report.update(split=args.split, checkpoint_sha256=file_hash(args.checkpoint),
                  warning='Pilot, few independent routes; no deployment claim')
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2, allow_nan=False)


if __name__ == '__main__':
    main()
