# Contributing to Tori

Tori is an early public preview. Focus contributions on reproducible fixes,
clear tests, and the accepted local-first, human-controlled product boundaries.
Open a focused public issue or propose a pull request against the public source
repository. Describe the behavior, why it matters, and what
checks you ran; avoid speculative expansion of Tori's authority.

Use synthetic fixtures and isolated temporary stores. **Never attach** real
conversations, runtime databases, credentials, backup payloads, screenshots
showing personal data, or sensitive logs. For a vulnerability, follow
[SECURITY.md](SECURITY.md) rather than disclosing details in a public issue.

The source is under the root [MIT license](LICENSE); contributors must have the
right to submit their work under that license and preserve third-party
attribution. Do not add a production dependency, vendored asset, or model
weight without an explicit provenance and license review. The maintainer may
decline or defer work that does not fit the current scope. Tests run with
isolated state; a configured Git development checkout can use
`./scripts/verify-milestone` after installing the declared prerequisites.
