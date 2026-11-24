---
name: intake
description: Describe what was scanned at the shelf on the Maker-5 phone (the intake, ADR-0022) so a person can check it into the stock. Look at each item's photos and note, reuse an article the stock has, and suggest what the item is (a device, a box of parts, loose parts), its category, maker, model, serial and count. Use when the person asks to describe, sort or prepare the intake, the new scans, or what they scanned tonight.
---

# Describing the intake (ADR-0022 in maker-5-shared)

At the shelf a person scanned a place (a shelf or a box), then label after
label of what went into it, with a photo, a note or a count when they had
time. You describe the items; **the person checks them in on the page**.
You cannot check in or drop an item, and you do not need to.

## 1. The items

1. `intake_list()`: the open items. `known` means the label points at
   something already: say what it is and leave the item (the person moves it
   in with one click).
2. `intake_item(id)`: the item and its photos. Look at them.

## 2. What is it

Only what a photo, the note or the label shows: a maker's name or logo, a
model or part number, a serial, a rating plate (volts, watts), the text on a
bag. Never invent a serial, a maker or a model. Leave a field out rather than
guess, and say how sure you are of each field in `sure`.

- **A device** (`what: device`): one thing with its own label, such as a
  board, a PC, a power supply, a phone. Tracked unit by unit; `serial` when
  the plate shows one.
- **A box of parts** (`what: box`): a bag, a box or a drawer with many of one
  part, such as resistors, screws or LEDs. The label becomes the box's;
  `boxName` like "Resistors 10 kΩ", `boxKind` bag/box/folder/drawer, `qty`.
- **Loose parts** (`what: bulk`): counted straight into the place.

The label's **family** says which inventory it belongs to: `m5` for maker
parts, `dhc` for devices a smart home can use (PCs, power supplies, routers,
hubs). Keep it; a `dhc` item is almost always a device.

## 3. Reuse before you make

`stock(words)` with the maker and model first, then with the name. When an
article fits (same maker and model, or the same generic part), suggest its
`articleId` and nothing else about the article. Only when none fits, describe
a new `article`: `name` (maker + model + what it is, short: "Raspberry Pi 3
Model B", "Mean Well LRS-50-12 power supply"), `category` from `catalogue()`
(two levels, "controllers/sbc", "power/supplies", "components/passives"),
`manufacturer`, `mpn`, `unit` for bulk (pcs, m, g, ml, set), a short `note`,
a `datasheet` https link only when you know it for certain.

## 4. Suggest

`intake_describe(id, suggestion)` for each item. Then tell the person, in a
short list, what you suggested and what you were unsure of, so they look
there first on the Intake tab. Items you could not tell apart from the
photos: say so and leave them as they are.
