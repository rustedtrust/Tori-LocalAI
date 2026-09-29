# Third-party material in this source snapshot

Tori-owned material is licensed under the root [MIT LICENSE](LICENSE). The
following third-party material is **included** in this source snapshot and its
own attribution and license remain in force. Keep these files with any source
archive or redistributed copy containing the corresponding material.

| Component | Upstream and version | Where included | License and retained attribution | Modification status |
| --- | --- | --- | --- | --- |
| xterm.js | [@xterm/xterm](https://github.com/xtermjs/xterm.js), 6.0.0 | `src/tori/web_assets/vendor/xterm/xterm.js`, `xterm.css` | MIT; full text and upstream copyright in [`LICENSE-xterm`](src/tori/web_assets/vendor/xterm/LICENSE-xterm). The CSS also retains its original header crediting Christopher Jeffrey and Fabrice Bellard. | Locally bundled upstream distribution files; no Tori modifications claimed. |
| xterm addon-fit | [@xterm/addon-fit](https://github.com/xtermjs/xterm.js), 0.11.0 | `src/tori/web_assets/vendor/xterm/addon-fit.js` | MIT; full text and upstream copyright in [`LICENSE-addon-fit`](src/tori/web_assets/vendor/xterm/LICENSE-addon-fit). | Locally bundled upstream distribution file; no Tori modifications claimed. |
| Voice interface provenance | [RealtimeSTT](https://github.com/KoljaB/RealtimeSTT), inspected at 1.1.2 | Tori-owned `deploy/voice/recognizer.py` and `runtime.py` integrate public RealtimeSTT APIs | Upstream attribution and full MIT notice in [`deploy/voice/NOTICE.md`](deploy/voice/NOTICE.md). | Tori-owned bridge influenced by upstream recorder/executor behavior; no RealtimeSTT implementation or weights are bundled. |

The vendored frontend files' version and npm tarball digests are recorded in
[`vendor/xterm/README.md`](src/tori/web_assets/vendor/xterm/README.md). Keep
their original embedded copyright comments. This index does not replace their
license files or the Voice notice.

The Python packages listed in `requirements.txt` and
`deploy/voice/requirements.txt` are **not in this snapshot**: installation
fetches them separately into the user's environment. Models, voice weights,
the optional GPT-Researcher implementation, and local service deployments are
also not distributed here. Their respective licenses matter to anyone who
obtains or redistributes them separately; this document does not purport to
license those external components.
