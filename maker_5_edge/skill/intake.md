---
name: intake
description: Describe what was scanned at the shelf on the Maker-5 phone (the intake, ADR-0022) so a person can check it into the stock. Look at each item's photos and note, reuse an article the stock has, and suggest what the item is (a device, a box of parts, loose parts), its category, maker, model, serial and count. Also reads a supplier's document (an order, shipping, invoice or service e-mail or PDF the person attached) into expected parts, links to parts the stock has, and their documents. Use when the person asks to describe, sort or prepare the intake, the new scans, or what they scanned tonight, or attaches a shop's e-mail or invoice.
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

## 2b. Was it ordered

`orders_open()` lists what was ordered and is expected (ADR-0023): lines
the person imported from an order e-mail, with their title, the shop's
article number, the quantity and the article they are (or a new one they
describe). Before anything else, look for the item's line: the title on the
bag or box, the photo, the count. When one fits, set `orderLineId`; the line
brings its article, what it is and the quantity, so give only what differs
(a different count in the bag, a box name). One line can arrive in several
items. Never set a line that does not fit just because it is the only one.

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

## 5. Supplier documents (ADR-0024)

The person attaches a shop's e-mail or PDF with 📎: an order confirmation, a
shipping notice, an invoice, a delivery note or a service report. `inbox()`
shows it as kind `email` (or `pdf`); `supplier_read(file)` reads it.

1. **Each line, is it ours already?** `match` is sure (the shop's number, the
   maker's part number, or the stock's name in the title). `candidates` only
   look alike: open `stock_article(id)` and compare maker, model and size
   before you call one the same. Two sizes or two colours are two articles.
   When unsure, say so and leave it to the person; never merge on a guess.
2. **What to do with it:**
   - `expect`: bought and coming (an order, a shipping notice, an invoice
     of something not here yet). With `articleId` when it is a known
     article, so no second article is made; otherwise the new article's
     `article` draft: fix its `name`, `category`, `manufacturer`, and set
     `family: "dhc"` for a smart-home device (devolo, Homematic, Hue,
     Zigbee, Shelly, a router or a powerline adapter), else leave it out.
   - `link`: the part is ours already (a service report, an invoice for
     something checked in): `articleId` of the stock's article. Its
     documents go onto it, and the shop's number is remembered.
   - `skip`: shipping costs, services, a deposit, what is not a part.
   - `known` lines were read before: link them, never expect them twice.
3. **A shop without a reader** gives no lines, only `text`: read it and write
   the lines yourself (`title`, `sku` the shop's article number, `ordered`,
   `unitPrice`, `currency`), and `supplier` (the shop's domain, as
   reichelt.de) and `ref` (the document's number) when the reader left them
   empty.
4. **Propose** `supplier_apply(preview)` with the whole preview (keep `file`,
   so its attachments go onto the parts) and your actions. In the chat that
   is a proposal the person confirms. Then tell them in a short list: what is
   expected, what is linked to what, which documents go where, and what you
   were unsure of.

The documents carry the person's address and customer number: they stay in
the organisation's private storage. Never quote that address or number back
in the chat.
