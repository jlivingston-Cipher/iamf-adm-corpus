# Security Policy — iamf-adm-corpus

## Reporting a vulnerability

Please report suspected security vulnerabilities **privately**, not through a
public issue.

- Preferred: open a **private security advisory** through GitHub's "Report a
  vulnerability" button on this repository's **Security** tab (GitHub Private
  Vulnerability Reporting is enabled).
- The maintainer will acknowledge on a best-effort basis. This is free
  software maintained by a single maintainer (Apache-2.0, no SLA — see
  `SUPPORT.md` where present); please allow reasonable time before any public
  disclosure, and we will coordinate a fix and credit.

## Scope

This project is **spec- and reference-validated, not platform-certified**: it
is built and tested against the **AOM IAMF v1.1.0** specification, the AOM
reference tools (`iamf-tools`, `libiamf`), and FFmpeg / GPAC MP4Box — not
against any streaming platform's private ingest pipeline. Findings about those
*upstream* projects, when this project's own tooling surfaces them, are
disclosed to their maintainers through their own security processes and are
tracked separately; they are not vulnerabilities in this code.

In scope for a report here:

- Any path in the corpus generators / harness scripts that lets crafted
  configuration or input cause file writes, code execution, or reads outside
  the intended working tree.
- Integrity problems in the published evidence or manifest (e.g. a sample that
  does not match its recorded hash).

Out of scope:

- A validator **correctly reporting** that a nonconformant file is
  nonconformant.
- Behavior that requires an already-trusted, attacker-controlled toolchain
  binary on `PATH` (the reference encoders/decoders run only as explicit,
  configured subprocesses).

## Supported versions

Pre-1.0: only the latest released version on each line receives fixes. This
project's robustness posture is exercised by a bounded-fuzz acceptance pass
over the parser and container walk (no hangs, no uncaught exceptions on
malformed input).
