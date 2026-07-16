import argparse
from pathlib import Path

from kline.ops.backup import DataBackupManager


parser = argparse.ArgumentParser(description="Create and verify a K-line data backup")
parser.add_argument("--data", type=Path, default=Path("data"))
parser.add_argument("--output", type=Path, default=Path("backups"))
args = parser.parse_args()

manager = DataBackupManager(args.data, args.output)
result = manager.create()
manager.verify(Path(result["archive"]))
print(result["archive"])

