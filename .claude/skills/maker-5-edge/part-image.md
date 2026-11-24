---
name: part-image
description: Give a block on the Maker-5 hardware canvas its picture. Look in the Fritzing and Wokwi libraries first; when neither has the part, draw it as SVG from its datasheet or the person's files, with every one of the block's pins marked where it really is. Use when the person asks for a picture, image or drawing of a part, when a block shows no picture, or when the Image window's "By the agent" sent the request.
---

# A block's picture (ADR-0021 in maker-5-shared)

A picture on the canvas is part of the design: it is pushed to the
repository (`hardware/images/<block>.svg`) and credited in `NOTICE`. It has to
be right more than it has to be pretty.

## 1. Look in the libraries first

1. `canvas(product)`: the block, its name and its pins `[{n, name, role}]`.
2. `fritzing_search(words)`: the Fritzing parts library. The block's name, or
   its maker and model ("Raspberry Pi B rev2", "PC817").
3. `wokwi_search(words)`: breadboard pictures of common boards and parts
   (Arduino, ESP32, LEDs, buttons, sensors, displays, servos).
4. A fit: `fritzing_part(path)` or `wokwi_part(name)` to compare its pins with
   the block's, then `image_use(product, block, "fritzing" | "wokwi", ref)`.
   A library part brings its own pins; the board's ports stay. Say what
   changes in the pins.
5. No fit: say so, in a line, and go on to draw. A part that only resembles
   the block is not a fit.

The person can also choose "drawn from its pins" (`image_use(product, block,
"drawn")`): a plain drawing that is always right. Offer it when there is
nothing to draw from.

## 2. Draw from evidence

Only what a source shows: the datasheet or photo the person gave
(`files(product)`, `read_file(...)`), the article's description, or what the
person said. The outline and size, where the headers and connectors are, the
order of the pins along them. Never invent a connector, a label or a
dimension. If you do not know where a pin is, ask, or put it in a plain row
and say so.

## 3. The rules of the drawing

`image_draw` refuses a drawing that breaks one, and says which:

- One `<svg>` with a `viewBox` (about 200 to 400 units across), at most 40 000
  characters. A top view, as on a breadboard.
- Only these elements: `svg g rect circle ellipse line polyline polygon path
  text tspan title desc defs linearGradient radialGradient stop`.
- Only presentation attributes (`fill stroke stroke-width transform x y width
  height r d points font-size text-anchor` and the like). No `style`, no
  `href`, no event attributes, no `<image>`, `<use>`, `<foreignObject>`,
  `<script>`, no DOCTYPE or entities. `url(#id)` only for a gradient defined
  in the same drawing.
- Colours as `#rrggbb` or names. Keep a solid body colour, so the picture
  reads on a light and a dark canvas.
- **Every pin of the block is marked exactly once**: `data-pin="<n>"` on the
  shape at its place (a small circle or rect on the header, the connector's
  outline). No `data-pin` for anything that is not a block pin. A port (USB,
  HDMI, audio, Ethernet, power socket) is a pin like any other.
- Labels are text, small (font-size 6 to 10), on the part.

## 4. Propose it

`image_draw(product, block, svg)` makes a proposal; the person sees the
drawing before it is kept. If it is refused, read the reason, fix that and
propose again; do not change what was not wrong. After it is confirmed, say
what the drawing shows and what it is based on ("from the datasheet's top
view, page 2").
