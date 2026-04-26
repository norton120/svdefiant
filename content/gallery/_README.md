# Adding a gallery album

This file is ignored by Hugo (leading `_` on the filename). It documents how to add an album.

## Folder layout

```
content/gallery/
  my-album-slug/
    index.md            <- album metadata + photo list
    photo1.jpg          <- source images, any name; reference them by filename in index.md
    photo2.jpg
    ...
```

The folder name becomes the URL slug: `content/gallery/sock-burning/` → `/gallery/sock-burning/`.

## index.md format

```yaml
---
title: "Sock Burning 2026"
date: 2026-03-21
draft: false
cover: photo1.jpg          # which file to use as the album thumbnail on the gallery list
summary: "Annapolis, March equinox"   # optional, shows under the title on the gallery list
photos:
  - file: photo1.jpg
    caption: "First sock goes in the fire"
  - file: photo2.jpg
    caption: "Mid-burn ceremony"
  - file: photo3.jpg
    caption: ""             # captions are optional
---

Optional album description in markdown — renders above the photo grid on the album page.
```

## Notes

- Source images can be any size. Hugo generates a 700px square thumbnail and a 2400px full version (both webp, q85/q90) automatically — no need to pre-resize.
- Captions render under each thumbnail in the grid AND in the lightbox when an image is opened.
- Lightbox is PhotoSwipe v5, loaded from a CDN (~25 KB JS). Click any photo to open.
- Drafts (`draft: true`) are hidden from the gallery list.
