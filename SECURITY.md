<!--
Canonical security, disclosure and acceptable-use policy for isogeny-labs
repositories (action plan F4, docs/strategy/2026-11-21-action-plan.md).
Copy it into a repository as SECURITY.md, then fill the two marked sections.
Owner actions before the first copy merges:
  1. enable GitHub private vulnerability reporting on each public repository
     (Settings > Code security > Private vulnerability reporting);
  2. create the security@isogenylabs.io mailbox, or replace the address below.
This is a policy draft, not legal advice. Counsel reviews it with F6 and F9.
-->

# Security policy

## Reporting a vulnerability

Please report security problems privately. Do not open a public issue.

- **GitHub:** use "Report a vulnerability" on this repository's Security tab.
- **Email:** security@isogenylabs.io

Tell us what you found, how to reproduce it, and what you think the impact
is. We confirm receipt within 3 business days and tell you what we will do
within 10 business days. Our default is coordinated disclosure after
90 days, or sooner once a fix is released. We credit reporters who want to be
credited.

We will not pursue legal action against good-faith research that stays
within this policy: it avoids privacy violations, data destruction and
service disruption, uses only accounts and data you own or are authorised
to use, and gives us reasonable time to respond before anything is made
public.

## What this repository is, and what it is not

This repository is the code behind [ecc-challenges.com](https://ecc-challenges.com),
a public volunteer-compute gateway for Pollard rho on the 24 published
[Certicom ECC challenges](https://www.certicom.com/content/dam/certicom/images/pdfs/challenge-2009.pdf):
the web and API service (`src/ecc_challenges/`), its AWS stacks (`infra/`),
the point verifier and collision resolver (`verifier/`, `Dockerfile.audit`)
and the CPU, CUDA and Metal workers (`worker/`). Isogeny Labs runs it as a
live service. The only targets are the challenge points Certicom published
for anyone to attack; the code solves no other discrete logarithms, recovers
no one's keys and probes no networks. Dual-use risk is low, so most of this
policy is about the service itself.

### The ecc-challenges.com service

**Worker API keys.** A contributor signs in with GitHub and creates an API key
on the dashboard. The key is shown once; keep it in
`~/.config/ecc-challenges/api-key` with mode `0600`, or let the installer do
that. The server stores only an HMAC-SHA256 digest of each key and compares
digests in constant time (`src/ecc_challenges/security.py`). A key is not an
AWS credential: it grants no bucket listing, archive reads or database
access, and each signed upload capability permits one bounded object write.
If a key leaks, revoke it on the dashboard; revoking it stops uploads for its
runs.

**Verification.** Every v2 record is checked for its distinguished-point
predicate, the curve equation and the relation `R = aG + bQ` before it is
indexed. A collision is replayed and the resulting scalar is checked against
the challenge points (`dG = Q`) before a result is marked verified. Upload
counts are estimates of work, not verified work. The README section "What an
accepted upload means" and `docs/admission-and-capacity.md` describe the
checks and their limits.

**What to report privately.** Anything that lets someone forge accepted work
or a solution, read another contributor's data or keys, get around key
revocation, quotas or replay sampling, write outside a granted upload
capability, or run code on the gateway. Use the channels above.

**Reporting abuse.** Report stolen or leaked keys, accounts created in bulk
to evade quotas, a worker image or installer that is not ours but claims to
be, or a contributor whose uploads look forged, by email to the address
above. Operators can suspend runs, revoke keys and quarantine points.

**Testing the service.** Test against the [local stack](docs/local-stack.md),
not the live gateway. Do not load-test ecc-challenges.com, create accounts in
bulk, or submit fabricated points to it; a failed replay suspends the run and
revokes its key. Only run the worker images whose digests the dashboard or
[`/v1/campaigns`](https://ecc-challenges.com/v1/campaigns) publishes.

## Acceptable use

Some code here implements published cryptanalytic techniques: attacks on
weak parameters, key recovery from flawed signatures or leakage, and network
probes that read how a system negotiates cryptography. We publish it for
research, education, and defensive assessment.

- Use it only on systems, keys, signatures and data that you own, or that
  you have written authorisation to test.
- Do not use it to obtain anyone else's keys, funds, messages or data, or to
  get into systems you are not authorised to access.
- Network probes complete ordinary handshakes and read what the server
  offers. Do not point them at networks you do not operate or have
  permission to assess, and respect the target's rate limits.
- If you recover key material that is not yours, stop. Do not use it or
  share it; report it privately as above.

## How Isogeny Labs runs client engagements

When we assess a client's systems, these rules hold whatever the contract
says on top of them:

1. **Written authorisation first.** No active test starts before a signed
   authorisation that names the systems, the adversary model, what counts as
   a finding, the testing window and the client's emergency contact.
2. **Public data by default.** We analyse public material (signatures, public
   keys, certificates, handshakes) unless the client agrees in writing to
   provide more.
3. **Recovered key material.** If an analysis recovers a private key or
   other secret, we tell the client's named contact at once through the
   agreed secure channel. We never store it in plaintext, never put it in a
   repository, ticket, report or log, and delete it at the end of the
   engagement, confirming the deletion in writing.
4. **Evidence, not exploitation.** We show a finding with the smallest proof
   that establishes it: a verified result, a test, a signed evidence record.
   We do not use it beyond that.
5. **Third parties.** A weakness found in someone else's product is reported
   to that vendor under coordinated disclosure (90 days by default), with
   the client's agreement where the client's data was involved.

## Ethics

We build attacks so that their cost is measured rather than guessed, and so
that weak deployments are found by their owners first. We do not sell attack
capability, target individuals, or take work whose purpose is to defeat
security that people rely on without their owner's consent.

## Components with dual-use capability

| Path | What it does | Intended use | Safeguards |
|:--|:--|:--|:--|
| `worker/` (generic v2 engine: CPU, CUDA, Metal; legacy ECC2K-130 client) | Pollard rho walks that upload distinguished points | Volunteer compute on the public Certicom challenges | The worker registers a run for a named gateway campaign (`ECC_CAMPAIGN`); every campaign is a published Certicom challenge point |
| `verifier/`, the audit service and the collision resolver | Checks every uploaded point; on a collision, computes the discrete logarithm and checks `dG = Q` | Accepting honest work and confirming a solution | Applies only to the published challenge points, whose solutions are meant to be public; a result is marked verified only after replay and an independent scalar check |
| `vendor/cryptanalysis/`, `vendor/crypto/` | Pinned ECC2K-130 arithmetic and host-solver sources from the lab's own repositories | The audit image's replay and solver binaries | Pinned commits with `SHA256SUMS`; built only for the ECC2K-130 challenge curve |
