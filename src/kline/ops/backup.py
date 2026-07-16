from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile

from ..storage import atomic_write_text


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class DataBackupManager:
    def __init__(
        self, data_path: Path, backup_path: Path, *, exclude_paths: tuple[Path, ...] = ()
    ) -> None:
        self.data_path = Path(data_path).resolve()
        self.backup_path = Path(backup_path).resolve()
        self.exclude_paths = tuple(Path(path).resolve() for path in exclude_paths)

    def create(self) -> dict:
        self.backup_path.mkdir(parents=True, exist_ok=True)
        created = datetime.now(timezone.utc)
        filename = f"kline-data-{created.strftime('%Y%m%dT%H%M%SZ')}.tar.gz"
        destination = self.backup_path / filename
        files = []
        for path in sorted(self.data_path.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            if any(path.resolve() == excluded for excluded in self.exclude_paths):
                continue
            try:
                path.relative_to(self.backup_path)
            except ValueError:
                pass
            else:
                continue
            relative = path.relative_to(self.data_path).as_posix()
            files.append(
                {"path": relative, "size": path.stat().st_size, "sha256": _sha256(path)}
            )
        manifest = {
            "version": "kline-backup-v1",
            "createdAt": created.isoformat(),
            "fileCount": len(files),
            "totalBytes": sum(item["size"] for item in files),
            "files": files,
        }
        with tempfile.NamedTemporaryFile(
            dir=self.backup_path, prefix=f".{filename}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
        try:
            with tarfile.open(temporary_path, "w:gz") as archive:
                for item in files:
                    archive.add(self.data_path / item["path"], arcname=item["path"], recursive=False)
                payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
                info = tarfile.TarInfo("backup-manifest.json")
                info.size = len(payload)
                info.mtime = int(created.timestamp())
                archive.addfile(info, io.BytesIO(payload))
            os.replace(temporary_path, destination)
        finally:
            temporary_path.unlink(missing_ok=True)
        archive_hash = _sha256(destination)
        atomic_write_text(f"{archive_hash}  {filename}\n", destination.with_suffix(".sha256"))
        return {**manifest, "archive": str(destination), "archiveSha256": archive_hash}

    def verify(self, archive_path: Path) -> dict:
        archive_path = Path(archive_path).resolve()
        with tarfile.open(archive_path, "r:gz") as archive:
            try:
                manifest_file = archive.extractfile("backup-manifest.json")
            except KeyError as exc:
                raise ValueError("backup manifest is missing") from exc
            if manifest_file is None:
                raise ValueError("backup manifest is unreadable")
            manifest = json.load(manifest_file)
            members = {member.name: member for member in archive.getmembers()}
            for item in manifest.get("files", []):
                member = members.get(item["path"])
                if member is None or not member.isfile():
                    raise ValueError(f"backup file is missing: {item['path']}")
                handle = archive.extractfile(member)
                digest = hashlib.sha256(handle.read()).hexdigest() if handle else ""
                if digest != item["sha256"]:
                    raise ValueError(f"backup checksum mismatch: {item['path']}")
        return {
            "valid": True,
            "archive": str(archive_path),
            "archiveSha256": _sha256(archive_path),
            "fileCount": manifest["fileCount"],
            "totalBytes": manifest["totalBytes"],
            "createdAt": manifest["createdAt"],
        }

    def restore(self, archive_path: Path) -> dict:
        verification = self.verify(archive_path)
        parent = self.data_path.parent
        staging = Path(tempfile.mkdtemp(prefix=f".{self.data_path.name}-restore-", dir=parent))
        previous = parent / f"{self.data_path.name}.before-restore-{datetime.now():%Y%m%d%H%M%S}"
        try:
            with tarfile.open(archive_path, "r:gz") as archive:
                for member in archive.getmembers():
                    if member.name == "backup-manifest.json":
                        continue
                    if not member.isfile() or Path(member.name).is_absolute() or ".." in Path(member.name).parts:
                        raise ValueError(f"unsafe backup member: {member.name}")
                    target = staging / member.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = archive.extractfile(member)
                    if source is None:
                        raise ValueError(f"backup member is unreadable: {member.name}")
                    with target.open("wb") as output:
                        shutil.copyfileobj(source, output)
            if self.data_path.exists():
                os.replace(self.data_path, previous)
            os.replace(staging, self.data_path)
        except Exception:
            if previous.exists() and not self.data_path.exists():
                os.replace(previous, self.data_path)
            raise
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        return {**verification, "restoredTo": str(self.data_path), "previousData": str(previous)}
