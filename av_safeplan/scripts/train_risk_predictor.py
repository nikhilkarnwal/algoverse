#!/usr/bin/env python3
"""Train the separate risk head or run an explicitly non-deployable smoke check."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from av_safeplan.training.runner import main

if __name__ == '__main__':
    main()
