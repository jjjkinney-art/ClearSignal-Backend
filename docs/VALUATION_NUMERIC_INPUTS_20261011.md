# Selective valuation-number validation

Follow-up to the restored ratio-provider path: booleans could appear as 1.0x,
NaN as a reported percentage, and a malformed field could discard an otherwise
valid P/E observation. This increment validates each ratio/key-metric field
before formatting rather than treating the entire response as one valid number.

Only finite JSON numbers qualify. Malformed fields are omitted independently;
conflicting aliases cannot silently choose a multiple. Equal aliases deduplicate.
Zero/nonpositive metric observations retain their numeric meaning where the
metric is not a price multiple. The existing omission of zero price multiples
is preserved. Percentage conversion uses decimal arithmetic so multiplying a
finite provider value by 100 cannot itself create Infinity.

Offline checks cover provider output and the valuation prompt, invalid fields
alongside valid observations, alias conflicts, signed/zero observations and
independent percentage arithmetic. Network access is prohibited in new tests.

This does not establish publication dates, freshness, currency verification,
primary-source provenance or expected returns. It depends on the valuation
period repair; its downstream unknown-freshness repair must also be retained.
No valuation scenario or investment threshold is selected.
