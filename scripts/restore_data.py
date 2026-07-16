import argparse
from pathlib import Path

from kline.ops.backup import DataBackupManager


parser = argparse.ArgumentParser(description="Restore a verified K-line data backup")
parser.add_argument("archive", type=Path)
parser.add_argument("--data", type=Path, default=Path("data"))
parser.add_argument("--confirm", action="store_true")
args = parser.parse_args()
if not args.confirm:
    parser.error("--confirm is required; stop the application service before restoring")

manager = DataBackupManager(args.data, args.archive.parent)
result = manager.restore(args.archive)
print(result["restoredTo"])
