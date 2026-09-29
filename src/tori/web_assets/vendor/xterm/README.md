# Locally bundled terminal frontend

These unmodified distribution files were extracted from the official npm
packages. Tori serves them from its own application port and needs no npm
install or CDN at runtime.

| Package | Exact version | npm tarball SHA-256 | Files |
| --- | --- | --- | --- |
| `@xterm/xterm` | `6.0.0` | `908e66e04af6c8dc6b00dd3b54de088e2e81e5ed866284fd6c2fb3c2d1c7a3f6` | `xterm.js`, `xterm.css`, `LICENSE-xterm` |
| `@xterm/addon-fit` | `0.11.0` | `26003b4517a132b64e4ff228fd88a5fda3fff5e606c76093f6dcff772e9ecec0` | `addon-fit.js`, `LICENSE-addon-fit` |

Both packages are MIT licensed. No Open Terminal code is included.

Gate P4 independently fetched the exact versions from the authoritative npm
registry, verified each tarball's published SHA-512 `dist.integrity` and the
SHA-256 digests above, then compared **every bundled JS, CSS, and LICENSE file
byte-for-byte** with its corresponding tarball member. All five included
asset/license files matched. Npm source maps and other package files are not
bundled; no included bytes were transformed.
