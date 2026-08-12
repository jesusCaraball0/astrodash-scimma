# Serving a Gated Model

A model definition can declare that running it requires a shared access code
(`requires_credential=True`). Such a model is **gated**: it does not appear on
the model-selection page or in any choice control, the REST API refuses it
outright, and the only way to reach it is a *model-scoped entry link* that you
mint and hand to whoever distributes it.

This exists for one situation: a classifier that must be usable before it is
public — typically by an anonymous peer reviewer, who cannot be asked to create
an account. It is deliberately interim, and the identity-and-access work will
retire it.

## What you must configure

A deployment whose registry contains a gated model **refuses to start** unless
the first three values below are set. The check runs in the app-ready hook, so a
misconfigured deployment fails in the init container with the missing names in
its logs rather than serving the model without a prompt.

| Value | Where | Purpose |
|---|---|---|
| `ASTRODASH_MODEL_GATE_CREDENTIAL` | sealed secret | The shared access code a visitor types. |
| `ASTRODASH_MODEL_GATE_LINK_TTL_SECONDS` | configmap | How long a newly minted link is valid, in seconds. |
| `SECRET_KEY` | sealed secret | Signs entry links. Must not be left at the committed `django-insecure-…` default — a key published in the repository would make links forgeable. |
| `ASTRODASH_MODEL_GATE_LINK_BASE_URL` | configmap | The public base URL links are minted against, e.g. `https://astrodash-dev.scimma.org`. Needed only when minting. |

These live in the chart in `../astrodash-k8s-gitops`. Sealed secrets are
per-cluster, so DEV and PROD each need their own re-sealed values.

An unset, empty, or whitespace-only value counts as unconfigured, as does a
`SECRET_KEY` still carrying the committed prefix.

## Minting a link

Minting is operator-only: no route mints a link, so a link can only come from a
shell on a running deployment.

```bash
# In the app container
python manage.py mint_model_link <model-id>

# Or with a one-off window, in seconds
python manage.py mint_model_link <model-id> --ttl-seconds 1209600
```

The command prints one URL, and nothing else. It refuses a model that is unknown
or not gated, and it never prints the access code.

The deadline is stamped into the link when it is minted. Changing
`ASTRODASH_MODEL_GATE_LINK_TTL_SECONDS` afterwards does not move the deadline of
a link that already exists — in either direction. Keep the window no longer than
the access you actually intend to grant, because nothing shortens an outstanding
link once it is minted.

## What to hand over

Two things, and it is worth sending them separately:

1. **The link** printed by the command.
2. **The access code** — the value of `ASTRODASH_MODEL_GATE_CREDENTIAL`.

The recipient opens the link, is prompted for the code, and lands in a
classification session locked to that one model. They can classify spectra and
use whichever result tabs the model declares. They cannot reach the batch flow,
the model picker, or any other model, and there is an explicit **End session**
control on the page.

A mistyped code is retryable while the link is still valid. An expired or
tampered link is refused with a page that names no model and reveals nothing
about which models exist.

## The session ends when the link does

The session carries the link's own deadline, so continuing to work does not
extend it — activity is not a heartbeat. When the deadline passes, the next
request is refused, and everything that session produced (results, plots, the
twins embedding) is discarded with it.

The visitor can also end the session themselves, which discards the same things
immediately.

## Rotating the access code

One code covers every simultaneously gated model. Make it long and random — it
is checked only for being set, so nothing else stops a short one from being
guessed, and there is no attempt limit by design.

Change the sealed secret and restart the pods. Rotation stops an outstanding
link from being redeemed with the old code; it does **not** end a session that
already redeemed one. Those sessions end at the deadline their link carried, or
when the visitor ends them. There is no per-visitor code and no way to revoke a
single link — if you need that, rotate, re-mint, and wait out the window.

## Publishing the model

Publishing is a definition change, not an operator action:

1. Clear `requires_credential` and set `listed=True` on the model's definition.
2. Deploy.

The card appears on the selection page and the model behaves like any other. A
visitor who was inside a scoped session finds it dissolved into an ordinary
selection of the same model on their next request, and an outstanding entry link
now leads into the normal public flow rather than refusing — so nobody is locked
out of a model that has just become public.

Once no gated model remains in the roster, the gate configuration is no longer
required for startup, though leaving the values in place is harmless.

## Two operational constraints

The request profiler (Django Silk) is installed and its sample rate is
environment-tunable. It can capture request bodies, which in this flow means the
access code and uploaded spectra. Do not raise `SILKY_INTERCEPT_PERCENT` in an
environment serving a gated model.

The link carries its token in the URL path, so it lands in ingress and proxy
access logs, in browser history, and in whatever the recipient forwards it
through. Treat a link as one half of a credential pair: it is useless without
the access code, which is why the two are sent separately.
