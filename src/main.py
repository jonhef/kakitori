#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import io
import math
import sys
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

import cairosvg
import requests
from PIL import Image, ImageDraw, ImageFont
from svgpathtools import parse_path

DPI = 200
PAGE_W = 1654
PAGE_H = 2339

# The layout follows the supplied A4 reference: five character bands, twelve
# large practice cells per row, and a half-cell guide grid in the upper rows.
GRID_LEFT = 119
GRID_TOP = 292
MAJOR_COLS = 12
CELL = 118
GRID_W = MAJOR_COLS * CELL
CHARS_PER_PAGE = 5
SECTION_H = CELL * 3
GRID_H = CHARS_PER_PAGE * SECTION_H

CACHE_DIR = Path.home() / ".cache" / "kanji-practice" / "kanjivg"
KANJIVG_RAW = "https://raw.githubusercontent.com/KanjiVG/kanjivg/master/kanji/{code}.svg"

BLACK = (18, 18, 18)
MID = (143, 147, 151)
GRID = (34, 34, 34)
GRID_FINE = (96, 96, 96)
RED = "#e53935"
WHITE = (255, 255, 255)
GUIDE_OFFSET = 9.0


def configure_console() -> None:
  """Keep Japanese progress output readable in the Windows console."""
  if sys.platform != "win32":
    return
  for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
      reconfigure(encoding="utf-8", errors="replace")


def unicode_filename(char: str) -> str:
  return f"{ord(char):05x}.svg"


def get_svg(char: str) -> str:
  CACHE_DIR.mkdir(parents=True, exist_ok=True)
  filename = unicode_filename(char)
  cached = CACHE_DIR / filename
  if cached.exists():
    return cached.read_text(encoding="utf-8")

  url = KANJIVG_RAW.format(code=filename[:-4])
  response = requests.get(url, timeout=20)
  if response.status_code == 404:
    raise ValueError(f"KanjiVG не содержит {char!r} (U+{ord(char):04X})")
  response.raise_for_status()
  cached.write_bytes(response.content)
  return response.text


def extract_strokes(svg_text: str) -> list[str]:
  root = ET.fromstring(svg_text)
  strokes = []
  for element in root.iter():
    if element.tag.endswith("path"):
      path = element.attrib.get("d")
      if path:
        strokes.append(path)
  if not strokes:
    raise ValueError("В SVG не найдено ни одной черты")
  return strokes


@lru_cache(maxsize=4096)
def make_direction_guide(path_data: str) -> tuple[str, float, float]:
  """Build a constant-distance guide on the upper-left side of a stroke."""
  try:
    path = parse_path(path_data)
    length = path.length()
    if length <= 0:
      return path_data, path.start.real, path.start.imag

    sample_count = max(10, min(56, math.ceil(length / 2.5) + 1))
    probe = path.point(0.18) - path.point(0)
    if abs(probe) < 1e-6:
      probe = path.unit_tangent(0)

    # Pick the perpendicular that points towards the free upper-left area,
    # matching the guide placement in the supplied writing-sheet reference.
    base_normal = 1j * probe / abs(probe)
    target = complex(-1, -1)
    dot = base_normal.real * target.real + base_normal.imag * target.imag
    side = 1 if dot >= 0 else -1

    points = []
    for index in range(sample_count):
      parameter = index / (sample_count - 1)
      point = path.point(parameter)
      tangent = path.unit_tangent(parameter)
      guide_point = point + side * 1j * tangent * GUIDE_OFFSET
      points.append(guide_point)

    commands = [f"M{points[0].real:.2f},{points[0].imag:.2f}"]
    commands.extend(f"L{point.real:.2f},{point.imag:.2f}" for point in points[1:])
    return " ".join(commands), path.start.real, path.start.imag
  except (AssertionError, ValueError, ZeroDivisionError):
    # KanjiVG paths are well-formed; this keeps an unusual future path usable.
    return path_data, 10.0, 18.0


def build_svg(
    paths: list[str],
    *,
    current_index: int | None = None,
    stroke_color: str = "#171717",
) -> str:
  if current_index is None:
    body = "\n".join(f'<path d="{path}" stroke="{stroke_color}" />' for path in paths)
  else:
    items = []
    for index, path in enumerate(paths):
      if index < current_index:
        items.append(f'<path d="{path}" stroke="#171717" />')
      elif index == current_index:
        items.append(
          f'<path d="{path}" stroke="#171717" />'
        )
        guide, start_x, start_y = make_direction_guide(path)
        items.append(
          f'<path d="{guide}" stroke="{RED}" stroke-width="1.15" '
          'marker-end="url(#stroke-arrow)" />'
        )
        number_x = max(2.0, min(100.0, start_x - 8.0))
        number_y = max(15.0, min(106.0, start_y - 6.0))
        items.append(
          f'<text x="{number_x:.2f}" y="{number_y:.2f}" fill="#171717" stroke="none" '
          f'font-family="Arial, sans-serif" font-size="14" font-weight="700">{index + 1}</text>'
        )
      else:
        break
    body = "\n".join(items)

  return f'''<svg xmlns="http://www.w3.org/2000/svg" width="109" height="109" viewBox="0 0 109 109">
<defs>
  <marker id="stroke-arrow" viewBox="0 0 8 8" refX="7" refY="4"
      markerWidth="8" markerHeight="8" orient="auto" markerUnits="userSpaceOnUse">
    <path d="M0,0 L7,4 L0,8" fill="none" stroke="{RED}" stroke-width="1.15"
        stroke-linecap="round" stroke-linejoin="round" />
  </marker>
</defs>
<g fill="none" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
{body}
</g>
</svg>'''


def render_svg(svg: str, size: int) -> Image.Image:
  png = cairosvg.svg2png(
    bytestring=svg.encode("utf-8"),
    output_width=size,
    output_height=size,
  )
  return Image.open(io.BytesIO(png)).convert("RGBA")


def load_font(size: int, *, japanese: bool = False):
  japanese_candidates = [
    r"C:\Windows\Fonts\YuGothR.ttc",
    r"C:\Windows\Fonts\meiryo.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
  ]
  latin_candidates = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
  ]
  candidates = japanese_candidates + latin_candidates if japanese else latin_candidates
  for candidate in candidates:
    if Path(candidate).exists():
      try:
        return ImageFont.truetype(candidate, size)
      except OSError:
        pass
  return ImageFont.load_default()


def paste_with_opacity(
    page: Image.Image,
    image: Image.Image,
    xy: tuple[int, int],
    opacity: float = 1.0,
) -> None:
  image = image.copy()
  if opacity < 1.0:
    alpha = image.getchannel("A").point(lambda value: round(value * opacity))
    image.putalpha(alpha)
  page.paste(image, xy, image)


def paste_glyph(
    page: Image.Image,
    glyph: Image.Image,
    box: tuple[int, int, int, int],
    *,
    padding: int,
    opacity: float = 1.0,
) -> None:
  x0, y0, x1, y1 = box
  size = max(1, min(x1 - x0, y1 - y0) - 2 * padding)
  resized = glyph.resize((size, size), Image.Resampling.LANCZOS)
  x = x0 + (x1 - x0 - size) // 2
  y = y0 + (y1 - y0 - size) // 2
  paste_with_opacity(page, resized, (x, y), opacity)


def make_step_image(paths: list[str], step: int, size: int) -> Image.Image:
  return render_svg(build_svg(paths, current_index=step), size)


def make_full_image(paths: list[str], size: int, color: str = "#171717") -> Image.Image:
  return render_svg(build_svg(paths, stroke_color=color), size)


def draw_sheet_grid(page: Image.Image) -> None:
  draw = ImageDraw.Draw(page)
  right = GRID_LEFT + GRID_W
  bottom = GRID_TOP + GRID_H

  # Major verticals continue through the entire writing area.
  for column in range(MAJOR_COLS + 1):
    x = GRID_LEFT + column * CELL
    width = 4 if column in (0, MAJOR_COLS) else 2
    draw.line((x, GRID_TOP, x, bottom), fill=GRID, width=width)

  for section in range(CHARS_PER_PAGE):
    y = GRID_TOP + section * SECTION_H

    # The upper two rows are split into half-cells, just like the reference.
    for column in range(MAJOR_COLS):
      x = GRID_LEFT + column * CELL + CELL // 2
      draw.line((x, y, x, y + 2 * CELL), fill=GRID_FINE, width=1)

    draw.line((GRID_LEFT, y + CELL // 2, right, y + CELL // 2), fill=GRID_FINE, width=1)
    draw.line((GRID_LEFT, y + CELL, right, y + CELL), fill=GRID, width=2)
    draw.line((GRID_LEFT, y + CELL + CELL // 2, right, y + CELL + CELL // 2), fill=GRID_FINE, width=1)
    draw.line((GRID_LEFT, y + 2 * CELL, right, y + 2 * CELL), fill=GRID, width=2)
    draw.line((GRID_LEFT, y, right, y), fill=GRID, width=4)

  draw.line((GRID_LEFT, bottom, right, bottom), fill=GRID, width=4)


def major_box(section_top: int, row: int, column: int) -> tuple[int, int, int, int]:
  x = GRID_LEFT + column * CELL
  y = section_top + row * CELL
  return x, y, x + CELL, y + CELL


def mini_box(section_top: int, row: int, column: int) -> tuple[int, int, int, int]:
  mini = CELL // 2
  x = GRID_LEFT + column * mini
  y = section_top + row * mini
  return x, y, x + mini, y + mini


def draw_character_band(page: Image.Image, section: int, paths: list[str]) -> None:
  section_top = GRID_TOP + section * SECTION_H
  large_size = CELL - 12
  full = make_full_image(paths, large_size)
  trace = make_full_image(paths, large_size, "#8f9397")

  paste_glyph(page, full, major_box(section_top, 0, 0), padding=6)
  paste_glyph(page, trace, major_box(section_top, 1, 0), padding=10, opacity=0.92)
  paste_glyph(page, trace, major_box(section_top, 2, 0), padding=10, opacity=0.92)

  if len(paths) <= 21:
    slots = [
      major_box(section_top, row, column)
      for row in range(2)
      for column in range(1, MAJOR_COLS)
    ]
    for index, path_box in enumerate(slots[:len(paths)]):
      step_image = make_step_image(paths, index, large_size)
      paste_glyph(page, step_image, path_box, padding=7)

    final_box = slots[len(paths)]
    paste_glyph(page, trace, final_box, padding=8, opacity=0.96)
    return

  # Complex characters use the half-cell grid so every stroke remains visible.
  slots = [
    mini_box(section_top, row, column)
    for row in range(4)
    for column in range(2, MAJOR_COLS * 2)
  ]
  mini_size = CELL // 2 - 5
  for index, path_box in enumerate(slots[:len(paths)]):
    step_image = make_step_image(paths, index, mini_size)
    paste_glyph(page, step_image, path_box, padding=2)

  if len(paths) < len(slots):
    compact_trace = make_full_image(paths, mini_size, "#8f9397")
    paste_glyph(page, compact_trace, slots[len(paths)], padding=2)


def script_title(chars: list[str]) -> str:
  codepoints = [ord(char) for char in chars]
  if all(0x3040 <= codepoint <= 0x309F for codepoint in codepoints):
    return "Hiragana Writing Practice Sheet"
  if all(0x30A0 <= codepoint <= 0x30FF for codepoint in codepoints):
    return "Katakana Writing Practice Sheet"
  if all(0x3400 <= codepoint <= 0x9FFF for codepoint in codepoints):
    return "Kanji Writing Practice Sheet"
  return "Japanese Writing Practice Sheet"


def create_page(entries: list[tuple[str, list[str]]], page_number: int) -> Image.Image:
  page = Image.new("RGB", (PAGE_W, PAGE_H), WHITE)
  draw = ImageDraw.Draw(page)
  title_font = load_font(36, japanese=True)
  footer_font = load_font(18)
  chars = [char for char, _ in entries]
  title = f"{script_title(chars)} {page_number:02d} — {'  '.join(chars)}"
  draw.text((GRID_LEFT + 8, GRID_TOP - 82), title, font=title_font, fill=BLACK)

  draw_sheet_grid(page)
  for section, (_, paths) in enumerate(entries):
    draw_character_band(page, section, paths)

  draw.text(
    (GRID_LEFT, PAGE_H - 48),
    "© 2026 Jonhef · Stroke data: KanjiVG · CC BY-SA 3.0",
    font=footer_font,
    fill=MID,
  )
  return page


def normalize_chars(text: str) -> list[str]:
  result = []
  seen = set()
  for char in text:
    if char.isspace():
      continue
    if char not in seen:
      result.append(char)
      seen.add(char)
  return result


def page_batches(entries: list[tuple[str, list[str]]]):
  """Keep writing systems on separate sheets and number each series from one."""
  current_system = None
  current_page = []
  page_number = 0

  for entry in entries:
    writing_system = script_title([entry[0]])
    if writing_system != current_system:
      if current_page:
        yield page_number, current_page
      current_system = writing_system
      current_page = []
      page_number = 1
    elif len(current_page) == CHARS_PER_PAGE:
      yield page_number, current_page
      current_page = []
      page_number += 1
    current_page.append(entry)

  if current_page:
    yield page_number, current_page


def make_pdf(text: str, output: Path) -> None:
  chars = normalize_chars(text)
  if not chars:
    raise ValueError("Не введено ни одного символа")

  entries = []
  print(f"Символов: {len(chars)}")
  for index, char in enumerate(chars, 1):
    print(f"[{index}/{len(chars)}] {char} (U+{ord(char):04X})", flush=True)
    try:
      svg = get_svg(char)
      entries.append((char, extract_strokes(svg)))
    except Exception as error:
      print(f"  Пропущен: {error}", file=sys.stderr)

  if not entries:
    raise RuntimeError("Не удалось построить ни одной страницы")

  pages = [create_page(page_entries, page_number) for page_number, page_entries in page_batches(entries)]

  output.parent.mkdir(parents=True, exist_ok=True)
  pages[0].save(output, "PDF", save_all=True, append_images=pages[1:], resolution=DPI)
  print(f"\nГотово: {output.resolve()} ({len(pages)} стр.)")


def main() -> None:
  configure_console()
  parser = argparse.ArgumentParser(description="Генератор японских прописей с порядком черт")
  parser.add_argument("text", nargs="?", help="Символы, например あいうえお или 日本語")
  parser.add_argument("-o", "--output", default="kanji_practice.pdf", help="Имя выходного PDF")
  args = parser.parse_args()

  text = args.text or input("Введи символы: ").strip()
  try:
    make_pdf(text, Path(args.output))
  except KeyboardInterrupt:
    print("\nОтменено", file=sys.stderr)
    raise SystemExit(130)
  except Exception as error:
    print(f"\nОшибка: {error}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
  main()
