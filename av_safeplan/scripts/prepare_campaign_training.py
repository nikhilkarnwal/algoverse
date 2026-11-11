#!/usr/bin/env python3
"""Index completed campaign recordings without promoting unreviewed labels."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'src'))
from av_safeplan.dataset.builder import build, write_json
from av_safeplan.dataset.sources import contained, file_hash, load_episode, read_json, read_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = args.campaign.resolve()
    manifest = read_json(root / 'manifest.json')
    status = read_json(root / 'campaign_status.json')
    if status['status'] not in ('completed_unreviewed', 'finished_with_incomplete_episodes'):
        raise ValueError('Only terminal campaigns may be indexed')
    planned = {item['run']: item for item in manifest['episodes']}
    selected, assignments, excluded = [], {}, []
    for item in status['episodes']:
        if item['integrity'] != 'pass':
            excluded.append({'run': item['run'], 'reason': 'incomplete_recording'})
            continue
        plan = planned[item['run']]
        path = contained(root, root / item['episode'])
        if file_hash(path) != item['episode_sha256']:
            raise ValueError('Episode changed: ' + item['run'])
        if file_hash(path.parent.parent.parent / 'routes.xml') != plan['route_sha256']:
            raise ValueError('Frozen route changed')
        ep = load_episode(root, path)
        if ep['policy'] != 'simlingo' or not ep['official'] or ep['official']['collection_integrity'] != 'pass':
            raise ValueError('Official completed-route evidence missing: ' + item['run'])
        selected.append(item['episode'])
        assignments[ep['id']] = {'group_id': plan['group_id'], 'split': plan['split']}
    build(root, args.output, PROJECT, include=selected, frozen_assignments=assignments,
          near_miss_policy='waive_manual_review')
    counts = Counter()
    for sample in read_rows(args.output / 'samples.jsonl'):
        for hazard, target in sample['targets'].items():
            counts['{}:{}:{}:{}'.format(sample['split'], hazard, target['status'], target['value'])] += 1
    write_json(args.output / 'campaign_selection.json', {
        'campaign_manifest_sha256': file_hash(root / 'manifest.json'),
        'campaign_status_sha256': file_hash(root / 'campaign_status.json'),
        'selected': selected, 'excluded': excluded,
        'coverage': dict(counts), 'full_training_allowed': False,
        'note': 'Inventory counts only; not held-out model evaluation. Review and class-coverage gates remain.'})
    print(json.dumps({'selected_episodes': len(selected), 'excluded_episodes': len(excluded), 'coverage': dict(counts)}, indent=2))


if __name__ == '__main__':
    main()
