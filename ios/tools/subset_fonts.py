"""產生 App 內建的中文字型子集（Noto Serif TC，每個字重原本約 10 MB）。

保留：Big5 的符號和常用字（約 5,400 字）、ASCII、全形標點，以及專案裡所有文字檔出現過的字
（種子資料、劇本、Swift 字串），確保示範內容不會缺字。罕見字在 App 裡退回系統字型。

    pip install fonttools
    # 從 Google Fonts 下載 Noto Serif TC 的 Regular 和 SemiBold（TTF），然後：
    python ios/tools/subset_fonts.py NotoSerifTC-Regular.ttf NotoSerifTC-SemiBold.ttf

輸出到 ios/JobAgent/Fonts/。字型授權是 SIL Open Font License（同一個資料夾的 OFL.txt）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools import subset

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ios" / "JobAgent" / "Fonts"
TEXT_FILES = ("*.py", "*.json", "*.yaml", "*.swift", "*.md")


def big5_chars() -> set[str]:
    """Big5 的符號區（A140–A3BF）和常用字區（A440–C67E）。"""
    chars = set()
    for lead in range(0xA1, 0xC7):
        for trail in [*range(0x40, 0x7F), *range(0xA1, 0xFF)]:
            try:
                chars.add(bytes([lead, trail]).decode("big5"))
            except UnicodeDecodeError:
                pass
    return chars


def project_chars() -> set[str]:
    chars = set()
    for pattern in TEXT_FILES:
        for path in ROOT.rglob(pattern):
            if any(part in {".venv", ".git", "build", "node_modules"} for part in path.parts):
                continue
            chars |= set(path.read_text(encoding="utf-8", errors="ignore"))
    return chars


def main(paths: list[str]) -> None:
    chars = big5_chars() | project_chars() | {chr(c) for c in range(0x20, 0x7F)}
    chars |= {chr(c) for c in range(0x3000, 0x3040)} | {chr(c) for c in range(0xFF00, 0xFFF0)}
    chars |= {chr(c) for c in range(0x2010, 0x2070)}
    text = "".join(sorted(c for c in chars if c.isprintable()))
    for path in paths:
        name = "NotoSerifTC-SemiBold" if "SemiBold" in path or "semibold" in path else "NotoSerifTC-Regular"
        options = subset.Options()
        options.layout_features = ["*"]
        options.name_IDs = ["*"]
        options.notdef_outline = True
        font = subset.load_font(path, options)
        subsetter = subset.Subsetter(options)
        subsetter.populate(text=text)
        subsetter.subset(font)
        out = OUT / f"{name}.ttf"
        subset.save_font(font, str(out), options)
        print(f"{out.relative_to(ROOT)}: {out.stat().st_size / 1e6:.1f} MB, {len(text)} 字")


if __name__ == "__main__":
    main(sys.argv[1:])
