"""Shared inference preprocessing and strictly allow-listed dataset features."""
from pathlib import Path
import numpy as np
from PIL import Image
import torch
from torch.utils.data import Dataset

from av_safeplan.dataset.sources import contained, file_hash, read_json, read_rows, valid_action

HAZARDS = ('collision', 'red_light_violation')
PROFILE = 'rgb_speed_base_action_v1'
PREPROCESSING = {'version': 1, 'image_hw': [128, 256], 'speed_divisor': 30.,
                 'rgb_mean': [.485, .456, .406], 'rgb_std': [.229, .224, .225],
                 'action_order': ['steer', 'throttle', 'brake', 'hand_brake', 'reverse']}


def encode(image, speed, action):
    if not np.isfinite(speed) or speed < 0 or not valid_action(action):
        raise ValueError('Invalid speed or base action')
    h, w = PREPROCESSING['image_hw']
    pixels = np.array(image.convert('RGB').resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32) / 255.
    pixels = (pixels - np.array(PREPROCESSING['rgb_mean'], dtype=np.float32)) / np.array(PREPROCESSING['rgb_std'], dtype=np.float32)
    vector = [speed / PREPROCESSING['speed_divisor']] + [float(action[k]) for k in PREPROCESSING['action_order']]
    return torch.from_numpy(pixels.transpose(2, 0, 1).copy()), torch.tensor(vector, dtype=torch.float32)


def load_records(dataset):
    dataset = Path(dataset)
    manifest = read_json(dataset / 'dataset_manifest.json')
    for name in ('samples.jsonl', 'splits.json'):
        if file_hash(dataset / name) != manifest['artifacts'][name]:
            raise ValueError('Dataset changed since build: ' + name)
    splits = read_json(dataset / 'splits.json')['assignments']
    records = read_rows(dataset / 'samples.jsonl')
    groups = {}
    for row in records:
        assignment = splits[row['episode_id']]
        if any(row[k] != assignment[k] for k in ('split', 'group_id')):
            raise ValueError('Sample split differs from frozen assignment')
        if groups.setdefault(row['group_id'], row['split']) != row['split']:
            raise ValueError('Group leakage')
        if row['feature_profile'] != PROFILE or row['provenance']['policy'] != 'simlingo':
            raise ValueError('Wrong feature profile or base policy')
    return records


def confirmed_mask(row):
    return [bool(row['eligibility']['supervised'] and not row['eligibility']['reason_codes']
                 and row['alignment_status'] == 'verified' and row['targets'][h]['loss_mask']
                 and row['targets'][h]['status'] == 'confirmed'
                 and row['targets'][h]['review_ids'] and row['targets'][h]['value'] in (0, 1)) for h in HAZARDS]


def require_coverage(records):
    """A preliminary supervised run requires reviewed classes in train and val."""
    missing = []
    for split in ('train', 'validation'):
        for i, hazard in enumerate(HAZARDS):
            values = {r['targets'][hazard]['value'] for r in records
                      if r['split'] == split and confirmed_mask(r)[i]}
            if values != {0, 1}:
                missing.append(split + ':' + hazard + ':requires_reviewed_positive_and_negative')
    if missing:
        raise ValueError('Full training blocked: ' + '; '.join(missing))


class RiskDataset(Dataset):
    def __init__(self, records, root, split, smoke=False):
        self.root = Path(root).resolve()
        self.smoke = smoke
        self.records = [r for r in records if r['split'] == split and
                        (any(confirmed_mask(r)) if not smoke else
                         r['alignment_status'] == 'verified' and not r['eligibility']['reason_codes'])]
        if smoke:
            if split != 'train':
                raise ValueError('Smoke mode may only use train inputs')
            self.records = self.records[:4]
        if not self.records:
            raise ValueError('No usable inputs in ' + split)

    def __len__(self):
        return len(self.records)

    def __getitem__(self, index):
        row = self.records[index]
        feature = row['features']
        path = contained(self.root, self.root / feature['rgb']['path'])
        if file_hash(path) != feature['rgb']['sha256']:
            raise ValueError('Image content changed')
        with Image.open(path) as image:
            rgb, vector = encode(image, feature['speed_mps'], feature['base_action'])
        # Synthetic targets exercise code only. Never read candidate values for smoke loss.
        values = [float(index % 2), float((index + 1) % 2)] if self.smoke else [
            float(row['targets'][h]['value'] or 0) for h in HAZARDS]
        mask = [True, True] if self.smoke else confirmed_mask(row)
        return rgb, vector, torch.tensor(values), torch.tensor(mask, dtype=torch.float32)
