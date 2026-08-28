#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

import requests
import cairosvg
from PIL import Image, ImageDraw, ImageFont

DPI = 200
PAGE_W = 1654
PAGE_H = 2339
MARGIN_X = 90
MARGIN_Y = 75
CACHE_DIR = Path.home() / ".cache" / "kanji-practice" / "kanjivg"
KANJIVG_RAW = "https://raw.githubusercontent.com/KanjiVG/kanjivg/master/kanji/{code}.svg"

BLACK = (20, 20, 20)
DARK = (65, 65, 65)
MID = (145, 145, 145)
LIGHT = (205, 205, 205)
VERY_LIGHT = (232, 232, 232)
WHITE = (255, 255, 255)


def unicode_filename(char: str) -> str:
  return f"{ord(char):05x}.svg"


def get_svg(char: str) -> str:
  CACHE_DIR.mkdir(parents=True, exist_ok=True)
  filename = unicode_filename(char)
  cached = CACHE_DIR / filename
  if cached.exists():
    return cached.read_text(encoding="utf-8")

  url = KANJIVG_RAW.format(code=filename[:-4])
  r = requests.get(url, timeout=20)
  if r.status_code == 404:
    raise ValueError(f"KanjiVG не содержит {char!r} (U+{ord(char):04X})")
  r.raise_for_status()
  cached.write_bytes(r.content)
  return r.text


def extract_strokes(svg_text: str) -> list[str]:
  root = ET.fromstring(svg_text)
  strokes = []
  for el in root.iter():
    if el.tag.endswith("path"):
      d = el.attrib.get("d")
      if d:
        strokes.append(d)
  if not strokes:
    raise ValueError("В SVG не найдено ни одной черты")
  return strokes


def build_svg(paths: list[str], *, current_index: int | None = None) -> str:
  if current_index is None:
    body = "\n".join(f'<path d="{d}" stroke="#202020" />' for d in paths)
  else:
    items = []
    for i, d in enumerate(paths):
      if i < current_index:
        items.append(f'<path d="{d}" stroke="#a8a8a8" />')
      elif i == current_index:
        items.append(f'<path d="{d}" stroke="#111111" />')
      else:
        break
    body = "\n".join(items)

  return f'''<svg xmlns="http://www.w3.org/2000/svg" width="109" height="109" viewBox="0 0 109 109">
<rect width="109" height="109" fill="white"/>
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
  return Image.open(io.BytesIO(png)).convert("RGB")


def load_font(size: int):
  candidates = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
  ]
  for p in candidates:
    if Path(p).exists():
      try:
        return ImageFont.truetype(p, size)
      except OSError:
        pass
  return ImageFont.load_default()


def draw_centered(draw, box, text, font, fill=BLACK):
  x0, y0, x1, y1 = box
  bbox = draw.textbbox((0, 0), text, font=font)
  tw = bbox[2] - bbox[0]
  th = bbox[3] - bbox[1]
  x = x0 + (x1 - x0 - tw) / 2 - bbox[0]
  y = y0 + (y1 - y0 - th) / 2 - bbox[1]
  draw.text((x, y), text, font=font, fill=fill)


def draw_grid_cell(page, x, y, size, kanji_img=None, opacity=1.0):
  draw = ImageDraw.Draw(page)
  draw.rectangle((x, y, x + size, y + size), outline=MID, width=2)
  draw.line((x + size // 2, y, x + size // 2, y + size), fill=LIGHT, width=1)
  draw.line((x, y + size // 2, x + size, y + size // 2), fill=LIGHT, width=1)
  draw.line((x, y, x + size, y + size), fill=VERY_LIGHT, width=1)
  draw.line((x + size, y, x, y + size), fill=VERY_LIGHT, width=1)

  if kanji_img is not None:
    glyph = kanji_img.resize((size - 18, size - 18))
    if opacity < 1:
      white = Image.new("RGB", glyph.size, WHITE)
      glyph = Image.blend(white, glyph, opacity)
    page.paste(glyph, (x + 9, y + 9))


def make_step_image(paths, step, size):
  return render_svg(build_svg(paths, current_index=step), size)


def make_full_image(paths, size):
  return render_svg(build_svg(paths), size)


def create_page(char: str, paths: list[str]) -> Image.Image:
  page = Image.new("RGB", (PAGE_W, PAGE_H), WHITE)
  draw = ImageDraw.Draw(page)

  small_font = load_font(26)
  tiny_font = load_font(20)

  draw.text((MARGIN_X, MARGIN_Y), f"U+{ord(char):04X}", font=small_font, fill=DARK)
  draw.text((MARGIN_X, MARGIN_Y + 45), f"{len(paths)} strokes", font=tiny_font, fill=MID)

  hero_size = 190
  hero = make_full_image(paths, hero_size)
  page.paste(hero, (PAGE_W - MARGIN_X - hero_size, MARGIN_Y - 15))

  top = 285
  draw.text((MARGIN_X, top - 45), "Stroke order", font=small_font, fill=BLACK)

  n = len(paths)
  if n <= 10:
    cols, step_size, gap = 10, 125, 22
  elif n <= 16:
    cols, step_size, gap = 8, 128, 25
  else:
    cols, step_size, gap = 10, 105, 18

  step_rows = (n + cols - 1) // cols

  for i in range(n):
    row, col = divmod(i, cols)
    x = MARGIN_X + col * (step_size + gap)
    y = top + row * (step_size + 55)
    draw.rectangle((x, y, x + step_size, y + step_size), outline=LIGHT, width=1)
    step_img = make_step_image(paths, i, step_size - 8)
    page.paste(step_img, (x + 4, y + 4))
    draw_centered(draw, (x, y + step_size + 3, x + step_size, y + step_size + 36), str(i + 1), tiny_font, DARK)

  practice_top = top + step_rows * (step_size + 55) + 65
  draw.text((MARGIN_X, practice_top - 42), "Practice", font=small_font, fill=BLACK)

  cols, rows, gap = 6, 5, 18
  available_w = PAGE_W - 2 * MARGIN_X
  cell = (available_w - gap * (cols - 1)) // cols
  available_h = PAGE_H - practice_top - MARGIN_Y - 50
  cell = min(cell, (available_h - gap * (rows - 1)) // rows)
  if cell < 90:
    rows = 4
    cell = min((available_w - gap * (cols - 1)) // cols,
        (available_h - gap * (rows - 1)) // rows)

  full = make_full_image(paths, cell)

  for row in range(rows):
    for col in range(cols):
      x = MARGIN_X + col * (cell + gap)
      y = practice_top + row * (cell + gap)
      if row == 0:
        img = full
        opacity = 1.0 if col == 0 else 0.48
      elif row == 1:
        img = full
        opacity = 0.23
      else:
        img = None
        opacity = 0.0
      draw_grid_cell(page, x, y, cell, img, opacity)

  draw.text(
    (MARGIN_X, PAGE_H - 42),
    "© 2026 Jonhef · Stroke data: KanjiVG · CC BY-SA 3.0",
    font=tiny_font,
    fill=MID,
  )
  return page


def normalize_chars(text: str) -> list[str]:
  result = []
  seen = set()
  for ch in text:
    if ch.isspace():
      continue
    if ch not in seen:
      result.append(ch)
      seen.add(ch)
  return result


def make_pdf(text: str, output: Path):
  chars = normalize_chars(text)
  if not chars:
    raise ValueError("Не введено ни одного символа")

  pages = []
  print(f"Символов: {len(chars)}")

  for i, char in enumerate(chars, 1):
    print(f"[{i}/{len(chars)}] {char} (U+{ord(char):04X})", flush=True)
    try:
      svg = get_svg(char)
      paths = extract_strokes(svg)
    except Exception as e:
      print(f"  Пропущен: {e}", file=sys.stderr)
      continue
    pages.append(create_page(char, paths))

  if not pages:
    raise RuntimeError("Не удалось построить ни одной страницы")

  output.parent.mkdir(parents=True, exist_ok=True)
  pages[0].save(output, "PDF", save_all=True, append_images=pages[1:], resolution=DPI)
  print(f"\nГотово: {output.resolve()}")


def main():
  parser = argparse.ArgumentParser(description="Генератор прописей кандзи с порядком черт")
  parser.add_argument("text", nargs="?", help="Кандзи, например 日本語勉強")
  parser.add_argument("-o", "--output", default="kanji_practice.pdf", help="Имя выходного PDF")
  args = parser.parse_args()

  text = args.text or input("Введи кандзи: ").strip()

  try:
    make_pdf(text, Path(args.output))
  except KeyboardInterrupt:
    print("\nОтменено", file=sys.stderr)
    raise SystemExit(130)
  except Exception as e:
    print(f"\nОшибка: {e}", file=sys.stderr)
    raise SystemExit(1)


if __name__ == "__main__":
  main()
