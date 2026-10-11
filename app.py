#!/usr/bin/env python3
"""
ASCII / Emoji Image Converter v3.3
--------------------------------
• NEW: Automatic resolution matching on image import
• Cell-size control for fine-tuning detail density
• Smart auto-fit: cols and font size adapt to image dimensions
• Premium modernized settings dropdowns and buttons
• Visual emoji icons in dropdowns for instant recognition
• Convert images to ASCII art (plain / colored) or emoji mosaics
• Custom emoji sets & ASCII charsets (managed in a dialog, saved to JSON)
• Batch-convert a whole folder (TXT / PNG / HTML) in a background thread

Requirements: pip install PySide6 pillow numpy
"""

import io
import json
import sys
import unicodedata
from functools import lru_cache
from html import escape
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

from PySide6.QtCore import QObject, QRect, QStandardPaths, Qt, QThread, QTimer, QUrl, Signal, QSize
from PySide6.QtGui import (QAction, QColor, QFont, QFontDatabase, QFontMetrics,
                           QGuiApplication, QImage, QPainter, QPixmap, QKeySequence)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                               QLabel, QLineEdit, QListWidget, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar,
                               QPushButton, QSizePolicy, QSpinBox, QSplitter,
                               QTabWidget, QTextEdit, QVBoxLayout, QWidget, QFrame, QToolBar)

# ---------------------------------------------------------------------------
# Built-in character sets (darkest -> brightest) and emoji palettes
# ---------------------------------------------------------------------------

ASCII_SETS = {
    "Standard": "@%#*+=-:. ",
    "Blocks":   "█▓▒░ ",
    "Detailed": "$@B%8&WM#*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,\"^`'. ",
    "Minimal":  "#+. ",
    "Binary":   "10 ",
    "Numbers":  "9876543210 ",
    "Alphabet": "MWNXKHAUDBO0 ",
    "Dots":     "●◎○◍◌ ",
    "Dingbats": "✶✸✹❂✦✧• ",
    "Lines":    "╋╂┿┼┄ ",
    "Hexagram": "⬢⬡◆◇ ",
}

EMOJI_MODES = {
    "Emoji - colored squares": {
        "type": "color",
        "palette": [
            ((0, 0, 0), "⬛"), ((255, 255, 255), "⬜"),
            ((230, 30, 30), "🟥"), ((255, 140, 0), "🟧"),
            ((255, 215, 0), "🟨"), ((40, 180, 60), "🟩"),
            ((30, 100, 240), "🟦"), ((150, 60, 200), "🟪"),
            ((150, 100, 60), "🟫"),
        ],
    },
    "Emoji - colored circles": {
        "type": "color",
        "palette": [
            ((0, 0, 0), "⚫"), ((255, 255, 255), "⚪"),
            ((230, 30, 30), "🔴"), ((255, 140, 0), "🟠"),
            ((255, 215, 0), "🟡"), ((40, 180, 60), "🟢"),
            ((30, 100, 240), "🔵"), ((150, 60, 200), "🟣"),
            ((150, 100, 60), "🟤"),
        ],
    },
    "Emoji - moon phases (shading)": {"type": "gray", "ramp": "🌑🌒🌓🌔🌕"},
    "Emoji - hearts (color)": {
        "type": "color",
        "palette": [
            ((0, 0, 0), "🖤"), ((120, 80, 70), "🤎"),
            ((150, 60, 200), "💜"), ((40, 90, 230), "💙"),
            ((40, 180, 60), "💚"), ((240, 220, 50), "💛"),
            ((240, 150, 40), "🧡"), ((220, 40, 40), "❤️"),
            ((245, 245, 245), "🤍"),
        ],
    },
    "Emoji - weather (shading)": {"type": "gray", "ramp": "⛈️🌩️🌧️🌦️🌥️⛅🌤️☀️"},
    "Emoji - dice (shading)": {"type": "gray", "ramp": "⚅⚄⚃⚂⚁⚀"},
    "Emoji - fruits (color)": {
        "type": "color",
        "palette": [
            ((80, 50, 120), "🍆"), ((60, 80, 160), "🫐"),
            ((120, 160, 60), "🥑"), ((240, 220, 50), "🍋"),
            ((240, 150, 40), "🍊"), ((220, 40, 40), "🍎"),
            ((255, 200, 180), "🍑"),
        ],
    },
    "Emoji - emoticons (shading)": {"type": "gray", "ramp": "👿😣😟😐🙂😄😆"},
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif", ".ico"}
EMOJI_FONT_CANDIDATES = ("Segoe UI Emoji", "Apple Color Emoji", "Noto Color Emoji",
                         "Twemoji", "EmojiOne", "JoyPixels", "OpenMoji")
EXAMPLE_WEB_JPG_URL = "https://picsum.photos/seed/asciiart/640/480.jpg"

# ---------------------------------------------------------------------------
# Config persistence (custom sets + settings)
# ---------------------------------------------------------------------------

def config_file() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation)
    return Path(base) / "custom_sets.json"

def load_custom_sets():
    try:
        data = json.loads(config_file().read_text(encoding="utf-8"))
        return list(data.get("emoji_sets", [])), list(data.get("ascii_sets", []))
    except Exception:
        return [], []

def save_custom_sets(emoji_sets, ascii_sets):
    f = config_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        json.dumps({"emoji_sets": emoji_sets, "ascii_sets": ascii_sets},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

# ---------------------------------------------------------------------------
# Text / emoji helpers
# ---------------------------------------------------------------------------

_CONT_CATS = {"Mn", "Me", "Cf", "Sk"}

def split_clusters(text: str) -> list[str]:
    out, cur = [], ""
    for ch in text:
        if cur and unicodedata.category(ch) in _CONT_CATS:
            cur += ch
        else:
            if cur:
                out.append(cur)
            cur = ch
    if cur:
        out.append(cur)
    return out

@lru_cache(maxsize=1)
def emoji_font_family() -> str:
    try:
        families = QFontDatabase.families()
    except Exception:
        return ""
    for cand in EMOJI_FONT_CANDIDATES:
        for fam in families:
            if cand.lower() in fam.lower():
                return fam
    return ""

@lru_cache(maxsize=512)
def emoji_avg_color(emoji: str) -> tuple[int, int, int]:
    size = 64
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(0)
    painter = QPainter(img)
    f = QFont(emoji_font_family()) if emoji_font_family() else QFont()
    f.setPointSize(48)
    painter.setFont(f)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignCenter, emoji)
    painter.end()
    arr = np.frombuffer(bytes(img.constBits()), dtype=np.uint8).reshape(size, size, 4)
    mask = arr[:, :, 3] > 40
    if not mask.any():
        return (128, 128, 128)
    return tuple(int(v) for v in arr[mask][:, :3].mean(axis=0))

# ---------------------------------------------------------------------------
# Conversion logic
# ---------------------------------------------------------------------------

def grid_size(image: Image.Image, cols: int):
    w, h = image.size
    rows = max(1, round(cols * (h / w) * 0.5))
    return cols, rows

def apply_adjustments(image: Image.Image, invert: bool, contrast: int) -> Image.Image:
    if invert:
        image = ImageOps.invert(image)
    c = contrast / 100.0
    if abs(c - 1.0) > 1e-3:
        image = ImageEnhance.Contrast(image).enhance(c)
    return image

def _map_clusters(values01: np.ndarray, clusters: list[str]) -> list[list[str]]:
    clusters = clusters or ["."]
    n = len(clusters)
    idx = np.clip(np.rint(values01 * (n - 1)).astype(int), 0, n - 1)
    return [[clusters[i] for i in row] for row in idx.tolist()]

def ascii_html(cells, colors, font_family: str, font_pt: int) -> str:
    head = f'<pre style="font-family:\'{font_family}\'; font-size:{font_pt}pt; line-height: 1.0; margin: 0;">'
    rows_html = []
    for row_cells, row_colors in zip(cells, colors):
        spans = []
        for ch, (r, g, b) in zip(row_cells, row_colors):
            spans.append(f'<span style="color:#{r:02x}{g:02x}{b:02x}">{escape(ch)}</span>')
        rows_html.append("".join(spans))
    return head + "<br>".join(rows_html) + "</pre>"

def image_to_ascii(image, cols, charset, invert=False, color=False,
                   font_family="monospace", font_pt=10):
    cols, rows = grid_size(image, cols)
    small = image.resize((cols, rows), Image.LANCZOS)

    gray = np.asarray(small.convert("L"), dtype=np.float32) / 255.0
    if invert:
        gray = 1.0 - gray
    cells = _map_clusters(gray, split_clusters(charset))
    text = "\n".join("".join(row) for row in cells)

    if not color:
        return text, None, None

    rgb = np.asarray(small, dtype=np.uint8)
    colors = [[tuple(int(v) for v in rgb[y, x]) for x in range(cols)]
              for y in range(rows)]
    return text, colors, ascii_html(cells, colors, font_family, font_pt)

def image_to_emoji(image, cols, spec) -> str:
    cols, rows = grid_size(image, cols)
    small = image.resize((cols, rows), Image.LANCZOS)
    arr = np.asarray(small, dtype=np.float32)

    if spec["type"] == "gray":
        cells = _map_clusters(arr.mean(axis=2) / 255.0, split_clusters(spec["ramp"]))
    else:
        colors = np.array([c for c, _ in spec["palette"]], dtype=np.float32)
        glyphs = [e for _, e in spec["palette"]]
        dist = ((arr[:, :, None, :] - colors[None, None, :, :]) ** 2).sum(axis=3)
        idx = dist.argmin(axis=2)
        cells = [[glyphs[i] for i in row] for row in idx.tolist()]

    return "\n".join("".join(row) for row in cells)

def render_grid_image(text: str, font: QFont, sample_char: str = "M",
                      colors=None, bg: str = "#ffffff", margin: int = 12) -> QImage:
    lines = text.split("\n") or [""]
    fm = QFontMetrics(font)
    cell_w = max(1, fm.horizontalAdvance(sample_char))
    line_h = max(1, fm.height())
    width = margin * 2 + max((len(split_clusters(l)) for l in lines), default=1) * cell_w
    height = margin * 2 + len(lines) * line_h

    img = QImage(width, height, QImage.Format_RGB32)
    img.fill(QColor(bg))
    painter = QPainter(img)
    painter.setRenderHint(QPainter.Antialiasing, False)
    painter.setFont(font)
    base = margin + fm.ascent()
    for y, line in enumerate(lines):
        x = 0
        for ch in split_clusters(line):
            if colors is not None and x < len(colors[y]):
                painter.setPen(QColor(*colors[y][x]))
            else:
                painter.setPen(QColor("#000000"))
            if ch.strip():
                painter.drawText(margin + x * cell_w, base + y * line_h, ch)
            x += 1
    painter.end()
    return img

def wrap_html(body: str) -> str:
    return ('<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<title>ascii</title></head>'
            f'<body style="background:#fff; margin:0; padding:8px;">{body}</body></html>')

# ---------------------------------------------------------------------------
# Batch worker (runs in a QThread)
# ---------------------------------------------------------------------------

class BatchWorker(QObject):
    progress = Signal(int, int)
    file_done = Signal(str)
    file_error = Signal(str)
    finished = Signal()

    def __init__(self, jobs, settings):
        super().__init__()
        self.jobs = jobs
        self.settings = settings
        self.cancelled = False

    def run(self):
        total = len(self.jobs)
        for i, (src, out_dir) in enumerate(self.jobs, 1):
            if self.cancelled:
                break
            try:
                self.file_done.emit(self._convert_one(src, out_dir))
            except Exception as exc:
                self.file_error.emit(f"{Path(src).name}: {exc}")
            self.progress.emit(i, total)
        self.finished.emit()

    def _convert_one(self, src: Path, out_dir: Path) -> str:
        s = self.settings
        img = Image.open(src)
        img = ImageOps.exif_transpose(img).convert("RGB")
        img = apply_adjustments(img, s["invert"], s["contrast"])

        if s["mode"] == "ASCII art":
            text, colors, html = image_to_ascii(
                img, s["cols"], s["charset"], color=s["color"],
                font_family=s["font"].family(), font_pt=s["font_pt"])
        else:
            text = image_to_emoji(img, s["cols"], s["emoji_spec"])
            colors, html = None, None

        stem = Path(src).stem
        written = []
        if "txt" in s["formats"]:
            p = out_dir / f"{stem}_ascii.txt"
            p.write_text(text, encoding="utf-8")
            written.append(p.name)
        if "html" in s["formats"]:
            if html is None:
                html = (f'<pre style="font-family:\'{s["font"].family()}\'; '
                        f'font-size:{s["font_pt"]}pt; line-height:1.0;">{escape(text)}</pre>')
            p = out_dir / f"{stem}_ascii.html"
            p.write_text(wrap_html(html), encoding="utf-8")
            written.append(p.name)
        if "png" in s["formats"]:
            sample = "M"
            if s["mode"] != "ASCII art":
                for line in text.split("\n"):
                    cl = split_clusters(line)
                    if cl:
                        sample = cl[0]
                        break
            image = render_grid_image(text, QFont(s["font"]), sample, colors)
            p = out_dir / f"{stem}_ascii.png"
            if not image.save(str(p)):
                raise OSError(f"could not write {p.name}")
            written.append(p.name)
        return f"{Path(src).name}  →  {', '.join(written)}"

# ---------------------------------------------------------------------------
# Custom set editor dialog
# ---------------------------------------------------------------------------

class SetEditorDialog(QDialog):
    def __init__(self, parent, emoji_sets, ascii_sets):
        super().__init__(parent)
        self.setWindowTitle("Manage Custom Sets")
        self.resize(750, 550)
        self.setStyleSheet("""
            QDialog { background: #f9f9f9; }
            QLabel { font-weight: bold; }
            QPushButton { padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #e0e0e0; }
        """)
        self.emoji_sets = [dict(s) for s in emoji_sets]
        self.ascii_sets = [dict(s) for s in ascii_sets]
        self._loading = False

        tabs = QTabWidget()
        tabs.addTab(self._build_emoji_tab(), "Emoji sets")
        tabs.addTab(self._build_ascii_tab(), "ASCII charsets")

        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_save)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(bb)

        self._reload_emoji()
        self._reload_ascii()

    def _build_emoji_tab(self):
        w = QWidget()
        h = QHBoxLayout(w)

        left = QVBoxLayout()
        left.addWidget(QLabel("Your sets:"))
        self.emoji_list = QListWidget()
        self.emoji_list.currentRowChanged.connect(self._emoji_row_changed)
        left.addWidget(self.emoji_list)
        b_add = QPushButton("Add")
        b_del = QPushButton("Remove")
        b_add.clicked.connect(self._emoji_add)
        b_del.clicked.connect(self._emoji_del)
        left.addWidget(b_add)
        left.addWidget(b_del)
        left.addStretch(1)

        form = QFormLayout()
        self.emoji_name = QLineEdit()
        self.emoji_type = QComboBox()
        self.emoji_type.addItems(["Color grid — each emoji matches pixel colors",
                                  "Shading ramp — ordered dark → bright"])
        self.emoji_text = QPlainTextEdit()
        self.emoji_text.setMaximumHeight(110)
        self.emoji_text.setPlaceholderText("😀 😃 😄 🙂 😐 😑 😴")
        self.emoji_preview = QLabel("—")
        self.emoji_preview.setStyleSheet("font-size: 26pt; background: #fff; border: 1px solid #ccc; border-radius: 4px; padding: 8px;")
        hint = QLabel("Enter emojis separated by spaces. Color grids get a color "
                      "per emoji automatically; ramps map brightness in the listed order.")
        hint.setWordWrap(True)

        form.addRow("Name:", self.emoji_name)
        form.addRow("Type:", self.emoji_type)
        form.addRow("Emojis:", self.emoji_text)
        form.addRow(hint)
        form.addRow("Preview:", self.emoji_preview)
        right = QWidget()
        right.setLayout(form)

        h.addLayout(left, 1)
        h.addWidget(right, 2)

        for sig in (self.emoji_name.textChanged, self.emoji_text.textChanged,
                    self.emoji_type.currentIndexChanged):
            sig.connect(self._emoji_edited)
        return w

    def _reload_emoji(self, row=0):
        self.emoji_list.blockSignals(True)
        self.emoji_list.clear()
        for s in self.emoji_sets:
            self.emoji_list.addItem(s["name"] or "(unnamed)")
        self.emoji_list.blockSignals(False)
        if self.emoji_sets:
            self.emoji_list.setCurrentRow(max(0, min(row, len(self.emoji_sets) - 1)))
        else:
            self._emoji_row_changed(-1)

    def _emoji_row_changed(self, row):
        self._loading = True
        try:
            ok = 0 <= row < len(self.emoji_sets)
            for wd in (self.emoji_name, self.emoji_type, self.emoji_text):
                wd.setEnabled(ok)
            if ok:
                s = self.emoji_sets[row]
                self.emoji_name.setText(s["name"])
                self.emoji_type.setCurrentIndex(0 if s["type"] == "color" else 1)
                self.emoji_text.setPlainText(s["emojis"])
            else:
                self.emoji_name.clear()
                self.emoji_text.clear()
            self._emoji_preview()
        finally:
            self._loading = False

    def _emoji_edited(self, _=None):
        if self._loading:
            return
        row = self.emoji_list.currentRow()
        if not (0 <= row < len(self.emoji_sets)):
            return
        s = self.emoji_sets[row]
        s["name"] = self.emoji_name.text()
        s["type"] = "color" if self.emoji_type.currentIndex() == 0 else "gray"
        s["emojis"] = self.emoji_text.toPlainText()
        self.emoji_list.item(row).setText(s["name"] or "(unnamed)")
        self._emoji_preview()

    def _emoji_preview(self):
        txt = " ".join(self.emoji_text.toPlainText().split())
        self.emoji_preview.setText(txt or "—")

    def _emoji_add(self):
        self.emoji_sets.append({"name": f"Set {len(self.emoji_sets) + 1}",
                                "type": "color", "emojis": ""})
        self._reload_emoji(len(self.emoji_sets) - 1)

    def _emoji_del(self):
        row = self.emoji_list.currentRow()
        if 0 <= row < len(self.emoji_sets):
            del self.emoji_sets[row]
            self._reload_emoji(min(row, len(self.emoji_sets) - 1))

    def _build_ascii_tab(self):
        w = QWidget()
        h = QHBoxLayout(w)

        left = QVBoxLayout()
        left.addWidget(QLabel("Your charsets:"))
        self.ascii_list = QListWidget()
        self.ascii_list.currentRowChanged.connect(self._ascii_row_changed)
        left.addWidget(self.ascii_list)
        b_add = QPushButton("Add")
        b_del = QPushButton("Remove")
        b_add.clicked.connect(self._ascii_add)
        b_del.clicked.connect(self._ascii_del)
        left.addWidget(b_add)
        left.addWidget(b_del)
        left.addStretch(1)

        form = QFormLayout()
        self.ascii_name = QLineEdit()
        self.ascii_chars = QLineEdit()
        self.ascii_chars.setPlaceholderText("@%#*+=-:. ")
        self.ascii_preview = QLabel("—")
        self.ascii_preview.setStyleSheet("font-family:monospace; font-size:15pt; background: #fff; border: 1px solid #ccc; border-radius: 4px; padding: 8px;")
        hint = QLabel("Characters ordered dark → bright. Use a space as the "
                      "last character for a clean background.")
        hint.setWordWrap(True)
        form.addRow("Name:", self.ascii_name)
        form.addRow("Characters:", self.ascii_chars)
        form.addRow(hint)
        form.addRow("Preview:", self.ascii_preview)
        right = QWidget()
        right.setLayout(form)

        h.addLayout(left, 1)
        h.addWidget(right, 2)

        self.ascii_name.textChanged.connect(self._ascii_edited)
        self.ascii_chars.textChanged.connect(self._ascii_edited)
        return w

    def _reload_ascii(self, row=0):
        self.ascii_list.blockSignals(True)
        self.ascii_list.clear()
        for s in self.ascii_sets:
            self.ascii_list.addItem(s["name"] or "(unnamed)")
        self.ascii_list.blockSignals(False)
        if self.ascii_sets:
            self.ascii_list.setCurrentRow(max(0, min(row, len(self.ascii_sets) - 1)))
        else:
            self._ascii_row_changed(-1)

    def _ascii_row_changed(self, row):
        self._loading = True
        try:
            ok = 0 <= row < len(self.ascii_sets)
            self.ascii_name.setEnabled(ok)
            self.ascii_chars.setEnabled(ok)
            if ok:
                s = self.ascii_sets[row]
                self.ascii_name.setText(s["name"])
                self.ascii_chars.setText(s["chars"])
                self.ascii_preview.setText(s["chars"] or "—")
            else:
                self.ascii_name.clear()
                self.ascii_chars.clear()
                self.ascii_preview.setText("—")
        finally:
            self._loading = False

    def _ascii_edited(self, _=None):
        if self._loading:
            return
        row = self.ascii_list.currentRow()
        if not (0 <= row < len(self.ascii_sets)):
            return
        s = self.ascii_sets[row]
        s["name"] = self.ascii_name.text()
        s["chars"] = self.ascii_chars.text()
        self.ascii_list.item(row).setText(s["name"] or "(unnamed)")
        self.ascii_preview.setText(s["chars"] or "—")

    def _ascii_add(self):
        self.ascii_sets.append({"name": f"Charset {len(self.ascii_sets) + 1}",
                                "chars": ""})
        self._reload_ascii(len(self.ascii_sets) - 1)

    def _ascii_del(self):
        row = self.ascii_list.currentRow()
        if 0 <= row < len(self.ascii_sets):
            del self.ascii_sets[row]
            self._reload_ascii(min(row, len(self.ascii_sets) - 1))

    def _on_save(self):
        names = set()
        for i, s in enumerate(self.emoji_sets, 1):
            if not s["emojis"].strip():
                QMessageBox.warning(self, "Empty set", f"Emoji set “{s['name'] or i}” has no emojis.")
                return
            name, n = (s["name"].strip() or f"Emoji set {i}"), 2
            while name.lower() in names:
                name, n = f"{s['name'].strip() or 'Emoji set'} {n}", n + 1
            names.add(name.lower())
            s["name"], s["emojis"] = name, " ".join(s["emojis"].split())

        names = set()
        for i, s in enumerate(self.ascii_sets, 1):
            if not s["chars"].strip():
                QMessageBox.warning(self, "Empty set", f"Charset “{s['name'] or i}” has no characters.")
                return
            name, n = (s["name"].strip() or f"Charset {i}"), 2
            while name.lower() in names:
                name, n = f"{s['name'].strip() or 'Charset'} {n}", n + 1
            names.add(name.lower())
            s["name"], s["chars"] = name, s["chars"].strip()
        self.accept()

# ---------------------------------------------------------------------------
# Batch conversion dialog
# ---------------------------------------------------------------------------

class BatchDialog(QDialog):
    def __init__(self, parent, modes, current_mode):
        super().__init__(parent)
        self.parent_main = parent
        self.setWindowTitle("Batch Convert Folder")
        self.setMinimumWidth(620)
        self.setStyleSheet("""
            QDialog { background: #f9f9f9; }
            QLabel { font-weight: bold; }
            QPushButton { padding: 6px 12px; border-radius: 4px; }
            QPushButton:hover { background: #e0e0e0; }
        """)
        self.worker = None
        self.thread = None

        grid = QGridLayout()

        self.in_edit = QLineEdit()
        b_in = QPushButton("Browse…")
        b_in.clicked.connect(self._browse_in)
        grid.addWidget(QLabel("Input folder"), 0, 0)
        grid.addWidget(self.in_edit, 0, 1)
        grid.addWidget(b_in, 0, 2)

        self.recursive = QCheckBox("Include subfolders")
        grid.addWidget(self.recursive, 1, 1)

        self.out_edit = QLineEdit()
        b_out = QPushButton("Browse…")
        b_out.clicked.connect(self._browse_out)
        grid.addWidget(QLabel("Output folder"), 2, 0)
        grid.addWidget(self.out_edit, 2, 1)
        grid.addWidget(b_out, 2, 2)
        grid.addWidget(QLabel("(blank = “ascii_output” inside the input folder)"), 3, 1)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(modes)
        self.mode_combo.setCurrentText(current_mode)
        grid.addWidget(QLabel("Mode"), 4, 0)
        grid.addWidget(self.mode_combo, 4, 1)

        fmt_w = QWidget()
        fl = QHBoxLayout(fmt_w)
        fl.setContentsMargins(0, 0, 0, 0)
        self.f_txt = QCheckBox("TXT")
        self.f_txt.setChecked(True)
        self.f_png = QCheckBox("PNG")
        self.f_png.setChecked(True)
        self.f_html = QCheckBox("HTML")
        for cb in (self.f_txt, self.f_png, self.f_html):
            fl.addWidget(cb)
        fl.addStretch(1)
        grid.addWidget(QLabel("Formats"), 5, 0)
        grid.addWidget(fmt_w, 5, 1, 1, 2)

        note = QLabel("Uses the current column width, charset / emoji set, "
                      "invert and contrast settings from the main window.")
        note.setWordWrap(True)
        note.setStyleSheet("font-weight: normal; color: #666;")
        grid.addWidget(note, 6, 0, 1, 3)

        self.progress = QProgressBar()
        self.progress.hide()
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.hide()
        self.log.setMaximumHeight(170)

        btns = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_start.clicked.connect(self._start)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btns.addWidget(self.btn_start)
        btns.addWidget(self.btn_close)
        btns.addStretch(1)

        lay = QVBoxLayout(self)
        lay.addLayout(grid)
        lay.addWidget(self.progress)
        lay.addWidget(self.log)
        lay.addLayout(btns)

    def _browse_in(self):
        d = QFileDialog.getExistingDirectory(self, "Choose input folder",
                                             self.in_edit.text() or str(Path.home()))
        if d:
            self.in_edit.setText(d)
            if not self.out_edit.text().strip():
                self.out_edit.setText(str(Path(d) / "ascii_output"))

    def _browse_out(self):
        d = QFileDialog.getExistingDirectory(self, "Choose output folder",
                                             self.out_edit.text() or str(Path.home()))
        if d:
            self.out_edit.setText(d)

    def _log(self, msg):
        self.log.show()
        self.log.appendPlainText(msg)

    def _on_progress(self, done, total):
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def _on_done(self):
        cancelled = bool(self.worker and self.worker.cancelled)
        self.btn_start.setEnabled(True)
        self.btn_close.setText("Close")
        self._log("Cancelled." if cancelled else "Done.")
        self.thread = None
        self.worker = None

    def _start(self):
        in_dir = Path(self.in_edit.text().strip()).expanduser()
        if not in_dir.is_dir():
            QMessageBox.warning(self, "No input folder", "Please choose a valid input folder.")
            return
        formats = [n for n, cb in (("txt", self.f_txt), ("png", self.f_png),
                                   ("html", self.f_html)) if cb.isChecked()]
        if not formats:
            QMessageBox.warning(self, "No formats", "Select at least one output format.")
            return
        out_txt = self.out_edit.text().strip()
        out_dir = Path(out_txt).expanduser() if out_txt else in_dir / "ascii_output"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            QMessageBox.critical(self, "Output folder", f"Could not create output folder:\n{exc}")
            return

        it = in_dir.rglob("*") if self.recursive.isChecked() else in_dir.glob("*")
        jobs = []
        for p in sorted(it):
            if not (p.is_file() and p.suffix.lower() in IMAGE_EXTS):
                continue
            if out_dir in p.parents or p.stem.endswith("_ascii"):
                continue
            jobs.append((p, out_dir))
        if not jobs:
            QMessageBox.information(self, "No images", "No image files found.")
            return

        settings = self.parent_main.batch_settings(self.mode_combo.currentText(), formats)
        self.progress.setRange(0, len(jobs))
        self.progress.setValue(0)
        self.progress.show()
        self.log.clear()
        self._log(f"{len(jobs)} file(s)  →  {out_dir}")

        self.thread = QThread(self)
        self.worker = BatchWorker(jobs, settings)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_done.connect(self._log)
        self.worker.file_error.connect(lambda m: self._log("ERROR  " + m))
        self.worker.finished.connect(self._on_done)
        self.worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.btn_start.setEnabled(False)
        self.btn_close.setText("Cancel")
        self.thread.start()

    def closeEvent(self, event):
        t = self.thread
        if t is not None:
            try:
                if t.isRunning():
                    if self.worker is not None:
                        self.worker.cancelled = True
                    self.btn_close.setEnabled(False)
                    t.wait(20000)
                    self.btn_close.setEnabled(True)
            except RuntimeError:
                pass
        event.accept()

# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ASCII / Emoji Image Converter")
        self.resize(1280, 860)
        self.setAcceptDrops(True)

        self.source_image: Image.Image | None = None
        self._pixmap: QPixmap | None = None
        self.plain_text = ""
        self.result_colors = None
        self.html_text = None

        self.net = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._last_url = ""

        self.custom_emoji_sets, self.custom_ascii_sets = load_custom_sets()

        self._build_menu()
        self._build_toolbar()
        self._build_ui()

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(120)
        self._debounce.timeout.connect(self.convert)

        self._rebuild_mode_combo()
        self._rebuild_charset_combo()
        self.statusBar().showMessage(
            "Workflow: 1. Open Image → 2. Adjust Parameters → 3. Export Result")

    def _build_menu(self):
        m = self.menuBar().addMenu("&File")
        m.addAction(QAction("&Open image…", self, shortcut="Ctrl+O", triggered=self.open_dialog))
        m.addAction(QAction("Open from &URL…", self, shortcut="Ctrl+U", triggered=self.open_url))
        m.addAction(QAction("Load &example image", self, shortcut="Ctrl+E",
                            triggered=self.load_example_web_image))
        m.addSeparator()
        m.addAction(QAction("&Clear workspace", self, shortcut="Ctrl+L", triggered=self.clear_image))
        m.addSeparator()
        m.addAction(QAction("&Save text…", self, shortcut="Ctrl+S", triggered=self.save_text))
        m.addAction(QAction("Save &PNG…", self, shortcut="Ctrl+Shift+S", triggered=self.save_png))
        m.addSeparator()
        m.addAction(QAction("E&xit", self, shortcut="Ctrl+Q", triggered=self.close))

        tools = self.menuBar().addMenu("&Tools")
        tools.addAction(QAction("&Manage custom sets…", self, shortcut="Ctrl+M", triggered=self.manage_sets))
        tools.addAction(QAction("&Batch convert folder…", self, shortcut="Ctrl+Shift+B", triggered=self.batch_convert))

        h = self.menuBar().addMenu("&Help")
        h.addAction(QAction("&About", self, triggered=self.show_about))

    def _build_toolbar(self):
        tb = QToolBar("Main Actions")
        tb.setMovable(False)
        tb.setIconSize(QSize(18, 18))
        self.addToolBar(Qt.TopToolBarArea, tb)

        def add_tb_action(text, shortcut, callback, icon=""):
            act = QAction(f"{icon} {text}" if icon else text, self)
            if shortcut:
                act.setShortcut(shortcut)
            act.triggered.connect(callback)
            tb.addAction(act)
            return act

        add_tb_action("Open File", "Ctrl+O", self.open_dialog, "📂")
        add_tb_action("From URL", "Ctrl+U", self.open_url, "🌐")
        add_tb_action("Example", "Ctrl+E", self.load_example_web_image, "🖼️")
        tb.addSeparator()

        add_tb_action("Manage Sets", "Ctrl+M", self.manage_sets, "⚙️")
        add_tb_action("Batch Convert", "Ctrl+Shift+B", self.batch_convert, "📦")
        tb.addSeparator()

        add_tb_action("Copy Text", "Ctrl+C", self.copy_output, "📋")
        add_tb_action("Save TXT", "Ctrl+S", self.save_text, "📝")
        add_tb_action("Save PNG", "Ctrl+Shift+S", self.save_png, "🖼️")
        tb.addSeparator()
        
        add_tb_action("Clear", "Ctrl+L", self.clear_image, "🗑️")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # --- Modern Settings Bar ---
        settings_bar = QFrame()
        settings_bar.setFrameShape(QFrame.StyledPanel)
        settings_bar.setStyleSheet("""
            QFrame { 
                background: #f8f9fa; 
                border-radius: 8px; 
                border: 1px solid #e2e8f0; 
            }
            QLabel { font-weight: 600; font-size: 12px; color: #475569; margin-bottom: 4px; }
        """)
        settings_layout = QHBoxLayout(settings_bar)
        settings_layout.setSpacing(20)
        settings_layout.setContentsMargins(16, 12, 16, 12)

        def add_setting(layout, label_text, widget, tooltip=""):
            v = QVBoxLayout()
            v.setSpacing(4)
            v.setContentsMargins(0, 0, 0, 0)
            lbl = QLabel(label_text)
            if tooltip:
                lbl.setToolTip(tooltip)
                widget.setToolTip(tooltip)
            v.addWidget(lbl)
            v.addWidget(widget)
            layout.addLayout(v)

        # Group 1: Resolution Matching (NEW!)
        res_group = QFrame()
        res_group.setStyleSheet("QFrame { background: transparent; }")
        res_layout = QHBoxLayout(res_group)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.setSpacing(12)

        self.match_resolution_check = QCheckBox("Match resolution on import")
        self.match_resolution_check.setChecked(True)
        self.match_resolution_check.setToolTip(
            "Automatically adjust column count based on the image's pixel dimensions.\n"
            "Ensures the ASCII art preserves the original image's detail level.")
        self.match_resolution_check.toggled.connect(self._on_match_resolution_toggled)
        res_layout.addWidget(self.match_resolution_check)

        self.cell_size_spin = QSpinBox()
        self.cell_size_spin.setRange(2, 20)
        self.cell_size_spin.setValue(6)
        self.cell_size_spin.setSuffix(" px")
        self.cell_size_spin.setFixedWidth(85)
        self.cell_size_spin.setToolTip(
            "Pixels per character cell.\n"
            "• Smaller (2-4 px) = more detail, larger output\n"
            "• Medium (5-8 px) = balanced\n"
            "• Larger (10-20 px) = more abstract, smaller output")
        self.cell_size_spin.valueChanged.connect(self._on_cell_size_changed)
        add_setting(res_layout, "Cell size", self.cell_size_spin,
                    "How many pixels each character represents")

        settings_layout.addWidget(res_group)

        # Vertical Divider
        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Plain)
        vline.setStyleSheet("color: #cbd5e1;")
        settings_layout.addWidget(vline)

        # Group 2: Conversion
        conv_group = QFrame()
        conv_group.setStyleSheet("QFrame { background: transparent; }")
        conv_layout = QHBoxLayout(conv_group)
        conv_layout.setContentsMargins(0, 0, 0, 0)
        conv_layout.setSpacing(16)

        self.mode_box = QComboBox()
        self.mode_box.setMinimumWidth(200)
        self.mode_box.currentIndexChanged.connect(self._on_mode_changed)
        add_setting(conv_layout, "Mode", self.mode_box, "Choose between ASCII art or various Emoji palettes")

        self.charset_box = QComboBox()
        self.charset_box.setMinimumWidth(160)
        self.charset_box.currentIndexChanged.connect(self._schedule)
        add_setting(conv_layout, "Charset", self.charset_box, "Character set used for ASCII art (dark to bright)")

        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(16, 400)
        self.columns_spin.setValue(100)
        self.columns_spin.setSuffix(" cols")
        self.columns_spin.valueChanged.connect(self._schedule)
        add_setting(conv_layout, "Width", self.columns_spin, "Number of characters across the image")

        self.contrast_spin = QSpinBox()
        self.contrast_spin.setRange(25, 400)
        self.contrast_spin.setValue(100)
        self.contrast_spin.setSuffix("%")
        self.contrast_spin.valueChanged.connect(self._schedule)
        add_setting(conv_layout, "Contrast", self.contrast_spin, "Adjust image contrast before conversion")

        check_layout = QVBoxLayout()
        check_layout.setSpacing(10)
        check_layout.setContentsMargins(0, 18, 0, 0)
        self.invert_check = QCheckBox("Invert Colors")
        self.invert_check.toggled.connect(self._schedule)
        self.color_check = QCheckBox("Colored Output")
        self.color_check.toggled.connect(self._schedule)
        check_layout.addWidget(self.invert_check)
        check_layout.addWidget(self.color_check)
        conv_layout.addLayout(check_layout)

        settings_layout.addWidget(conv_group)

        # Vertical Divider
        vline2 = QFrame()
        vline2.setFrameShape(QFrame.VLine)
        vline2.setFrameShadow(QFrame.Plain)
        vline2.setStyleSheet("color: #cbd5e1;")
        settings_layout.addWidget(vline2)

        # Group 3: Appearance & Tools
        app_group = QFrame()
        app_group.setStyleSheet("QFrame { background: transparent; }")
        app_layout = QHBoxLayout(app_group)
        app_layout.setContentsMargins(0, 0, 0, 0)
        app_layout.setSpacing(16)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(4, 32)
        self.font_spin.setValue(8)
        self.font_spin.setSuffix(" pt")
        self.font_spin.setFixedWidth(90)
        self.font_spin.valueChanged.connect(self._on_font_changed)
        add_setting(app_layout, "Font Size", self.font_spin, "Size of the output text")

        app_layout.addStretch()

        # Premium Settings Button
        self.btn_manage_sets = QPushButton("⚙️ Manage Custom Sets")
        self.btn_manage_sets.setCursor(Qt.PointingHandCursor)
        self.btn_manage_sets.clicked.connect(self.manage_sets)
        self.btn_manage_sets.setStyleSheet("""
            QPushButton {
                background-color: #3b82f6;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: 600;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #2563eb;
            }
            QPushButton:pressed {
                background-color: #1d4ed8;
            }
        """)
        self.btn_manage_sets.setToolTip("Create, edit, or remove your own custom ASCII charsets and Emoji palettes")
        app_layout.addWidget(self.btn_manage_sets)

        settings_layout.addWidget(app_group)
        root.addWidget(settings_bar)

        # --- Main Splitter ---
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel("No image loaded")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(300, 300)
        self.preview.setStyleSheet(
            "QLabel { border: 2px dashed #cbd5e1; background: #f8fafc; border-radius: 8px; color: #64748b; font-size: 14px; }")
        preview_layout.addWidget(self.preview)
        
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setLineWrapMode(QTextEdit.NoWrap)
        self.output.setPlaceholderText("Converted output will appear here…")
        self.output.setStyleSheet("""
            QTextEdit {
                background: #ffffff;
                color: #0f172a;
                border: 1px solid #e2e8f0;
                border-radius: 8px;
                padding: 12px;
                font-family: monospace;
            }
            QTextEdit:focus {
                border: 1px solid #3b82f6;
            }
        """)
        self._apply_font()

        self.splitter.addWidget(preview_container)
        self.splitter.addWidget(self.output)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([400, 800])
        self.splitter.splitterMoved.connect(lambda *_: self._update_preview_pixmap())
        
        root.addWidget(self.splitter, 1)

        # Global App Styling
        self.setStyleSheet("""
            QMainWindow { background: #ffffff; }
            QToolBar { 
                background: #f8fafc; 
                border-bottom: 1px solid #e2e8f0; 
                padding: 6px;
                spacing: 4px;
            }
            QToolBar QToolButton {
                background: transparent;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: 500;
                color: #334155;
            }
            QToolBar QToolButton:hover {
                background: #e2e8f0;
                border: 1px solid #cbd5e1;
            }
            QToolBar QToolButton:pressed {
                background: #cbd5e1;
            }
            
            /* Premium Dropdown Styling */
            QComboBox {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 12px;
                color: #0f172a;
                selection-background-color: #3b82f6;
                selection-color: white;
            }
            QComboBox:hover {
                border: 1px solid #94a3b8;
                background-color: #f8fafc;
            }
            QComboBox:focus {
                border: 1px solid #3b82f6;
                background-color: #ffffff;
            }
            QComboBox::drop-down {
                border: none;
                width: 24px;
            }
            QComboBox::down-arrow {
                width: 12px;
                height: 12px;
            }
            QComboBox QAbstractItemView {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                selection-background-color: #3b82f6;
                selection-color: white;
                outline: none;
                padding: 4px;
            }
            
            /* Premium SpinBox Styling */
            QSpinBox {
                background-color: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px;
                color: #0f172a;
            }
            QSpinBox:hover {
                border: 1px solid #94a3b8;
            }
            QSpinBox:focus {
                border: 1px solid #3b82f6;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background: transparent;
                border: none;
                width: 16px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background: #e2e8f0;
                border-radius: 4px;
            }
            
            /* Premium Checkbox Styling */
            QCheckBox {
                spacing: 8px;
                color: #334155;
                font-weight: 500;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #cbd5e1;
                border-radius: 4px;
                background: #ffffff;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #94a3b8;
            }
            QCheckBox::indicator:checked {
                background: #3b82f6;
                border: 2px solid #3b82f6;
                image: url(data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='white'><path d='M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z'/></svg>);
            }
            
            QSplitter::handle {
                background: #e2e8f0;
                width: 4px;
                border-radius: 2px;
            }
            QSplitter::handle:hover {
                background: #94a3b8;
            }
        """)

    def _custom_emoji_spec(self, s: dict) -> dict:
        if s["type"] == "gray":
            return {"type": "gray", "ramp": "".join(s["emojis"].split())}
        palette = [(emoji_avg_color(e), e) for e in s["emojis"].split()]
        return {"type": "color", "palette": palette}

    def _rebuild_mode_combo(self, keep: str | None = None):
        combo = self.mode_box
        if keep is None:
            keep = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        
        combo.addItem("🔤 ASCII art")
        self.emoji_specs = {k: dict(v) for k, v in EMOJI_MODES.items()}
        
        icon_map = {
            "squares": "🟥", "circles": "🔴", "moon": "🌑", 
            "hearts": "❤️", "weather": "☀️", "dice": "⚅", 
            "fruits": "🍎", "emoticons": "🙂"
        }
        
        for key, val in EMOJI_MODES.items():
            icon = "😀"
            for k, v in icon_map.items():
                if k in key.lower():
                    icon = v
                    break
            combo.addItem(f"{icon} {key}")
            self.emoji_specs[key] = val
            
        for s in self.custom_emoji_sets:
            label = f"✨ {s['name']} (custom)"
            self.emoji_specs[label] = self._custom_emoji_spec(s)
            combo.addItem(label)
            
        clean_keep = keep.lstrip("🔤 😀 🟥 🔴 🌑 ❤️ ☀️ ⚅ 🍎 🙂 ✨ ").strip()
        i = combo.findText(clean_keep, Qt.MatchContains)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)
        self._on_mode_changed()

    def _rebuild_charset_combo(self, keep: str | None = None):
        combo = self.charset_box
        if keep is None:
            keep = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        self.charset_specs = dict(ASCII_SETS)
        
        icon_map = {
            "standard": "🔠", "blocks": "▓", "detailed": "🔍", 
            "minimal": "▪", "binary": "01", "numbers": "🔢", 
            "alphabet": "🔤", "dots": "⚬", "dingbats": "✦", 
            "lines": "╋", "hexagram": "⬡"
        }
        
        for key, val in ASCII_SETS.items():
            icon = "📝"
            for k, v in icon_map.items():
                if k in key.lower():
                    icon = v
                    break
            combo.addItem(f"{icon} {key}")
            
        for s in self.custom_ascii_sets:
            label = f"✨ {s['name']} (custom)"
            self.charset_specs[label] = s["chars"]
            combo.addItem(label)
            
        clean_keep = keep.lstrip("🔠 ▓ 🔍 ▪ 01 🔢 🔤 ⚬ ✦ ╋ ⬡ ✨ ").strip()
        i = combo.findText(clean_keep, Qt.MatchContains)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            if url.scheme() in ("http", "https"):
                self._download(url)
                return
            path = url.toLocalFile()
            if path and Path(path).is_file():
                self.load_image(path)
                return
        self.statusBar().showMessage("Dropped item is not a supported file or link.", 3000)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_preview_pixmap()

    def clear_image(self):
        self.source_image = None
        self._pixmap = None
        self.plain_text = ""
        self.result_colors = None
        self.html_text = None
        self.preview.setText("No image loaded")
        self.preview.setStyleSheet(
            "QLabel { border: 2px dashed #cbd5e1; background: #f8fafc; border-radius: 8px; color: #64748b; font-size: 14px; }")
        self.output.clear()
        self.setWindowTitle("ASCII / Emoji Image Converter")
        self.statusBar().showMessage("Workspace cleared. Ready for new image.", 3000)

    # --- Resolution Matching Logic ---
    def _on_match_resolution_toggled(self, checked):
        """Enable/disable cell_size_spin based on match_resolution_check."""
        self.cell_size_spin.setEnabled(checked)
        if checked and self.source_image is not None:
            self._auto_fit_resolution()
            self._schedule()

    def _on_cell_size_changed(self, value):
        """When cell size changes and match_resolution is on, recalculate cols."""
        if self.match_resolution_check.isChecked() and self.source_image is not None:
            self._auto_fit_resolution()
            self._schedule()

    def _auto_fit_resolution(self):
        """Calculate optimal column count based on image dimensions and cell size."""
        if self.source_image is None:
            return
        
        img_w, img_h = self.source_image.size
        cell_size = self.cell_size_spin.value()
        
        # Calculate cols: each character covers cell_size pixels horizontally
        # and cell_size * 2 pixels vertically (because chars are ~2x taller than wide)
        optimal_cols = max(16, min(400, img_w // cell_size))
        
        # Block signals to prevent recursive updates
        self.columns_spin.blockSignals(True)
        self.columns_spin.setValue(optimal_cols)
        self.columns_spin.blockSignals(False)
        
        # Also auto-fit font size to make output fit nicely in the output area
        # Estimate: output area is roughly 2/3 of window width
        output_width = self.output.viewport().width() - 40  # subtract padding
        if output_width > 0 and optimal_cols > 0:
            # Each char is roughly 0.6 * font_size wide (for monospace)
            # So font_size ≈ output_width / (optimal_cols * 0.6)
            estimated_font_pt = max(4, min(32, int(output_width / (optimal_cols * 0.6))))
            self.font_spin.blockSignals(True)
            self.font_spin.setValue(estimated_font_pt)
            self.font_spin.blockSignals(False)
            self._apply_font()

    def _use_image(self, img: Image.Image, pixmap: QPixmap, title: str):
        self.source_image = img
        self._pixmap = pixmap
        self._update_preview_pixmap()
        self.preview.setStyleSheet("")
        self.setWindowTitle(f"ASCII / Emoji Image Converter — {title}")
        
        # Auto-fit resolution if enabled
        if self.match_resolution_check.isChecked():
            self._auto_fit_resolution()
        
        self.convert()

    def _on_mode_changed(self):
        is_ascii = "ASCII art" in self.mode_box.currentText()
        self.charset_box.setEnabled(is_ascii)
        self.color_check.setEnabled(is_ascii)
        # Don't auto-reduce cols for emoji if match_resolution is on
        if not is_ascii and self.columns_spin.value() > 120 and not self.match_resolution_check.isChecked():
            self.columns_spin.setValue(60)
        self._apply_font()
        self._schedule()

    def _on_font_changed(self):
        self._apply_font()
        self._schedule()

    def _current_font(self) -> QFont:
        pt = max(4, self.font_spin.value())
        mode_text = self.mode_box.currentText()
        if "ASCII art" in mode_text or not emoji_font_family():
            f = QFont("Consolas")
            f.setStyleHint(QFont.StyleHint.Monospace)
        else:
            f = QFont(emoji_font_family())
        f.setPointSize(pt)
        return f

    def _apply_font(self):
        self.output.setFont(self._current_font())

    def _schedule(self):
        self._debounce.start()

    def _pil_to_pixmap(self, img: Image.Image) -> QPixmap:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        pm = QPixmap()
        pm.loadFromData(buf.getvalue(), "PNG")
        return pm

    def _update_preview_pixmap(self):
        if self._pixmap is None:
            self.preview.setText("No image loaded")
            return
        self.preview.setPixmap(
            self._pixmap.scaled(self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def open_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tiff *.ico);;All files (*)")
        if path:
            self.load_image(path)

    def load_image(self, path):
        try:
            img = Image.open(path)
            img = ImageOps.exif_transpose(img).convert("RGB")
        except Exception as exc:
            QMessageBox.critical(self, "Could not open image", str(exc))
            return
        pm = QPixmap(path)
        if pm.isNull():
            pm = self._pil_to_pixmap(img)
        self._use_image(img, pm, Path(path).name)

    def open_url(self):
        if self._reply is not None:
            self.statusBar().showMessage("A download is already in progress…", 3000)
            return
        default = self._last_url or EXAMPLE_WEB_JPG_URL
        text, ok = QInputDialog.getText(
            self, "Open image from web",
            "Image URL (http / https):\n"
            f"  example: {EXAMPLE_WEB_JPG_URL}",
            text=default)
        if not ok:
            return
        text = text.strip()
        if not text:
            return
        self._last_url = text
        self._download(QUrl.fromUserInput(text))

    def load_example_web_image(self):
        if self._reply is not None:
            self.statusBar().showMessage("A download is already in progress…", 3000)
            return
        self._last_url = EXAMPLE_WEB_JPG_URL
        self.statusBar().showMessage(f"Loading example: {EXAMPLE_WEB_JPG_URL}", 4000)
        self._download(QUrl.fromUserInput(EXAMPLE_WEB_JPG_URL))

    def _download(self, url: QUrl):
        if not (url.isValid() and url.scheme() in ("http", "https")):
            QMessageBox.warning(self, "Invalid URL", "Please provide a valid http(s) image URL.")
            return
        if self._reply is not None:
            self._reply.abort()
        req = QNetworkRequest(url)
        req.setTransferTimeout(30000)
        req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                         QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy)
        req.setRawHeader(b"User-Agent", b"Mozilla/5.0 (compatible; AsciiEmojiConverter/3.3)")
        self.statusBar().showMessage(f"Downloading from {url.host()}…")
        reply = self.net.get(req)
        reply.downloadProgress.connect(self._dl_progress)
        reply.finished.connect(lambda r=reply: self._dl_finished(r))
        self._reply = reply

    def _dl_progress(self, done, total):
        if total > 0:
            pct = 100 * done // total
            self.statusBar().showMessage(f"Downloading… {done / 1e6:.1f} / {total / 1e6:.1f} MB ({pct}%)")
        else:
            self.statusBar().showMessage(f"Downloading… {done / 1e6:.1f} MB")

    def _dl_finished(self, reply: QNetworkReply):
        if self._reply is reply:
            self._reply = None
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            if reply.error() != QNetworkReply.NetworkError.OperationCanceledError:
                QMessageBox.critical(self, "Download failed", reply.errorString() +
                                     "\n\nNote: some websites block direct image downloads.")
            self.statusBar().clearMessage()
            return
        data = bytes(reply.readAll())
        if not data:
            QMessageBox.critical(self, "Download failed", "Empty response.")
            return
        try:
            img = Image.open(io.BytesIO(data))
            img = ImageOps.exif_transpose(img).convert("RGB")
        except Exception as exc:
            QMessageBox.critical(self, "Not an image", f"The downloaded data is not a supported image.\n{exc}")
            return
        pm = QPixmap()
        if not pm.loadFromData(data):
            pm = self._pil_to_pixmap(img)
        name = Path(QUrl(reply.url()).path()).name or "web image"
        self._use_image(img, pm, name)
        self.statusBar().showMessage(f"Loaded from web: {name}", 5000)

    def manage_sets(self):
        dlg = SetEditorDialog(self, self.custom_emoji_sets, self.custom_ascii_sets)
        if dlg.exec() == QDialog.Accepted:
            self.custom_emoji_sets = dlg.emoji_sets
            self.custom_ascii_sets = dlg.ascii_sets
            try:
                save_custom_sets(self.custom_emoji_sets, self.custom_ascii_sets)
            except Exception as exc:
                QMessageBox.warning(self, "Could not save", str(exc))
            self._rebuild_mode_combo()
            self._rebuild_charset_combo()
            self._schedule()

    def batch_settings(self, mode: str, formats) -> dict:
        font = self._current_font()
        is_ascii = "ASCII art" in mode
        return {
            "mode": mode,
            "cols": self.columns_spin.value(),
            "charset": self.charset_specs.get(self.charset_box.currentText().lstrip("🔠 ▓ 🔍 ▪ 01 🔢 🔤 ⚬ ✦ ╋ ⬡ ✨ ").strip(), ASCII_SETS["Standard"]),
            "invert": self.invert_check.isChecked(),
            "contrast": self.contrast_spin.value(),
            "color": is_ascii and self.color_check.isChecked(),
            "font": font,
            "font_pt": max(4, font.pointSize()),
            "emoji_spec": None if is_ascii else self.emoji_specs.get(mode),
            "formats": formats,
        }

    def batch_convert(self):
        modes = ["ASCII art"] + list(self.emoji_specs.keys())
        dlg = BatchDialog(self, modes, self.mode_box.currentText())
        dlg.exec()

    def convert(self):
        if self.source_image is None:
            return
        self.statusBar().showMessage("Processing...")
        
        img = apply_adjustments(self.source_image, self.invert_check.isChecked(),
                                self.contrast_spin.value())
        mode = self.mode_box.currentText()
        cols = self.columns_spin.value()
        font = self._current_font()

        if "ASCII art" in mode:
            clean_charset = self.charset_box.currentText().lstrip("🔠 ▓ 🔍 ▪ 01 🔢 🔤 ⚬ ✦ ╋ ⬡ ✨ ").strip()
            self.plain_text, self.result_colors, self.html_text = image_to_ascii(
                img, cols,
                self.charset_specs.get(clean_charset, ASCII_SETS["Standard"]),
                color=self.color_check.isChecked(),
                font_family=font.family(), font_pt=max(4, font.pointSize()))
        else:
            spec = self.emoji_specs.get(mode)
            if spec is None:
                return
            self.plain_text = image_to_emoji(img, cols, spec)
            self.result_colors = None
            self.html_text = None

        if self.html_text is not None:
            self.output.setHtml(self.html_text)
        else:
            self.output.setPlainText(self.plain_text)

        rows = grid_size(self.source_image, cols)[1]
        self.statusBar().showMessage(
            f"Ready: {mode} | {cols} × {rows} cells | Original: {self.source_image.size[0]}×{self.source_image.size[1]} px")

    def copy_output(self):
        if not self.plain_text:
            QMessageBox.information(self, "Nothing to copy", "Convert an image first.")
            return
        QGuiApplication.clipboard().setText(self.plain_text)
        self.statusBar().showMessage("Copied to clipboard.", 2500)

    def save_text(self):
        if not self.plain_text:
            QMessageBox.information(self, "Nothing to save", "Convert an image first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save text file", "output.txt", "Text files (*.txt);;All files (*)")
        if not path:
            return
        Path(path).write_text(self.plain_text, encoding="utf-8")
        self.statusBar().showMessage(f"Saved TXT to {path}", 4000)

    def save_png(self):
        if not self.plain_text:
            QMessageBox.information(self, "Nothing to save", "Convert an image first.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save PNG image", "output.png", "PNG images (*.png);;All files (*)")
        if not path:
            return
        
        sample = "M"
        if "ASCII art" not in self.mode_box.currentText():
            for line in self.plain_text.split("\n"):
                cl = split_clusters(line)
                if cl:
                    sample = cl[0]
                    break
                    
        image = render_grid_image(self.plain_text, self._current_font(), sample,
                                  self.result_colors, bg="#ffffff")
        if not image.save(path):
            QMessageBox.critical(self, "Save failed", f"Could not write {path}")
        else:
            self.statusBar().showMessage(f"Saved PNG to {path}", 4000)

    def show_about(self):
        QMessageBox.about(
            self, "About",
            "<b>ASCII / Emoji Image Converter v3.3</b><br><br>"
            "Converts any image into ASCII art or an emoji mosaic.<br><br>"
            "<b>NEW: Automatic Resolution Matching</b><br>"
            "• Enable 'Match resolution on import' to auto-calculate the optimal column count.<br>"
            "• Adjust 'Cell size' to control detail density (smaller = more detail).<br>"
            "• Font size also auto-adjusts to fit the output area nicely.<br><br>"
            "<b>Workflow:</b><br>"
            "1. <b>Load</b> an image via the top toolbar.<br>"
            "2. <b>Adjust</b> parameters in the settings bar.<br>"
            "3. <b>Export</b> using the toolbar buttons (Copy, TXT, PNG).<br><br>"
            "<b>Tips:</b><br>"
            "• ASCII output requires a <i>monospaced</i> font for proper alignment.<br>"
            "• Emoji rendering relies on system color-emoji fonts (e.g., Segoe UI Emoji).<br>"
            "• Use the blue 'Manage Custom Sets' button to create your own palettes!",
        )


def main():
    import os
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    app = QApplication(sys.argv)
    app.setApplicationName("AsciiEmojiConverter")
    app.setOrganizationName("AsciiEmojiConverter")
    app.setStyle("Fusion")
    
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()