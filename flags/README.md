`talentflow.flagd.json` is the reviewed flag source. See
[`docs/feature-flags/README.md`](../docs/feature-flags/README.md) for operation and
[ADR 010](../docs/adr/010-feature-flags.md) for naming, ownership and removal rules.

`flagd.schema.json` and `targeting.schema.json` vendor the upstream schemas from
<https://flagd.dev/schema/v0/flags.json> and
<https://flagd.dev/schema/v0/targeting.json>, fetched 2026-11-28. These are from
the [OpenFeature flagd project](https://github.com/open-feature/flagd), Apache-2.0.
They are kept local so the lifecycle checks do not require network access. Refresh
them together when upgrading flagd and run the invalid/valid lifecycle fixtures.
