"""Builds the profile README and every image it shows, from scripts/profile.json.

    python3 scripts/build_readme.py [--fonts ../Portfolio/src/assets/fonts] [--portrait ../Portfolio/public/images/avatar-cutout.webp]

Each image is an SVG in assets/readme/, in a dark and a light version that the README swaps with
prefers-color-scheme. Text is set in the portfolio's own fonts (Antonio, Inter, JetBrains Mono): each SVG
embeds only the letters it uses, as WOFF2, so it renders the same everywhere and stays small.
Needs fonttools and brotli (pip install fonttools brotli).

The Latest writing list between the BLOG-POST-LIST markers is kept from the current README, because a
workflow rewrites it there.
"""

import argparse
import base64
import io
import json
import re
from functools import lru_cache
from html import escape
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "readme"
W = 880

THEMES = {
    "dark": dict(bg="#07090A", panel="#0B0F0E", line="#1C2622", grid="#34D399", grid_a=0.06, text="#F2F5F3",
                 muted="#97A39E", faint="#5E6B66", accent="#34D399", accent_text="#34D399", on_accent="#04120C",
                 glow_a=0.22, ghost_a=0.07, code_kw="#34D399", code_str="#A7F3D0", code_cm="#5E6B66", code_num="#FBBF24"),
    "light": dict(bg="#F4F8F6", panel="#FFFFFF", line="#D5E1DB", grid="#0D8F63", grid_a=0.07, text="#0B1210",
                  muted="#4F5E58", faint="#7D8B85", accent="#10B981", accent_text="#0B7A55", on_accent="#FFFFFF",
                  glow_a=0.16, ghost_a=0.08, code_kw="#0B7A55", code_str="#0E6B4C", code_cm="#7D8B85", code_num="#B45309"),
}

# family, weight → file in the fonts directory
FACES = {
    ("display", 600): ("antonio-latin.woff2", 600),
    ("display", 700): ("antonio-latin.woff2", 700),
    ("sans", 400): ("inter-latin.woff2", 400),
    ("sans", 600): ("inter-latin.woff2", 600),
    ("mono", 400): ("jetbrains-mono-latin.woff2", 400),
}
FONTS_DIR = None


@lru_cache(None)
def instance(family, weight):
    """A static TTFont for one weight of the variable font."""
    file, wght = FACES[(family, weight)]
    font = TTFont(FONTS_DIR / file)
    if "fvar" in font:
        font = instancer.instantiateVariableFont(font, {"wght": wght})
    return font


@lru_cache(None)
def instance_bytes(family, weight):
    buf = io.BytesIO()
    instance(family, weight).save(buf)
    return buf.getvalue()


@lru_cache(None)
def metrics(family, weight):
    font = instance(family, weight)
    cmap = font.getBestCmap()
    hmtx = font["hmtx"].metrics
    upm = font["head"].unitsPerEm
    return cmap, hmtx, upm


def width(text, family, weight, size, tracking=0.0):
    cmap, hmtx, upm = metrics(family, weight)
    total = 0
    for ch in text:
        glyph = cmap.get(ord(ch)) or cmap.get(ord("?"))
        total += hmtx[glyph][0] if glyph else upm * 0.5
    return total * size / upm + tracking * max(0, len(text) - 1)


def wrap(text, family, weight, size, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and width(trial, family, weight, size) > max_width:
            lines.append(line)
            line = word
        else:
            line = trial
    if line:
        lines.append(line)
    return lines


class Svg:
    """Collects text per face so each SVG embeds only the glyphs it draws."""

    def __init__(self, w, h, theme):
        self.w, self.h, self.t = w, h, THEMES[theme]
        self.parts, self.used, self.defs = [], {}, []

    def add(self, s):
        self.parts.append(s)

    def text(self, x, y, s, family, weight, size, fill, tracking=0, anchor="start", opacity=None, style=""):
        self.used.setdefault((family, weight), set()).update(s)
        op = f' opacity="{opacity}"' if opacity is not None else ""
        ls = f' letter-spacing="{tracking}"' if tracking else ""
        self.add(f'<text x="{x:.1f}" y="{y:.1f}" class="{family}{weight}" font-size="{size}" fill="{fill}"'
                 f' text-anchor="{anchor}"{ls}{op}{style}>{escape(s)}</text>')

    def fonts_css(self):
        css = []
        for (family, weight), chars in self.used.items():
            opts = subset.Options()
            opts.flavor, opts.layout_features, opts.name_IDs, opts.notdef_outline = "woff2", ["kern", "liga"], [], True
            sub = subset.Subsetter(opts)
            sub.populate(text="".join(sorted(chars | {" "})))
            f = TTFont(io.BytesIO(instance_bytes(family, weight)))  # a fresh copy: subsetting edits the font
            sub.subset(f)
            f.flavor = "woff2"
            buf = io.BytesIO()
            f.save(buf)
            data = base64.b64encode(buf.getvalue()).decode()
            css.append(f"@font-face{{font-family:f-{family}{weight};src:url(data:font/woff2;base64,{data}) format('woff2')}}"
                       f".{family}{weight}{{font-family:f-{family}{weight}}}")
        return "".join(css)

    def render(self, title):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="{self.w}" '
                f'height="{self.h}" viewBox="0 0 {self.w} {self.h}" role="img"><title>{escape(title)}</title>'
                f'<style>{self.fonts_css()}</style><defs>{"".join(self.defs)}</defs>{"".join(self.parts)}</svg>')


def frame(svg, h, radius=18, glow=None):
    """Panel background: the portfolio's page grid, an emerald glow, a hairline border."""
    t = svg.t
    uid = len(svg.defs)
    svg.defs.append(f'<clipPath id="c{uid}"><rect width="{svg.w}" height="{h}" rx="{radius}"/></clipPath>'
                    f'<radialGradient id="g{uid}" cx="{glow[0] if glow else 0.08}" cy="{glow[1] if glow else 0.3}" r="0.55">'
                    f'<stop offset="0" stop-color="{t["accent"]}" stop-opacity="{t["glow_a"]}"/>'
                    f'<stop offset="1" stop-color="{t["accent"]}" stop-opacity="0"/></radialGradient>')
    svg.add(f'<g clip-path="url(#c{uid})"><rect width="{svg.w}" height="{h}" fill="{t["bg"]}"/>')
    lines = "".join(f'<path d="M{x} 0V{h}"/>' for x in range(44, svg.w, 44))
    lines += "".join(f'<path d="M0 {y}H{svg.w}"/>' for y in range(44, h, 44))
    svg.add(f'<g stroke="{t["grid"]}" stroke-opacity="{t["grid_a"]}" stroke-width="1">{lines}</g>')
    svg.add(f'<rect width="{svg.w}" height="{h}" fill="url(#g{uid})"/></g>')
    svg.add(f'<rect x="0.5" y="0.5" width="{svg.w - 1}" height="{h - 1}" rx="{radius}" fill="none" stroke="{t["line"]}"/>')


def hero(p, theme, portrait):
    h = 460
    s = Svg(W, h, theme)
    t = s.t
    frame(s, h, glow=(0.12, 0.42))
    s.text(44, 132, p["label"].upper(), "sans", 600, 12, t["accent_text"], tracking=2.6)
    s.text(40, 228, p["name"].upper(), "display", 700, 104, t["text"])
    s.text(44, 278, p["headline"], "sans", 600, 26, t["text"])
    for i, line in enumerate(wrap(p["tagline"], "sans", 400, 15, 380)):
        s.text(44, 316 + i * 23, line, "sans", 400, 15, t["muted"])
    s.text(44, h - 36, p["footnote"].upper(), "mono", 400, 11, t["faint"], tracking=1.2)
    # Portrait, anchored bottom-right, with an emerald rim like the site's hero
    ph = 430
    pw = ph * 1672 / 941
    s.defs.append(f'<filter id="rim" x="-10%" y="-10%" width="120%" height="120%">'
                  f'<feDropShadow dx="0" dy="0" stdDeviation="{5 if theme == "dark" else 3}" flood-color="{t["accent"]}" '
                  f'flood-opacity="{0.75 if theme == "dark" else 0.35}"/></filter>')
    s.add(f'<image x="{W - pw + 38:.0f}" y="{h - ph:.0f}" width="{pw:.0f}" height="{ph:.0f}" filter="url(#rim)" '
          f'href="data:image/webp;base64,{portrait}" xlink:href="data:image/webp;base64,{portrait}"/>')
    s.add(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{h - 1}" rx="18" fill="none" stroke="{t["line"]}"/>')
    return s.render(f'{p["name"]}: {p["headline"]}')


def button(label, primary, theme):
    t = THEMES[theme]
    size, pad = 14, 22
    arrow = " →" if primary else " ↗"
    w = width(label + arrow, "sans", 600, size) + pad * 2
    s = Svg(int(w + 2), 44, theme)
    if primary:
        s.add(f'<rect x="1" y="1" width="{w:.1f}" height="42" rx="21" fill="{t["accent"]}"/>')
        s.text(1 + pad, 27.5, label + arrow, "sans", 600, size, t["on_accent"])
    else:
        s.add(f'<rect x="1" y="1" width="{w:.1f}" height="42" rx="21" fill="{t["panel"]}" stroke="{t["line"]}"/>')
        s.text(1 + pad, 27.5, label + arrow, "sans", 600, size, t["text"])
    return s.render(label)


def header(num, label, theme):
    t = THEMES[theme]
    s = Svg(W, 72, theme)
    s.text(0, 48, f"{num}.", "display", 600, 30, t["accent_text"])
    x = width(f"{num}.", "display", 600, 30) + 12
    s.text(x, 48, label.upper(), "display", 600, 30, t["text"], tracking=0.5)
    lx = x + width(label.upper(), "display", 600, 30, 0.5) + 20
    s.add(f'<path d="M{lx:.0f} 37.5H{W}" stroke="{t["line"]}" stroke-width="1"/>')
    return s.render(f"{num}. {label}")


def featured(item, index, theme):
    t = THEMES[theme]
    body = wrap(item["body"], "sans", 400, 15, 700)
    h = 172 + len(body) * 23
    s = Svg(W, h, theme)
    frame(s, h, glow=(0.95, 0.1))
    s.text(W - 36, h - 18, f"{index:02d}", "display", 700, 150, t["accent"], anchor="end", opacity=t["ghost_a"])
    s.text(40, 52, item["meta"].upper(), "mono", 400, 11, t["accent_text"], tracking=1.4)
    s.text(38, 96, item["title"], "display", 600, 38, t["text"])
    for i, line in enumerate(body):
        s.text(40, 132 + i * 23, line, "sans", 400, 15, t["muted"])
    s.text(40, h - 28, item["link"] + " →", "mono", 400, 12, t["faint"])
    return s.render(f'{item["title"]}: {item["body"]}')


def card(item, theme):
    t = THEMES[theme]
    w = 432
    body = wrap(item["body"], "sans", 400, 14, w - 64)
    h = 210
    s = Svg(w, h, theme)
    s.w = w
    frame(s, h, radius=16, glow=(0.9, 0.0))
    s.text(30, 44, item["meta"].upper(), "mono", 400, 10.5, t["accent_text"], tracking=1.2)
    s.text(29, 82, item["title"], "display", 600, 30, t["text"])
    for i, line in enumerate(body[:4]):
        s.text(30, 112 + i * 21, line, "sans", 400, 14, t["muted"])
    return s.render(f'{item["title"]}: {item["body"]}')


def experience(p, theme):
    t = THEMES[theme]
    rows = []
    for e in p["experience"]:
        rows.append((e, wrap(e["body"], "sans", 400, 14.5, 640) if e["body"] else []))
    h = 64 + sum(78 + len(b) * 22 for _, b in rows) + 120
    s = Svg(W, h, theme)
    frame(s, h, glow=(0.0, 0.0))
    x0, y = 48, 64
    s.add(f'<path d="M{x0} {y - 8}V{h - 150}" stroke="{t["line"]}" stroke-width="2"/>')
    for i, (e, body) in enumerate(rows):
        s.add(f'<circle cx="{x0}" cy="{y - 7}" r="6" fill="{t["accent"] if i == 0 else t["panel"]}" stroke="{t["accent"]}" stroke-width="2"/>')
        s.text(x0 + 28, y, e["org"].upper(), "display", 600, 28, t["text"])
        s.text(W - 40, y, e["dates"].upper(), "mono", 400, 11, t["accent_text"], anchor="end", tracking=1.2)
        s.text(x0 + 28, y + 26, e["role"], "sans", 600, 14, t["muted"])
        for j, line in enumerate(body):
            s.text(x0 + 28, y + 54 + j * 22, line, "sans", 400, 14.5, t["muted"])
        y += 78 + len(body) * 22
    # Award and education
    ay = h - 116
    aw = W - 80
    s.add(f'<rect x="40" y="{ay}" width="{aw}" height="44" rx="12" fill="{t["panel"]}" stroke="{t["accent"]}" stroke-opacity="0.45"/>')
    s.text(60, ay + 27.5, "★", "sans", 600, 15, t["accent_text"])
    s.text(84, ay + 27.5, p["award"], "sans", 600, 14, t["text"])
    s.text(48, h - 36, p["education"].upper(), "mono", 400, 11, t["faint"], tracking=1.1)
    return s.render("Experience: " + "; ".join(f'{e["org"]}, {e["role"]}, {e["dates"]}' for e, _ in rows))


def stack(p, theme):
    t = THEMES[theme]
    x0, x_max, row_h = 220, W - 40, 46

    def layout(items):
        """Chip rows for one group, wrapping before the right edge."""
        rows, row, x = [], [], x0
        for item in items:
            w = width(item, "sans", 600, 13.5) + 30
            if row and x + w > x_max:
                rows.append(row)
                row, x = [], x0
            row.append((item, x, w))
            x += w + 10
        rows.append(row)
        return rows

    groups = [(g, layout(g["items"])) for g in p["stack"]]
    h = 40 + sum(len(rows) * row_h + 18 for _, rows in groups) + 22
    s = Svg(W, h, theme)
    frame(s, h, glow=(1.0, 1.0))
    y = 64
    for g, rows in groups:
        s.text(40, y + 4, g["group"].upper(), "mono", 400, 11, t["accent_text"], tracking=1.2)
        for r, row in enumerate(rows):
            for item, x, w in row:
                cy = y + r * row_h
                s.add(f'<rect x="{x:.1f}" y="{cy - 19}" width="{w:.1f}" height="34" rx="17" fill="{t["panel"]}" stroke="{t["line"]}"/>')
                s.text(x + 15, cy + 3, item, "sans", 600, 13.5, t["text"])
        y += len(rows) * row_h + 18
    return s.render("What I build with: " + "; ".join(f'{g["group"]}: {", ".join(g["items"])}' for g in p["stack"]))


def about(theme):
    t = THEMES[theme]
    k, st, cm, nm, tx = t["code_kw"], t["code_str"], t["code_cm"], t["code_num"], t["text"]
    code = [
        [("var ", k), ("achyuth", tx), (" = ", tx), ("new ", k), ("Engineer", tx), ("(", tx)],
        [("    ", tx), ('"Achyuth KP"', st), (",", tx), ("                    // Bengaluru, India", cm)],
        [("    ", tx), ('"Software Engineer"', st), (",", tx), ("             // Cognizant, ex-FIS Global", cm)],
        [("    ", tx), ("5", nm), (",", tx), ("                               // years running banking in production", cm)],
        [("    ", tx), ("List", tx), (".of(", tx), ('"Java"', st), (", ", tx), ('"Spring Boot"', st), (", ", tx), ('"Kafka"', st),
         (", ", tx), ('"Spring AI"', st), ("),", tx)],
        [("    ", tx), ('"Reliable systems. Useful AI."', st)],
        [(");", tx)],
        [("", tx)],
        [("achyuth", tx), (".", tx), ("openToOpportunities", tx), ("();", tx), ("     // true", cm)],
    ]
    h = 96 + len(code) * 25 + 30
    s = Svg(W, h, theme)
    frame(s, h, glow=(0.85, 0.2))
    # window chrome
    s.add(f'<path d="M0.5 46.5H{W - 0.5}" stroke="{t["line"]}"/>')
    for i, c in enumerate(("#FF5F57", "#FEBC2E", "#28C840")):
        s.add(f'<circle cx="{28 + i * 20}" cy="24" r="6" fill="{c}" opacity="0.9"/>')
    s.text(W / 2, 28.5, "Engineer.java", "mono", 400, 12, t["faint"], anchor="middle")
    size = 14.5
    for i, line in enumerate(code):
        x, y = 44, 92 + i * 25
        s.text(18, y, f"{i + 1:>2}", "mono", 400, 12, t["faint"], opacity=0.7)
        for chunk, color in line:
            if chunk:
                s.text(x, y, chunk, "mono", 400, size, color, style=' xml:space="preserve"')
                x += width(chunk, "mono", 400, size)
    return s.render('var achyuth = new Engineer("Achyuth KP", "Software Engineer", 5 years in production, '
                    'Java, Spring Boot, Kafka, Spring AI, "Reliable systems. Useful AI."); open to opportunities')


def cta(p, theme):
    t = THEMES[theme]
    c = p["cta"]
    h = 250
    s = Svg(W, h, theme)
    frame(s, h, glow=(0.5, 1.0))
    s.text(W / 2, 116, c["title"].upper(), "display", 700, 84, t["text"], anchor="middle")
    s.text(W / 2, 160, c["body"], "sans", 400, 16, t["muted"], anchor="middle")
    s.text(W / 2, 204, c["link"] + " →", "sans", 600, 16, t["accent_text"], anchor="middle")
    return s.render(f'{c["title"]} {c["body"]} {c["link"]}')


def pic(name, alt, width_attr="100%", height=None):
    size = f'height="{height}"' if height else f'width="{width_attr}"'
    return (f'<picture><source media="(prefers-color-scheme: light)" srcset="assets/readme/{name}-light.svg">'
            f'<img src="assets/readme/{name}.svg" {size} alt="{escape(alt, quote=True)}"/></picture>')


def main():
    global FONTS_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", default=str(ROOT.parent / "Portfolio" / "src" / "assets" / "fonts"))
    ap.add_argument("--portrait", default=str(ROOT.parent / "Portfolio" / "public" / "images" / "avatar-cutout.webp"))
    args = ap.parse_args()
    FONTS_DIR = Path(args.fonts)
    p = json.loads((ROOT / "scripts" / "profile.json").read_text())
    portrait = base64.b64encode(Path(args.portrait).read_bytes()).decode()
    OUT.mkdir(parents=True, exist_ok=True)

    def emit(name, make):
        for theme in THEMES:
            suffix = "" if theme == "dark" else "-light"
            (OUT / f"{name}{suffix}.svg").write_text(make(theme))

    emit("hero", lambda th: hero(p, th, portrait))
    for b in p["links"]:
        emit(f'btn-{b["file"]}', lambda th, b=b: button(b["label"], b.get("primary"), th))
    sections = [("01", "A 60-second tour", "tour"), ("02", "Featured work", "featured"), ("03", "More I've built", "more"),
                ("04", "Experience", "experience"), ("05", "What I build with", "stack"), ("06", "About me", "about"),
                ("07", "Latest writing", "writing"), ("08", "On GitHub", "github")]
    for num, label, key in sections:
        emit(f"h-{key}", lambda th, num=num, label=label: header(num, label, th))
    for i, item in enumerate(p["featured"], start=1):
        emit(f'featured-{item["slug"]}', lambda th, item=item, i=i: featured(item, i, th))
    for item in p["more"]:
        emit(f'card-{item["slug"]}', lambda th, item=item: card(item, th))
    emit("experience", lambda th: experience(p, th))
    emit("stack", lambda th: stack(p, th))
    emit("about", about)
    emit("cta", lambda th: cta(p, th))

    # README
    readme_path = ROOT / "README.md"
    current = readme_path.read_text() if readme_path.exists() else ""
    m = re.search(r"<!-- BLOG-POST-LIST:START -->.*?<!-- BLOG-POST-LIST:END -->", current, re.S)
    blog = m.group(0) if m else "<!-- BLOG-POST-LIST:START -->\n<!-- BLOG-POST-LIST:END -->"
    h = {key: pic(f"h-{key}", f"{num}. {label}") for num, label, key in sections}

    out = ["<!-- Generated by scripts/build_readme.py from scripts/profile.json. Edit those and run it again. -->", ""]
    out.append(f'<a href="{p["site"]}">{pic("hero", p["name"] + ", " + p["label"] + ". " + p["headline"] + " " + p["tagline"])}</a>')
    out += ["", '<p align="center">']
    for b in p["links"]:
        out.append(f'  <a href="{b["href"]}">{pic("btn-" + b["file"], b["label"], height=44)}</a>')
    out += ["</p>", "", h["tour"], "", p["video"]["url"], "", f'<sub>{p["video"]["credit"]}</sub>', "", h["featured"], ""]
    for item in p["featured"]:
        out += [f'<a href="{item["href"]}">{pic("featured-" + item["slug"], item["title"] + ": " + item["body"])}</a>', ""]
    out += [h["more"], "", "<p>"]
    for i, item in enumerate(p["more"]):
        out.append(f'  <a href="{item["href"]}">{pic("card-" + item["slug"], item["title"] + ": " + item["body"], "49%")}</a>')
    out += ["</p>", "", h["experience"], "", pic("experience", "Experience at Cognizant, FIS Global and Aniworks"), "",
            h["stack"], "", pic("stack", "What I build with"), "", h["about"], "", pic("about", "About me, as a Java record"), "",
            h["writing"], "", blog, "", h["github"], ""]
    gh = "https://raw.githubusercontent.com/achyuthkp27/achyuthkp27/main/profile-summary-card-output/github_dark"
    out += ['<p align="center">',
            f'  <img src="{gh}/0-profile-details.svg" width="49%" alt="Profile details" />',
            f'  <img src="{gh}/3-stats.svg" width="49%" alt="GitHub stats" />',
            "</p>", "",
            "<picture>",
            '  <source media="(prefers-color-scheme: dark)" srcset="https://github.com/achyuthkp27/achyuthkp27/blob/output/github-contribution-grid-snake-dark.svg">',
            '  <source media="(prefers-color-scheme: light)" srcset="https://github.com/achyuthkp27/achyuthkp27/blob/output/github-contribution-grid-snake.svg">',
            '  <img alt="Contribution grid" src="https://github.com/achyuthkp27/achyuthkp27/blob/output/github-contribution-grid-snake.svg">',
            "</picture>", "",
            f'<a href="{p["cta"]["href"]}">{pic("cta", p["cta"]["title"] + " " + p["cta"]["body"])}</a>', ""]
    readme_path.write_text("\n".join(out))
    sizes = sorted((f.stat().st_size, f.name) for f in OUT.glob("*.svg"))
    print(f"{len(sizes)} SVGs, {sum(s for s, _ in sizes) / 1024:.0f} KB in all; largest {sizes[-1][1]} {sizes[-1][0] / 1024:.0f} KB")


if __name__ == "__main__":
    main()
