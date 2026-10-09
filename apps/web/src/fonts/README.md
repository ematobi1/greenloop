# Bundled fonts

## Orbitron

Used for headings, numbers and labels in the HUD (ADR 0014), loaded with `next/font/local`. No font is fetched from a remote server.

- Source: npm package `@fontsource/orbitron@5.3.0` (files `files/orbitron-latin-500-normal.woff2` and `files/orbitron-latin-700-normal.woff2`), copied as is. The package is not a dependency.
- Licence: SIL Open Font License 1.1, in [`orbitron/OFL.txt`](orbitron/OFL.txt).

| File | Bytes | SHA256 |
|---|---|---|
| `orbitron/orbitron-latin-500-normal.woff2` | 6596 | `c13360768270c65d6c97701b100a88993885671dfdfd2a400aa58ea0195381ea` |
| `orbitron/orbitron-latin-700-normal.woff2` | 6528 | `ee6acc5ad5349018f9ca71fab8118144160e110838931874150a1ac3f97db38d` |

`tests/fonts.test.mjs` checks these hashes against the files, so a font can't change without this table changing too.
