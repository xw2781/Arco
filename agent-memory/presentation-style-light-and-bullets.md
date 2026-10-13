---
name: presentation-style-light-and-bullets
description: "Presentation pages (decks, animated explainers) use a light theme only and minimal text in bullet points"
metadata:
  node_type: memory
  type: feedback
  originSessionId: 6ae16138-903c-4804-9472-a4b8babe32ce
  modified: 2026-10-13T17:51:49.049Z
---

For presentation-style HTML pages (decks, animated explainers like docs/presentations/resq-vs-arco-data-flow.html), always use a single light color theme (no dark-mode blocks), and keep on-page text short, using bullet points wherever possible instead of sentences or paragraphs.

**Why:** user rule given 2026-10-13 after the ResQ vs Arco animation page; these are shown to general audiences on a projector.

**How to apply:** set every color explicitly in one light palette with `color-scheme: light`; skip the prefers-color-scheme and [data-theme] blocks. Lane captions, takeaways, and table cells become 2-4 word-lean bullets; drop explanatory prose and fine print.
