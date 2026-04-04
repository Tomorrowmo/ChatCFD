"""AnalysisArchive: save/load analysis history in .chatcfd/ next to data files."""

import hashlib
import json
import os
import time


class AnalysisArchive:
    @staticmethod
    def archive_path(file_path):
        """Return the archive JSON path for a given data file."""
        dir_name = os.path.dirname(file_path)
        file_name = os.path.basename(file_path)
        archive_dir = os.path.join(dir_name, ".chatcfd")
        return os.path.normpath(
            os.path.join(archive_dir, f"{file_name}.archive.json")
        ).replace("\\", "/")

    @staticmethod
    def file_md5(file_path):
        """Compute MD5 hex digest of a file."""
        h = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def load(file_path):
        """Load archive for a file. Returns dict or None."""
        ap = AnalysisArchive.archive_path(file_path)
        if not os.path.exists(ap):
            return None
        with open(ap, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def save_entry(file_path, method, zone, params, result, note=""):
        """Append an entry to the archive. Creates archive file if needed."""
        ap = AnalysisArchive.archive_path(file_path)
        os.makedirs(os.path.dirname(ap), exist_ok=True)

        archive = AnalysisArchive.load(file_path)
        if archive is None:
            archive = {
                "file": os.path.basename(file_path),
                "file_md5": AnalysisArchive.file_md5(file_path),
                "entries": [],
            }

        archive["entries"].append(
            {
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "method": method,
                "zone": zone,
                "params": params,
                "result": result,
                "note": note,
            }
        )

        with open(ap, "w", encoding="utf-8") as f:
            json.dump(archive, f, ensure_ascii=False, indent=2)
        return ap

    @staticmethod
    def check_consistency(file_path):
        """Check if file has changed since archive was created."""
        archive = AnalysisArchive.load(file_path)
        if archive is None:
            return {"has_archive": False}
        current_md5 = AnalysisArchive.file_md5(file_path)
        matches = current_md5 == archive.get("file_md5", "")
        return {
            "has_archive": True,
            "entries_count": len(archive.get("entries", [])),
            "md5_matches": matches,
            "message": "历史存档可用"
            if matches
            else "文件已更新，历史存档可能不适用",
        }
