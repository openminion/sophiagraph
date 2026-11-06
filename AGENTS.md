# Agent instructions

Before making changes, read [CONTRIBUTING](CONTRIBUTING.md) and
[CODE_QUALITY](CODE_QUALITY.md). Follow their existing-owner, comment-review and
validation rules in source, tests and scripts. These requirements apply equally
to agents, maintainers and external contributors.

Apply the [minimum-code and review-evidence rules](CODE_QUALITY.md#minimum-usable-code)
to the full final diff and every new delta. Record the exact head and concrete
caller/failure evidence. For merged work, verify surviving code on the current
development branch and reuse existing findings. Claim sweep coverage only from
a fresh inventory and explicit per-file dispositions; require the documented
local and hosted gates before merging.
