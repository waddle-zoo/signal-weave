# OpenAI provider validation — 2026-10-12

This note records a source-level audit of the OpenAI Decisions API and the
open-source Sign in with ChatGPT plan-usage flow. It is not a product-quality,
calibration, account-entitlement, or installed-binary certification.

## Official contract checked

- [Decisions API guide](https://developers.openai.com/api/docs/guides/decisions):
  public beta, dedicated `POST /v1/decisions`, and only `gpt-6-luna` currently
  supported. Requests use shared `input` plus typed `questions`; responses
  include named typed answers, choice distributions, confidence, and possible
  refusals.
- [Sign in with ChatGPT quickstart](https://developers.openai.com/siwc/quickstart)
  and [registration/sign-in](https://developers.openai.com/siwc/token-sharing-open-source/sign-in):
  the open-source plan-usage flow is separate from identity-only sign-in. It
  uses dynamic client registration for first consent, a saved issued client ID
  thereafter, loopback PKCE with state and nonce, and the explicit
  `resource.invoke` and `chatgpt.tokens.use.direct` scopes. A validated ID token
  alone does not establish plan-use entitlement.
- [Models and inference](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference):
  plan-use inference calls public `POST /v1/responses` with the OAuth bearer
  token, `store: false`, and `stream: true`; the stream is successful only after
  `response.completed`. Model availability is account-specific and should be
  read from `/v1/models` using that account's token.
- [Token reference](https://developers.openai.com/siwc/token-sharing-open-source/token-reference)
  and [errors and recovery](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery):
  successful refresh rotates the refresh token; documented unusable-token
  errors require OAuth again, while transient failures should not silently
  destroy credentials.

## Provider source changes

- Decisions model overrides other than `gpt-6-luna` fail early. Typed answer
  names and shapes, probability distributions, refusals, and omissions are
  checked rather than silently accepted or dropped.
- Responses streaming accepts only a completed response, treats failed,
  incomplete, malformed, and refused results as failures, and reports only
  bounded diagnostic metadata (HTTP/event kind, safe error code/parameter, and
  request ID), not provider body text.
- Empty resource ranking/classification returns an empty result without
  sending an invalid zero-question Decisions request.
- OAuth token exchange validates bearer type, granted scopes, required token
  fields, expiry, dynamic registration, state, and the ID-token validation path.
  Refresh rotation requires the replacement refresh token. Known unusable
  refresh errors clear token material while preserving registration/identity
  for reauthorization; transient errors preserve the saved credentials.
- Browser fallback output removes `id_token_hint`. No browser login was started
  and no Codex credential was read or reused.

## Evidence and limits

| Check | Result | What it establishes |
| --- | --- | --- |
| `tests/test_openai_integrations.py` | 12 passed | Mocked HTTP/provider behavior, local PKCE flow, mocked token exchange/refresh, and synthetic local ID-token signature/claim validation. It is not real OpenAI authentication. |
| Ruff on the three provider/test files | Passed | Static lint only. |
| Authorized credential inventory | Both authorized dotenv files and this process environment had no OpenAI-related variable names; `OPENAI_API_KEY`, `OPENAI_KEY`, and `OPENAI_API_KEY_FILE` were absent, with no key-file references | No candidate OpenAI API credential was found. Only names/presence and reference paths were inspected; no secret values or dotenv contents were recorded. |
| Decisions API-key live preflight | Not exercised | A real API key and endpoint entitlement were not available from the authorized key sources. |
| Responses API-key schema/transport preflight | Not exercised | No `/v1/responses` request was sent. Even a successful API-key request would not prove ChatGPT OAuth or plan entitlement. |
| SIWC startup registration without browser consent | Not attempted; HTTP status: not sent / not applicable | Official OpenAI documentation describes `dynamic_agent_client` registration as part of authorization: the user signs in and authorizes the agent before OpenAI returns an issued client ID. The documented `chatgpt.signIn()` helper opens the system browser and runs that flow. No standalone no-consent registration request/helper is documented, so no authorization request was issued. This is distinct from browser consent and does not establish account entitlement. |
| Sign in with ChatGPT browser consent / real refresh | Not exercised | No user OAuth login or consent was initiated; account entitlement and refresh against OpenAI remain unproven. |
| Installed-binary provider trial | Not run | This audit launched no binary. Candidate provenance is separate and does not prove provider authentication, entitlement, or human-workflow success. |

Latest candidate provenance reported separately by the parent and locally
binary-hash checked: `dist/signalweave`, binary SHA-256
`4dbc21d4bbf07a6979bc82f200aab2cc541c60c3f9f31e7b594a9eb87c2b1521`, source
SHA-256 prefix `22498…` (abbreviated in the parent’s update), embedded version
`0.2.0rc2`. This is candidate identity only; this provider audit did not launch
the binary. The previous `2e0a…` binary / `012935…` source candidate and the
older `ed913…` / `0745…` certification are historical and superseded. No
provider authentication or entitlement proof attaches to those candidate
identities or to the current binary.

The synthetic tests contain no company data and no benchmark gold labels are
sent to a model. There are no live model-quality or calibration conclusions in
this evidence.

## Integration items for the runtime/CLI owner

1. Before offering a ChatGPT-plan model choice, query the account-specific
   `/v1/models` catalog using its OAuth access token and use an available model
   slug. The current transport's `gpt-6.1-sol` default matches the official
   inference example but is not proof of availability for every account.
2. Current logout removes the local token record; the CLI describes remote
   revocation through ChatGPT settings. Review the current SIWC recommendation
   to attempt the discovered revocation endpoint and clearly report when
   revocation cannot be confirmed.
3. Provider decision transport cannot by itself provide the human's useful
   recurring report, schedule, recipient choice, or delivered alert. Those
   end-to-end outcomes need separate fresh-install and agent-workflow evidence.

The current source candidate has embedded version `0.2.0rc2`; release tag
`v0.2.0rc2` remains unpublished. The latest-candidate provenance above is
separate from this provider audit and is not a provider-authentication or
user-workflow result. No browser consent, real OAuth refresh, live API request,
or account-specific model-catalog request was performed.
