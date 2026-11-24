#!/usr/bin/env python3
"""Build a distributable AnyFlows .afplugin archive."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_EXPANDED_BYTES = 512 * 1024 * 1024
MAX_METADATA_BYTES = 256 * 1024
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def archive_entry(name: str, mode: int) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(name, FIXED_TIMESTAMP)
    entry.create_system = 3
    entry.external_attr = mode << 16
    if stat.S_ISDIR(mode):
        entry.external_attr |= 0x10
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.extra = b""
    entry.comment = b""
    return entry


def package(output: Path | None, overwrite: bool = False) -> Path:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    distribution = (ROOT / "dist").resolve()
    if output is None:
        version = manifest.get("pluginVersion")
        if not isinstance(version, str) or not version:
            raise ValueError("Manifest 缺少有效 pluginVersion")
        output = distribution / f"capy-free-provider-{version}.afplugin"
    output = output.resolve()
    if output.suffix.lower() != ".afplugin":
        raise ValueError("输出文件名必须以 .afplugin 结尾")
    if output.is_symlink():
        raise ValueError("输出文件不能是符号链接")
    if output.exists() and not overwrite:
        raise ValueError(f"输出文件已存在：{output}")
    if output.parent != distribution:
        raise ValueError("输出路径必须位于仓库 dist 目录")

    metadata = json.dumps(
        {"manifest": manifest, "executablePath": "plugin.py"},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(metadata) > MAX_METADATA_BYTES:
        raise ValueError("Manifest 超过宿主元数据大小限制")

    files = [
        ROOT / "README.md",
        ROOT / "LICENSE",
        ROOT / "LICENSE-AGPL-3.0.txt",
        ROOT / "NOTICE.md",
        ROOT / "manifest.json",
        ROOT / "plugin.py",
        ROOT / "anyflows_plugin.py",
    ]
    if not all(path.is_file() for path in files):
        raise ValueError("插件发布文件不完整")
    expanded_size = len(metadata) + sum(path.stat().st_size for path in files)
    if expanded_size > MAX_EXPANDED_BYTES:
        raise ValueError("插件解压后超过宿主大小限制")

    distribution.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=".capy-plugin-", suffix=".tmp", dir=distribution, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)

    try:
        with zipfile.ZipFile(temporary_path, "w", allowZip64=True) as archive:
            archive.writestr(
                archive_entry("anyflows-plugin.json", stat.S_IFREG | 0o644), metadata
            )
            archive.writestr(
                archive_entry("payload/", stat.S_IFDIR | 0o755), b""
            )
            for source in files:
                relative = source.name
                mode = stat.S_IFREG | (0o755 if relative == "plugin.py" else 0o644)
                info = archive_entry(f"payload/{relative}", mode)
                with source.open("rb") as input_file, archive.open(info, "w") as output_file:
                    shutil.copyfileobj(input_file, output_file, 1024 * 1024)

        if temporary_path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("插件包超过宿主上传大小限制")
        if overwrite:
            os.replace(temporary_path, output)
        else:
            os.link(temporary_path, output)
    finally:
        temporary_path.unlink(missing_ok=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        type=Path,
        help="输出文件，默认 dist/capy-free-provider-<版本>.afplugin",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖 dist 中同名安装包",
    )
    args = parser.parse_args()
    try:
        output = package(args.output, overwrite=args.force)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        parser.exit(1, f"package_plugin: {error}\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
