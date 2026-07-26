# Contract 3: Deterministic Backtest Comparison V1

**Status:** normative implementation specification  
**Contract version:** `comparison.contract.v1`  
**Recommendation authority:** proposal only  
**Mutation authority:** none  
**Deployment modes:** production real-only, hermetic sample-only, test-process synthetic-only

## 1. Purpose and authority

Contract 3 defines a synchronous, deterministic, read-only comparison service over complete immutable backtest evidence. It ranks candidate groups only when every candidate has complete, authorized, origin-verified, controlled, policy-compliant evidence for every required axis.

The service may return only:

- `proposal_only`: one candidate group is proposed for a new, independent human Gate 2 review; or
- `abstain`: no proposal is made, with closed reason codes.

The service does not create or mutate a Task, Attempt, Run, transport Command, candidate, approval, Gate receipt, promotion receipt, release record, Git reference, order, broker state, public-write grant, or safety flag. Comparison events and caches are disposable projections, not business journals.

Authority ownership is fixed:

- The Platform backtest producer owns backtest execution and production of complete comparison bundles.
- The Platform comparison service owns immutable bundle verification, origin classification, controlled-design validation, axis evaluation, ranking, response projection, and the result cache.
- HQA may display an authorized comparison response but does not reinterpret it as workflow completion, evidence acceptance, Gate approval, or promotion authority.
- Existing Platform Candidate Gate 2 remains the only candidate approve/reject authority. Existing Gate 3 remains the only promotion-review authority.

Current HQA summary receipts and Platform experiment summaries contain unversioned binary floating-point summaries and best-run-by-Sharpe selection. They are legacy locators only. They are never rankable Contract 3 evidence and fail with `producer_evidence_incomplete`.

## 2. Normative language and primitive types

`MUST`, `MUST NOT`, `REQUIRED`, `SHALL`, and `SHALL NOT` are normative.

All objects in this specification are strict objects: every listed required field is present, every optional field is explicitly identified, and unknown fields are rejected. JSON duplicate keys are rejected before model validation.

Primitive aliases:

| Alias | Exact rule |
|---|---|
| `sha256` | Lowercase ASCII hexadecimal matching `^[0-9a-f]{64}$`. |
| `git_commit` | Lowercase ASCII hexadecimal matching `^[0-9a-f]{40}$`. |
| `identifier` | ASCII matching `^[a-z][a-z0-9._-]{0,127}$`. |
| `logical_name` | ASCII matching `^[a-z0-9][a-z0-9._/-]{0,191}$`; no leading `/`, empty component, `.` component, `..` component, backslash, percent-encoded slash, NUL, or trailing `/`. |
| `display_string` | NFC-normalized printable UTF-8, 1..512 encoded bytes; no control character except ordinary space. |
| `reason_string` | NFC-normalized printable UTF-8, 1..2,000 encoded bytes. |
| `utc_timestamp` | UTC RFC 3339 exactly `YYYY-MM-DDTHH:MM:SS.ffffffZ`; six fractional digits; leap seconds rejected. |
| `date` | Gregorian `YYYY-MM-DD`. |
| `decimal` | Canonical decimal string matching `^-?(0|[1-9][0-9]*)(\.[0-9]+)?$`; no exponent, leading plus, leading zero, trailing decimal point, NaN, Infinity, or negative zero. |
| `nonnegative_decimal` | `decimal` whose mathematical value is at least zero. |
| `positive_int` | JSON integer, not boolean, in `1..2^53-1`. |
| `nonnegative_int` | JSON integer, not boolean, in `0..2^53-1`. |

NFC validation is fail-closed: the service does not silently normalize input before digest verification. A string whose received form is not already NFC is invalid.

## 3. Canonical JSON and content identity

### 3.1 Canonical encoding profile

`canonical_json_v1(value)` is UTF-8 JSON with these exact rules:

1. Decode UTF-8 strictly; reject BOM, invalid UTF-8, duplicate keys, and non-NFC strings.
2. Permit only objects, arrays, strings, booleans, null, and bounded JSON integers. Binary floating-point JSON numbers are forbidden. Quantitative non-integers use the `decimal` string type.
3. Object keys are sorted by Unicode scalar-value order.
4. Arrays retain semantic order unless a schema explicitly declares a canonical sort before encoding.
5. Encode with no insignificant whitespace, `,` and `:` compact separators, lowercase literals, and direct UTF-8 characters rather than ASCII escapes except the JSON-required escapes for quotation mark, reverse solidus, and control characters.
6. Reject lone surrogates and all control characters in schema fields that require printable strings.
7. Append no newline.

The reference Python encoding is equivalent to `json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")` after the strict parse, NFC, integer-range, no-float, and schema checks above. TypeScript must use a shared conformance implementation, not `JSON.stringify` on insertion-ordered objects.

`digest_v1(value) = sha256(canonical_json_v1(value))`.

Golden vectors shared by Python and TypeScript are activation evidence. At minimum they cover Unicode, key ordering, arrays, null, decimal strings, integer bounds, duplicate-key rejection, negative-zero rejection, and manifest/member/request/response identities.

### 3.2 External manifest identity

A manifest never contains its own digest. `manifest_sha256` is the SHA-256 of the exact canonical manifest bytes stored in the immutable manifest store. A noncanonical but semantically equivalent document is rejected as `noncanonical_manifest`; the verifier never reparses and redigests it into a replacement identity.

### 3.3 Digest sets

Where a schema declares a digest set, the producer supplies a JSON array sorted ascending by digest and containing no duplicate. Where a schema declares role/digest pairs, pairs are sorted first by role and then by digest for identity construction.

## 4. Closed policy registry

Callers do not submit formulas, dimensions, weights, thresholds, directions, null rules, origin switches, sample switches, proposal modes, resource limits, deadlines, or arbitrary policy documents. They submit one `policy_set` reference. The deployment resolves it from the following closed registry.

### 4.1 Production policy set

`comparison-prod-v1` contains exactly:

| Policy kind | ID | Version |
|---|---|---:|
| origin | `origin-real-v1` | 1 |
| design | `design-controlled-daily-v1` | 1 |
| metrics | `metrics-daily-v1` | 1 |
| cross-regime | `axis-cross-regime-v1` | 1 |
| cost sensitivity | `axis-cost-total-bps-v1` | 1 |
| capacity | `axis-capacity-disabled-v1` | 1 |
| ranking | `ranking-stability-cost-v1` | 1 |
| operations | `operations-production-v1` | 1 |
| wording | `proposal-wording-v1` | 1 |

Its `policy_set_digest` is the digest of the strict `PolicySetV1` document in section 12. Production accepts only this exact ID and configured digest. A caller cannot choose a prior or alternative digest.

Default required axes are exactly `cross_regime` and `cost_sensitivity`. `capacity` is returned as unavailable metadata but is not a required ranking axis in V1. No production request can add, remove, or reorder required axes.

### 4.2 Hermetic policy set

`comparison-sample-v1` uses the same formulas, ranking, numeric rules, and limits at one-quarter of production row/byte limits. Its origin policy is `origin-sample-v1`, proposal capability is permanently false, and every valid result abstains with `sample_proposal_forbidden`. It exists in a separate executable composition root and separate manifest store.

### 4.3 Test synthetic policy set

`comparison-test-v1` is available only when `process_role=contract_test` is compiled or configured before process start. It accepts only `test_synthetic`, has no network credentials, no production store handle, no result persistence beyond the test temporary directory, and proposal capability is false. Both deployed applications reject this policy set.

### 4.4 Registry mutation

The registry is code/config committed with the comparison engine. Runtime registry mutation is forbidden. Adding or changing a policy requires a new policy ID or version, new digest vectors, a clean committed revision seal, and the full activation process. A digest mismatch is an integrity error, not an instruction to fetch or accept another policy.

## 5. Artifact schemas

### 5.1 `ComparisonBundleManifestV1`

Strict fields:

| Field | Type | Rule |
|---|---|---|
| `schema_version` | literal `comparison.bundle-manifest.v1` | Required. |
| `bundle_kind` | `backtest_run`, `regime_assignment`, `capacity_evidence`, or `origin_attestation` | Required. |
| `producer` | `ProducerIdentityV1` | Required. |
| `created_at` | `utc_timestamp` | Informational; excluded from comparability but included in manifest identity. |
| `declared_origin` | `real_observed`, `sample`, or `test_synthetic` | Never trusted without verification. |
| `candidate` | `CandidateIdentityV1` or null | Null only for a market-wide regime assignment or origin attestation. |
| `run` | `RunIdentityV1` or null | Required for `backtest_run`; null otherwise. |
| `data` | `DataIdentityV1` | Required. |
| `execution` | `ExecutionIdentityV1` or null | Required for `backtest_run`. |
| `members` | array of `BundleMemberV1`, 1..64 | Sorted by `logical_name`; names and semantic roles unique. |
| `evidence_refs` | array of `EvidenceManifestRefV1`, 0..32 | Sorted by role/digest; pair unique. |

`ProducerIdentityV1`:

- `repository_url`: exact allowlisted HTTPS GitHub URL, 1..512 ASCII bytes, no credentials or query;
- `commit`: `git_commit`;
- `component`: `identifier`;
- `component_version`: `identifier`;
- `build_policy_id`: `identifier`;
- `build_policy_digest`: `sha256`;
- `revision_seal_digest`: `sha256`.

`CandidateIdentityV1`:

- `candidate_manifest_digest`: `sha256`;
- `strategy_code_digest`: `sha256`;
- `strategy_semantics_id`: `identifier`;
- `display_ref`: `display_string`, metadata only.

`RunIdentityV1`:

- `run_role`: one of `baseline_cost`, `cost_0000bps`, `cost_0005bps`, `cost_0010bps`, `cost_0020bps`, or `capacity_grid`;
- `run_config_digest`: `sha256`;
- `engine_semantics_id`: literal `platform-backtest-engine-v1` for V1;
- `metric_semantics_id`: literal `metrics-daily-v1`;
- `scenario_parameters`: strict `ScenarioParametersV1`.

`ScenarioParametersV1` contains exactly:

- `total_linear_cost_bps`: canonical nonnegative decimal with exactly four fractional digits;
- `commission_bps`: canonical nonnegative decimal with exactly four fractional digits;
- `slippage_bps`: canonical nonnegative decimal with exactly four fractional digits;
- `spread_model`: literal `unsupported`;
- `borrow_model`: literal `unsupported`;
- `venue_fee_model`: literal `unsupported`;
- `nonlinear_impact_model`: literal `unsupported`.

For V1, `commission_bps + slippage_bps` must equal `total_linear_cost_bps` exactly. Unsupported components are not interpreted as zero; they remain explicit limitations. The required cost roles use totals `0.0000`, `5.0000`, `10.0000`, and `20.0000` bps. How commission and slippage divide the total is fixed across all candidates and all scenarios by `design-controlled-daily-v1`; V1 uses commission `1/6` and slippage `5/6` of total, each quantized to four decimals, with the remainder added to slippage so the exact sum equals the total.

`DataIdentityV1` contains exactly:

- `provider_id`: `identifier`;
- `market_data_digest`: `sha256`;
- `acquisition_receipt_digest`: `sha256`;
- `observation_index_digest`: `sha256`;
- `universe_digest`: `sha256`;
- `date_window`: `{start:date,end:date}`, start not after end;
- `calendar_id`: `identifier`;
- `timezone`: IANA name, exact allowlist entry;
- `adjustment_policy_id`: `identifier`;
- `benchmark_series_digest`: `sha256`.

`ExecutionIdentityV1` contains exactly:

- `signal_timing`: literal `bar_close`;
- `execution_timing`: literal `next_open`;
- `execution_price`: literal `next_open`;
- `rebalance_policy_digest`: `sha256`;
- `initial_cash`: positive `decimal`;
- `base_currency`: literal `USD`;
- `whole_share_orders`: boolean;
- `minimum_order_value`: nonnegative `decimal`;
- `cash_constraint`: literal `no_negative_cash`.

`EvidenceManifestRefV1` contains `role:identifier` and `manifest_sha256:sha256`.

### 5.2 `BundleMemberV1`

Strict fields:

| Field | Type | Rule |
|---|---|---|
| `logical_name` | `logical_name` | Unique in manifest. |
| `media_type` | closed enum | `application/json`, `application/x-ndjson`, `text/csv`, or `application/parquet`. |
| `sha256` | `sha256` | Digest of exact member bytes. |
| `size_bytes` | `nonnegative_int` | Must equal snapshot member size. |
| `semantic_role` | closed role | See below. |
| `schema_id` | `identifier` | Exact member schema. |
| `row_count` | `nonnegative_int` or null | Required for tabular roles. |
| `compression` | literal `none` | V1 archive members are not compressed. |

Closed semantic roles:

- `run_config`
- `metrics_summary`
- `equity_series`
- `return_series`
- `trade_blotter`
- `fill_blotter`
- `observation_index`
- `market_data_receipt`
- `producer_revision_seal`
- `regime_assignment`
- `capacity_curve`
- `capacity_model`
- `origin_attestation`

A proposal-capable `backtest_run` bundle requires exactly one of every role from `run_config` through `producer_revision_seal`. Empty trade or fill blotters are valid only when their schema is present with zero rows and the equity/return series also proves no trading; an absent file is invalid.

### 5.3 Member schemas

#### `ObservationSeriesV1`

Both equity and return members use strict rows sorted ascending by timestamp, with no duplicate timestamp:

- equity row: `timestamp:utc_timestamp`, `equity:positive decimal`;
- return row: `timestamp:utc_timestamp`, `return:decimal`.

The first equity timestamp has no return row. For every later equity row `i`, the return row at the same timestamp must equal `equity_i / equity_(i-1) - 1` under the numeric rules in section 11, quantized to 18 fractional digits. Mismatch greater than `0.000000000000000001` is `metric_recomputation_mismatch`.

All candidates in a comparison must have the same complete ordered return timestamps. Missing observations are not filled, interpolated, forward-filled, or dropped.

#### `TradeRowV1` and `FillRowV1`

Rows are sorted by `(timestamp, stable_id)` and have unique stable IDs. Quantities, requested/fill prices, gross values, commission, and slippage use decimal strings. Side is `buy|sell`; fill status is `filled|partial`. Every fill references an existing trade/order identity. These records verify cost scenario production but are not capacity evidence.

#### `MetricSummaryV1`

Strict fields are `metric_semantics_id`, `observation_count`, `total_return`, `annualized_return`, `volatility`, `sharpe`, `max_drawdown`, and `turnover`. Values are decimal strings quantized to 12 fractional digits. The comparison reader recomputes every rankable metric and rejects a difference above `0.000000000001`. Producer summaries are never ranked directly.

#### `ProducerRevisionSealV1`

Strict fields:

- `schema_version: "producer-revision-seal.v1"`;
- `repository_url`, `commit`, `component`, `build_policy_id`, `build_policy_digest` matching the manifest;
- `source_tree_digest:sha256`;
- `dependency_lock_digest:sha256`;
- `test_receipt_digest:sha256`;
- `clean_worktree:true`;
- `issued_at:utc_timestamp`;
- `issuer_key_id:identifier`;
- `signature_ed25519_base64`: canonical padded Base64 of 64 signature bytes.

The signature covers canonical JSON of all preceding fields. Issuer public keys are allowlisted by the origin policy. Revoked keys or commits fail origin verification; revocation does not mutate old bytes but removes proposal eligibility on every read.

### 5.4 `OriginAttestationV1`

Strict fields:

- `schema_version: "origin-attestation.v1"`;
- `attestation_id:identifier`;
- `provider_id:identifier`;
- `issuer_id:identifier`;
- `issuer_key_id:identifier`;
- `acquisition_component:identifier`;
- `acquisition_commit:git_commit`;
- `acquisition_config_digest:sha256`;
- `source_receipt_ids`: sorted unique array of 1..256 identifiers;
- `raw_member_digests`: sorted unique array of 1..1,024 SHA-256 digests;
- `market_data_digest:sha256`;
- `observation_index_digest:sha256`;
- `universe_digest:sha256`;
- `coverage_start:utc_timestamp`;
- `coverage_end:utc_timestamp`;
- `contains_sample:false`;
- `contains_fixture:false`;
- `contains_synthetic:false`;
- `issued_at:utc_timestamp`;
- `signature_ed25519_base64`.

The issuer signs canonical JSON excluding the signature. `origin-real-v1` derives `real_observed` only when provider, issuer, key, acquisition component/commit/config, producer commit, and build policies are allowlisted; signatures verify; all bound digests match; coverage contains the comparison window; and all three marker booleans are false. A provider label or successful network call alone has no evidentiary value.

## 6. Candidate group schema and ranking unit

### 6.1 `CandidateGroupManifestV1`

The ranking unit is exactly one candidate group. It is not a Run, scenario, bundle, display ref, or mutable candidate ID.

Strict fields:

- `schema_version: "comparison.candidate-group.v1"`;
- `candidate_manifest_digest:sha256`;
- `strategy_code_digest:sha256`;
- `strategy_semantics_id:identifier`;
- `members`: sorted array of `CandidateGroupMemberV1`, 5..16;
- `group_digest:sha256`.

`CandidateGroupMemberV1` contains exactly `role` and `manifest_sha256`. Required roles are `baseline_cost`, `cost_0000bps`, `cost_0005bps`, `cost_0010bps`, and `cost_0020bps`. Optional roles in V1 are `capacity_evidence` and `origin_attestation`. Roles are unique.

`group_digest` is the digest of the document excluding `group_digest`. Every member manifest with candidate identity must match the group candidate, strategy code, and strategy semantics. A bundle digest may appear in only one group in a request. Candidate manifest digests and group digests are unique. Every role resolves to exactly one bundle.

All axis values are computed at group level from those exact members. There is no cross-run averaging except the formulas explicitly defined below.

## 7. Request, authorization, cancellation, and deadline

### 7.1 `BacktestComparisonRequestV1`

Strict fields:

| Field | Type | Rule |
|---|---|---|
| `schema_version` | literal `comparison.request.v1` | Required. |
| `candidate_groups` | array of 2..8 `CandidateGroupRequestV1` | Request order nonsemantic. |
| `policy_set` | `{id:identifier,digest:sha256}` | Must equal the deployment-selected exact policy. |
| `client_request_id` | null or ASCII `^[A-Za-z0-9._:-]{1,128}$` | Correlation only. |

`CandidateGroupRequestV1` contains `candidate_manifest_digest`, `group_manifest_sha256`, and `group_digest`, all SHA-256. The service verifies the external group manifest and its internal group digest.

The request contains no required-axis list, sample switch, real-only switch, formula, threshold, weight, score key, direction, null rule, proposal mode, Gate field, path, filename, Run ID, candidate ID, timeout, cache control, resource limit, provider override, or origin declaration.

### 7.2 Authorization without existence leakage

`ComparisonAuthorizationV1` is internal and never serialized into the public response. It contains authenticated owner/user scope, workspace scope, allowed manifest namespace, and request operation ID.

Authorization is performed for the complete deduplicated set of group and bundle manifest digests before any public artifact-specific response, cache lookup, member read, event naming, or timing distinction. The authorization adapter returns only an internal bitset. Public behavior is:

- if any requested manifest is missing, unauthorized, outside scope, archived, or hidden, return HTTP 404 problem code `artifact_not_found_or_unauthorized`;
- the public title, detail, body length class, headers, and retry semantics are identical for every one of those cases;
- the response never identifies which digest failed or how many failed;
- no `bundle_verified` event is published until the full set is authorized;
- audit logs may record exact internal causes only in a restricted sink that is inaccessible to the caller.

The implementation performs a bounded authorization call for every distinct requested digest even after an earlier failure. It pads public failure completion to the deployment-configured 20 ms bucket, with a maximum of one bucket of jitter derived from an HMAC of the operation ID. This is not a cryptographic constant-time claim; it prevents direct branch and early-exit existence leakage within the service contract.

Authorization is rechecked on every request, including cache hits. Cached result existence is never exposed to an unauthorized caller.

### 7.3 Immutable snapshot

After authorization, `ManifestStore.open_many` returns one snapshot token binding every manifest and member object version. The reader verifies metadata and bytes under that token. Any version change, replacement, truncation, or deletion before completion returns `artifact_snapshot_changed`. No retry substitutes newer bytes inside the request.

### 7.4 Cancellation

The service receives a transport-scoped `CancellationToken`; it is not caller JSON. Cancellation becomes effective at the next required boundary:

1. after authorization;
2. after snapshot open;
3. after each manifest;
4. before and after each member read;
5. every 10,000 parsed rows;
6. before and after each origin, design, and axis evaluation;
7. before ranking;
8. before cache commit;
9. before response/event publication.

Cancellation returns HTTP 499 with `cancelled`. It writes no completed result, proposal, abstention, cache value, or terminal comparison event. Temporary buffers are discarded.

### 7.5 Deadline

The operations policy fixes a monotonic execution deadline of 30,000 ms from entry into the service after request-body parsing and authentication. Callers cannot extend or shorten it in JSON. Queue time inside the comparison worker counts. The monotonic deadline is checked at every cancellation boundary.

Deadline expiration returns HTTP 504 with `deadline_exceeded` and the same no-partial-output guarantees as cancellation. Wall-clock timestamps do not participate in comparison identity, formulas, or rank.

## 8. Origin policy and deployment isolation

### 8.1 `OriginEvidenceV1`

Strict response object:

- `schema_version: "comparison.origin-evidence.v1"`;
- `origin: "real_observed"|"sample"|"test_synthetic"`;
- `status: "verified"|"conflict"|"unverifiable"`;
- `display_label: "REAL OBSERVED"|"SAMPLE"|"TEST SYNTHETIC"`;
- `origin_policy:{id,digest}`;
- `provider_id:identifier`;
- `producer_revision_seal_digest:sha256`;
- `origin_attestation_digest:sha256|null`;
- `evidence_digests`: sorted unique SHA-256 array;
- `reason_code`: closed reason or null;
- `origin_evidence_digest:sha256`.

The evidence digest covers all fields except itself.

### 8.2 Closed admissibility matrix

| Process | Accepted all-member origin | Rejected origins | Proposal possible |
|---|---|---|---|
| production | `real_observed` | `sample`, `test_synthetic`, mixed, unverifiable | yes, subject to all gates |
| hermetic sample | `sample` | `real_observed`, `test_synthetic`, mixed, unverifiable | never |
| contract test | `test_synthetic` | `real_observed`, `sample`, mixed, unverifiable | never |

A group origin is verified only if every bundle and referenced origin artifact derives the exact same origin under the process policy. A comparison origin is verified only if every group has the same origin. Mixed origins return problem code `origin_mixed`; they do not become an abstention.

The production binary is composed without sample-store credentials or test fixture loaders. The sample binary is composed without production-store credentials, Gate clients, or production issuer keys. `TEST SYNTHETIC` is rejected by both deployed binaries even if a manifest declares it as sample or real.

## 9. Controlled comparison design

### 9.1 `ComparisonDesignV1`

Strict fields:

- `schema_version: "comparison.design.v1"`;
- `design_policy:{id,digest}`;
- `candidate_group_digests`: ascending unique digest array;
- `candidate_manifest_digests`: ascending unique digest array;
- `fixed_dimensions: FixedDimensionsV1`;
- `candidate_dimensions`: array keyed by candidate manifest digest;
- `axis_controlled_dimensions: AxisControlledDimensionsV1`;
- `bundle_role_bindings`: canonical array of group/role/manifest digest;
- `observation_index_digest:sha256`;
- `design_digest:sha256`.

`design_digest` covers all preceding fields.

### 9.2 Comparability predicate

Two or more candidate groups are comparable if and only if all predicates below are true:

1. Every group passes schema, member, origin, and candidate-binding verification.
2. Across every group and every required run role, these fields are byte-equal: provider ID, market-data digest, acquisition receipt digest, observation-index digest, universe digest, date window, calendar, timezone, adjustment policy, benchmark-series digest, engine semantics, metric semantics, signal timing, execution timing, execution price, rebalance policy digest, initial cash, base currency, whole-share rule, minimum-order-value rule, cash constraint, and all policy-declared controls.
3. Candidate manifest digest, strategy code digest, and strategy semantics may differ between groups and are the only candidate-owned varying dimensions.
4. Within one group, candidate identity and every fixed dimension are equal across all scenario runs.
5. Across cost roles, only commission bps, slippage bps, total linear cost bps, run config digest, metrics, equity, returns, trades, and fills may vary. The scenario totals and role names must equal the closed grid. Unsupported cost component declarations remain identical.
6. Across candidates at the same cost role, scenario parameters are equal.
7. Return timestamp arrays are byte-equal across every required run after strict parsing. No intersection, union, truncation, filling, resampling, or tolerance-based timestamp match is allowed.
8. Regime assignment is derived once from the shared benchmark series and observation index, then used unchanged for every candidate.
9. No bundle is reused across groups and no role is duplicated or omitted.

Failure is HTTP problem `not_comparable` with a non-sensitive dimension reason code. Public details may name the dimension class, such as `window_mismatch`, but never expose hidden artifact content.

## 10. Axis schemas and formulas

### 10.1 Common axis envelope

Every axis result contains:

- `schema_version` specific to the axis;
- `candidate_group_digest`;
- `candidate_manifest_digest`;
- `axis`;
- `status: "complete"|"unavailable"`;
- `reason_code:null|closed reason`;
- `policy:{id,digest}`;
- `source_manifest_digests`: sorted SHA-256 array;
- axis-specific payload and ranking key;
- `limitations`: sorted unique reason strings;
- `result_digest` covering every preceding field.

`unavailable` means valid evidence does not contain the capability required by the policy or fails a policy minimum that explicitly permits abstention. Supplied malformed evidence is never converted to an axis object; it follows the HTTP `axis_evidence_invalid` rule in section 10.4. An unavailable required axis causes whole-comparison abstention.

### 10.2 Metric formula `metrics-daily-v1`

Input is the exact ordered daily equity/return series. The observation frequency is one row per shared trading-session observation index; intraday and duplicated sessions are invalid. Annualization factor `A=252`. Risk-free return is exactly zero. All calculations use section 11 decimal rules.

For `n` returns `r_1..r_n` and starting equity `E_0`:

- `total_return = product(1+r_i) - 1`.
- `annualized_return = product(1+r_i)^(252/n) - 1`; `n>=1` and every compounded wealth factor must remain positive.
- `mean_return = sum(r_i)/n`.
- `population_variance = sum((r_i-mean_return)^2)/n`.
- `volatility = sqrt(population_variance) * sqrt(252)`.
- `sharpe = mean_return / sqrt(population_variance) * sqrt(252)` when variance is positive; when variance is zero, Sharpe is exactly `0` only if mean is zero, otherwise metric status is invalid with `zero_variance_nonzero_return`.
- `drawdown_i = 1 - E_i / max(E_0..E_i)`.
- `max_drawdown = max(drawdown_i)`, nonnegative.
- `turnover = sum(abs(fill_gross_value_i)) / initial_cash`.

At least 20 returns are required for rankable metrics. Missing, non-finite, nonpositive equity, timestamp mismatch, arithmetic domain error, or summary recomputation mismatch is invalid. No row is silently removed.

### 10.3 Regime assignment `regime-assignment-momentum126-vol20-v1`

The shared benchmark member contains a positive adjusted close for each observation timestamp. Benchmark returns use the same return formula.

For timestamp index `i` with at least 126 prior benchmark returns:

- `momentum126_i = product(1+b_j for j=i-126..i-1) - 1`.
- `vol20_i = population_stddev(b_j for j=i-20..i-1) * sqrt(252)`.
- volatility threshold is exactly `0.200000000000000000`.
- momentum sign uses `momentum126_i >= 0` as nonnegative.

Closed label order and assignment:

1. `risk_on_low_vol`: momentum nonnegative and vol below threshold;
2. `risk_on_high_vol`: momentum nonnegative and vol at or above threshold;
3. `risk_off_low_vol`: momentum negative and vol below threshold;
4. `risk_off_high_vol`: momentum negative and vol at or above threshold;
5. `unknown`: insufficient lookback only.

The assignment at index `i` never reads `b_i` or any later return. The first 126 return timestamps, indices `0..125`, are `unknown`; index `126` is the first classifiable timestamp and uses only returns `0..125`. Any later missing/invalid benchmark input invalidates the assignment instead of producing unknown.

`RegimeAssignmentV1` is a strict object with exactly:

- `schema_version:"regime-assignment.v1"`;
- `method:{id:"regime-assignment-momentum126-vol20-v1",digest:sha256}`;
- `source_benchmark_series_digest:sha256`;
- `source_market_data_digest:sha256`;
- `observation_index_digest:sha256`;
- `timezone`: an allowlisted IANA name;
- `closed_label_order:["risk_on_low_vol","risk_on_high_vol","risk_off_low_vol","risk_off_high_vol","unknown"]`;
- `assignments`: timestamp-ascending array of strict `{timestamp:utc_timestamp,label:closed regime label}` objects with no duplicate timestamp;
- `coverage`: strict `{expected:nonnegative_int,assigned:nonnegative_int,unknown:nonnegative_int,missing:nonnegative_int}`;
- `assignment_digest:sha256`, covering every preceding field.

Coverage requires `expected = len(observation index)`, `assigned + unknown = expected`, and `missing = 0`. Assignment timestamps must equal the observation index byte-for-byte and in the same order.

### 10.4 `CrossRegimeResultV1`

Per non-unknown regime, filter candidate baseline returns by label while retaining original order and build regime pseudo-equity starting at 1 by cumulative multiplication. Compute `observation_count`, `compounded_return`, `annualized_return`, `volatility`, `sharpe`, and `max_drawdown` using `metrics-daily-v1` on that subsequence. Every one of the four regimes requires at least 20 candidate returns. Unknown-assignment coverage must be exactly 126 and is excluded identically for all candidates.

Ranking fields:

- `worst_regime_sharpe = min(regime_sharpe)`;
- `sharpe_dispersion = max(regime_sharpe) - min(regime_sharpe)`;
- `sign_consistency = count(regime_compounded_return > 0) / 4`;
- `stress_drawdown = max(regime_max_drawdown)`;
- `stability_score = worst_regime_sharpe - sharpe_dispersion - stress_drawdown`.

All values are quantized to 12 fractional digits. The strict result payload is:

- `per_regime`: exactly four `PerRegimeMetricsV1` rows in the non-unknown closed-label order;
- `coverage`: strict `{total:nonnegative_int,unknown:nonnegative_int,classified:nonnegative_int,per_regime_counts:[{label:non-unknown label,count:nonnegative_int}]}`;
- `ranking_key`: strict `{stability_score:decimal|null,worst_regime_sharpe:decimal|null,sharpe_dispersion:decimal|null,sign_consistency:decimal|null,stress_drawdown:decimal|null}`.

`PerRegimeMetricsV1` contains exactly `label`, `observation_count`, `compounded_return`, `annualized_return`, `volatility`, `sharpe`, and `max_drawdown`; all metrics are published-scale decimals. Insufficient observations produce `status="unavailable"`, `reason_code="insufficient_regime_observations"`, an empty `per_regime`, valid coverage, and all-null ranking fields.

There is one unambiguous invalid-axis rule for every axis: **if supplied evidence exists but violates schema, digest binding, controlled-design binding, arithmetic domain, recomputation tolerance, or any axis invariant, the request fails as HTTP 422 `axis_evidence_invalid`; no `BacktestComparisonResponseV1`, axis result, abstention, ranking, recommendation, or cache entry is produced.** Validate-only diagnostics and observability may record internal state `invalid`, but that state MUST NOT appear in a public comparison response. Valid evidence lacking a required capability or minimum sample is `unavailable` and may produce canonical whole-comparison abstention.

### 10.5 `CostSensitivityResultV1`

The four exact cost scenario runs are evaluated independently from their own verified equity/return series using `metrics-daily-v1`. Scenario order is ascending total cost bps. At least these four scenarios are required; extra scenarios are rejected in V1.

Let `x_i` be total cost bps, `a_i` annualized return, and `s_i` Sharpe. Let `x_bar` and `y_bar` be arithmetic means. Exact ordinary-least-squares slopes are:

- `return_slope_per_bps = sum((x_i-x_bar)*(a_i-a_bar)) / sum((x_i-x_bar)^2)`;
- `sharpe_slope_per_bps = sum((x_i-x_bar)*(s_i-s_bar)) / sum((x_i-x_bar)^2)`.

Other fields:

- `cost_degradation = annualized_return_at_0bps - annualized_return_at_20bps`;
- `worst_scenario_annualized_return = min(a_i)`;
- `worst_scenario_sharpe = min(s_i)`;
- `break_even_bps` is null when every `a_i>0`; otherwise it is the smallest scenario x with `a_i=0`, or the linear interpolation between the adjacent ascending scenarios that first bracket positive to negative: `x_lo + (0-a_lo)*(x_hi-x_lo)/(a_hi-a_lo)`. Nonmonotonic results are still reported but add limitation `nonmonotonic_cost_response`.

The strict result contains `design_kind="total_linear_bps_grid"`; `scenarios`, exactly four strict `CostScenarioMetricsV1` objects in ascending cost order; and `ranking_key`, exactly `{cost_degradation,return_slope_per_bps,sharpe_slope_per_bps,worst_scenario_annualized_return,worst_scenario_sharpe,break_even_bps}`, each `decimal|null`.

`CostScenarioMetricsV1` contains exactly `role`, `total_linear_cost_bps`, `commission_bps`, `slippage_bps`, `observation_count`, `annualized_return`, `sharpe`, and `metrics_digest`. Missing controlled roles produce `status="unavailable"`, `reason_code="insufficient_controlled_cost_scenarios"`, `scenarios=[]`, and an all-null ranking key. A malformed supplied scenario follows the single HTTP `axis_evidence_invalid` rule above.

Spread, borrow, venue fees, and nonlinear impact remain limitations in every V1 result. They are never treated as included or zero.

### 10.6 `CapacityResultV1`

The initial policy is `axis-capacity-disabled-v1`. It accepts no capacity bundle as proposal evidence and deterministically returns:

- `schema_version: "comparison.axis.capacity.v1"`;
- `axis: "capacity"`;
- `status: "unavailable"`;
- `reason_code: "capacity_evidence_missing"`;
- `model_id:null`;
- `model_digest:null`;
- `liquidity_evidence_digest:null`;
- `notional_grid:[]`;
- `curve:[]`;
- `ranking_key:{supported_capacity:null}`;
- limitations exactly `ADV/volume evidence unavailable`, `participation policy unavailable`, `spread and impact model unavailable`.

Capacity cannot become complete by configuration or caller input. Activation requires a new versioned capacity policy and producer schema with verified ADV/volume observations, participation limits, spread and nonlinear impact assumptions, exact notional grid, model implementation digest, calibration evidence, and validation tests. Turnover, concentration caps, minimum order value, whole-share rules, cash constraints, and partial fills are explicitly non-evidence.

### 10.7 Literal golden boundary vectors

These vectors are normative shared fixtures, not illustrative prose. Decimal outputs use the publication rules in section 11.

| Vector | Exact input | Exact result |
|---|---|---|
| regime insufficient boundary | benchmark returns at indices `0..125`, all `0.000000000000000000` | labels `0..125` are `unknown`; no read of index `126` occurs |
| first classifiable regime | returns `0..125` all zero; evaluate `i=126`; current return `b_126=-0.900000000000000000` | `momentum126=0.000000000000`; `vol20=0.000000000000`; label `risk_on_low_vol`; changing only `b_126` cannot change this label |
| prior-only momentum boundary | `b_0..b_124=0`, `b_125=-0.000000000000000001`; evaluate `i=126` | momentum is negative; the label is risk-off and is selected from the unquantized prior-only statistics |
| volatility threshold equality | prior returns `106..115` are `-0.012598815766974240907150551207806002027191710395630` and `116..125` are `+0.012598815766974240907150551207806002027191710395630`; returns `0..105` are zero | population mean is zero and annualized population volatility is exactly `0.200000000000000000`; momentum is negative, so label is `risk_off_high_vol`; equality belongs to high volatility |
| zero Sharpe | twenty returns all `0.000000000000000000` | mean `0`; variance `0`; `sharpe="0.000000000000"` |
| invalid zero variance | twenty returns all `0.010000000000000000` | HTTP 422 `axis_evidence_invalid`, internal reason `zero_variance_nonzero_return` |
| half-even down | unquantized published value `1.2345678901225` | `1.234567890122` |
| half-even up | unquantized published value `1.2345678901235` | `1.234567890124` |
| signed zero | unquantized result `-0E-50` | `0.000000000000` |
| break-even equality | annualized returns at `[0,5,10,20]` bps are `[0.1,0,-0.1,-0.2]` | `break_even_bps="5.000000000000"` |
| digest tie | all seven ordered ranking keys equal after quantization for candidate digests `00...01` and `00...02` | `00...01` ranks first; no shared rank |
| null key | one required ordered key is null | whole comparison abstains with `required_ranking_key_null`; ranking is empty |

The volatility-threshold fixture stores the exact decimals above and the expected intermediate variance in the shared fixture corpus; implementations MUST NOT convert them through binary float. The corpus also includes one-return-before and one-return-after perturbations proving that only indices `i-126..i-1` and `i-20..i-1` influence label `i`.

## 11. Decimal, rounding, null, and tie rules

All arithmetic uses base-10 arbitrary precision with context precision 50 significant digits and `ROUND_HALF_EVEN`. Inputs are parsed directly from canonical decimal strings; conversion through binary float is forbidden.

- Addition, subtraction, multiplication, division, exponentiation, and square root are performed at precision 50.
- Fractional powers use `exp(exponent * ln(base))` from the same correctly rounded decimal library, with positive base only.
- Intermediate values are not quantized unless a formula explicitly requires it.
- Published metrics and ranking keys are quantized to exactly 12 fractional digits using half-even rounding and serialized with exactly 12 digits after the decimal point.
- Return/equity consistency values are quantized to 18 fractional digits.
- Cost bps values use exactly four fractional digits.
- Any result mathematically equal to zero serializes as positive zero, such as `0.000000000000`; negative zero is forbidden.
- Null is permitted only where the schema explicitly permits it. Null never sorts high or low. A null required ranking key makes the candidate-axis pair incomplete and causes whole-comparison abstention.
- Candidate rank compares ordered keys lexicographically after quantization. Exact equality on every ordered key is broken by ascending `candidate_manifest_digest` byte value. Therefore no equal rank numbers exist; ranks are consecutive integers starting at 1.
- Input order, member physical location, hostname, request correlation, thread schedule, cache state, and event delivery do not affect results.

## 12. Policy schemas and initial values

### 12.1 `PolicyRefV1`

Strict fields: `id:identifier`, `version:positive_int`, `digest:sha256`.

### 12.2 `PolicySetV1`

Strict fields:

- `schema_version: "comparison.policy-set.v1"`;
- `policy_set_id:identifier`;
- `policy_set_version:positive_int`;
- `deployment_mode:"production"|"sample"|"test"`;
- `origin_policy:PolicyRefV1`;
- `design_policy:PolicyRefV1`;
- `metric_policy:PolicyRefV1`;
- `axis_policies`: exactly three refs keyed by closed axis;
- `axis_states`: strict `AxisStateManifestV1` with exactly `cross_regime`, `cost_sensitivity`, and `capacity`;
- `ranking_policy:PolicyRefV1`;
- `operations_policy:PolicyRefV1`;
- `wording_policy:PolicyRefV1`;
- `required_axes`: exactly `["cross_regime","cost_sensitivity"]` for production V1;
- `proposal_enabled`: true only in production;
- `policy_set_digest:sha256`.

The digest covers all preceding fields.

### 12.3 `RankingPolicyV1`

Initial `ranking-stability-cost-v1` strict fields and values:

- `schema_version: "comparison.ranking-policy.v1"`;
- `policy_id: "ranking-stability-cost-v1"`;
- `policy_version:1`;
- `required_axes:["cross_regime","cost_sensitivity"]`;
- `eligibility_rules:["all_groups_origin_verified","design_comparable","all_required_axis_results_complete","all_required_ranking_keys_nonnull","proposal_capability_enabled"]`;
- `ordered_keys` exactly:
  1. `cross_regime.stability_score`, descending;
  2. `cross_regime.worst_regime_sharpe`, descending;
  3. `cross_regime.sharpe_dispersion`, ascending;
  4. `cross_regime.sign_consistency`, descending;
  5. `cross_regime.stress_drawdown`, ascending;
  6. `cost_sensitivity.cost_degradation`, ascending;
  7. `cost_sensitivity.worst_scenario_sharpe`, descending;
- each null rule is literal `ineligible_whole_comparison`;
- `decimal_precision:50`;
- `rounding:"ROUND_HALF_EVEN"`;
- `published_scale:12`;
- `tie_breaker:"candidate_manifest_digest_ascending"`;
- `proposal_wording_version:"proposal-wording-v1"`;
- `policy_digest:sha256`.

No weighted sum is used. The ordered keys are the entire ranking algorithm.

### 12.4 `OperationsPolicyV1`

`OperationsPolicyV1` is a strict object containing exactly the following positive integer fields, plus `cache_ttl_seconds`; no limit is caller-overridable:

| Field | Production value |
|---|---:|
| `request_json_bytes` | 65,536 |
| `candidate_groups_min` | 2 |
| `candidate_groups_max` | 8 |
| `bundle_manifests_per_request` | 128 |
| `members_per_bundle` | 64 |
| `evidence_refs_per_bundle` | 32 |
| `manifest_bytes_each` | 131,072 |
| `group_manifest_bytes_each` | 65,536 |
| `member_bytes_each` | 134,217,728 |
| `aggregate_snapshot_member_bytes` | 536,870,912 |
| `rows_per_tabular_member` | 2,000,000 |
| `timestamps_per_series` | 500,000 |
| `source_receipt_ids` | 256 |
| `raw_origin_member_digests` | 1,024 |
| `execution_deadline_ms` | 30,000 |
| `concurrent_comparisons_per_process` | 4 |
| `queued_comparisons_per_process` | 32 |
| `overload_retry_seconds` | 5 |
| `parser_nesting_depth` | 32 |
| `result_response_bytes` | 4,194,304 |
| `memory_bytes_per_comparison` | 1,073,741,824 |
| `cache_entries` | 10,000 |
| `cache_aggregate_bytes` | 10,737,418,240 |
| `cache_ttl_seconds` | 604,800 |

The sample process uses one-quarter of every byte, row, timestamp, queue, and cache limit, rounded down but never below the schema minimum; it retains the same candidate minimum and 30,000 ms deadline. Contract tests may lower limits through a separately compiled test policy, never through request data. Exceeding a structural request limit is `invalid_request`; exceeding an artifact or working-set limit is `resource_limit_exceeded`. No truncation or sampling is permitted.

### 12.5 `DeploymentManifestV1`

Each process starts from one immutable, strict deployment manifest. Every nested object is closed; unknown or omitted fields reject startup. The manifest contains exactly:

- `schema_version:"comparison.deployment-manifest.v1"`;
- `service:{id:identifier,engine_version:identifier,deployment_mode:"production"|"sample"|"test",revision_seal_digest:sha256}`;
- `policy_set:{id:identifier,digest:sha256}`;
- `capabilities:CapabilityManifestV1`;
- `limits:OperationsPolicyV1`;
- `stores:StoreBindingsV1`;
- `isolation:IsolationPolicyV1`;
- `manifest_digest:sha256`, covering every preceding field.

`CapabilityManifestV1` contains exactly:

- `evidence_reader:"disabled"|"validate_only"|"enabled"`;
- `origin_verifier:"disabled"|"validate_only"|"enabled"`;
- `design_validator:"disabled"|"validate_only"|"enabled"`;
- `axes:AxisStateManifestV1`;
- `ranking:"disabled"|"validate_only"|"proposal_enabled"`;
- `proposal:"disabled"|"private_canary"|"enabled"`;
- `result_cache:"disabled"|"enabled"`;
- `events:"disabled"|"enabled"`.

`AxisStateManifestV1` contains exactly the three keys `cross_regime`, `cost_sensitivity`, and `capacity`, each with value `disabled|validate_only|proposal_enabled`. There are no implicit axis defaults. Production V1 startup requires capacity `disabled`; an attempt to mark it `validate_only` or `proposal_enabled` rejects startup. Ranking may be `proposal_enabled` only when cross-regime and cost sensitivity are both `proposal_enabled`. Proposal may be `private_canary|enabled` only when the reader, origin verifier, and design validator are `enabled`, ranking is `proposal_enabled`, and every required axis is `proposal_enabled`.

`StoreBindingsV1` contains exactly `manifest_store_id`, `member_store_id`, `cache_namespace`, `audit_sink_id`, and `issuer_registry_id`, all identifiers. It contains no credentials or mutable paths.

`IsolationPolicyV1` contains exactly:

- `accepted_origin:"real_observed"|"sample"|"test_synthetic"`;
- `production_store_access:boolean`;
- `sample_store_access:boolean`;
- `test_store_access:boolean`;
- `gate_clients_present:false`;
- `broker_clients_present:false`;
- `market_data_network_present:false`.

The only valid store-access tuples are production `(true,false,false)`, sample `(false,true,false)`, and contract test `(false,false,true)`. The accepted origin must match the deployment mode. The production and sample processes reject `deployment_mode="test"`; a test process rejects startup unless `process_role="contract_test"` was fixed before process start.

The deployment manifest is not caller input. Its exact bytes and digest are included in release evidence. Runtime environment variables may select only the path or content-addressed reference to the sealed manifest; they cannot override a nested capability, axis state, policy, limit, store, or isolation field.

## 13. Response and problem schemas

### 13.1 `BacktestComparisonResponseV1`

Strict fields:

- `schema_version: "comparison.response.v1"`;
- `terminal_state: "proposal_ready"|"abstained"`;
- `comparison_id:sha256`;
- `semantic_request_digest:sha256`;
- `response_digest:sha256`;
- `service:{id:identifier,engine_version:identifier,deployment_mode:"production"|"sample"|"test",revision_seal_digest:sha256}`;
- `policy_set:{id,digest}`;
- `origin:OriginEvidenceV1`;
- `design:ComparisonDesignV1`;
- `artifacts`: canonical group/role/manifest/member digest projection with no paths;
- `axes`: one result per candidate group for each closed axis, ordered by candidate manifest digest then axis order;
- `ranking`: array of `RankingRowV1`, empty on abstention;
- `recommendation:RecommendationV1`;
- `limitations`: sorted unique reason strings;
- `created_from_immutable_evidence:true`;
- `correlation:{client_request_id:null|string}`.

`RankingRowV1` contains `rank`, `candidate_group_digest`, `candidate_manifest_digest`, and the exact ordered key/value array used. It contains no mutable candidate reference.

`semantic_request_digest` covers the normalized request with candidate groups sorted by candidate manifest digest and excludes `client_request_id`.

`comparison_id` is the digest of:

- semantic request digest;
- verified group manifests and bundle role/digest bindings;
- policy set ID and digest;
- service engine version and deployment mode.

`response_digest` covers the entire response excluding `response_digest` and `correlation`. Consequently correlation changes do not change result identity.

### 13.2 `RecommendationV1`

Proposal form contains exactly:

- `status:"proposal_only"`;
- `candidate_group_digest:sha256`;
- `candidate_manifest_digest:sha256`;
- `evidence_set_digest:sha256`;
- `ranking_policy:{id,digest}`;
- `wording_version:"proposal-wording-v1"`;
- `statement:"Proposed for independent manual Gate 2 review; not approved, registered, promoted, executable, or authorized."`;
- `next_action:"manual_gate_2_review"`;
- `reason_codes:[]`.

Abstention form contains exactly:

- `status:"abstain"`;
- `candidate_group_digest:null`;
- `candidate_manifest_digest:null`;
- `evidence_set_digest:sha256`;
- `ranking_policy:{id,digest}`;
- `wording_version:"proposal-wording-v1"`;
- `statement:"No candidate is proposed."`;
- `next_action:null`;
- `reason_codes`: sorted unique nonempty closed array.

### 13.3 Gate non-handoff rule

A comparison response is not a Gate receipt, approval capability, mutation request, or review decision. It MUST NOT contain:

- `candidate_ref` or candidate ID accepted by Gate 2;
- `expected_status`, `decision`, human note, actor, approval ID, approval token, nonce, CAS version, mutation URL, callback URL, CLI command, form defaults, auto-submit flag, registration field, promotion field, or base commit;
- a serialized `ReviewCandidateCAS`, `PreparePromotionReview`, or equivalent action object.

The UI may display `next_action` as plain text and may offer navigation to the independent candidate review surface. Navigation carries no candidate ID, digest, expected status, decision, or note in query, route state, local storage, clipboard payload, or form prefill.

A human Gate 2 review begins independently. Its authority reopens and displays exact candidate bytes under its own authorization, then requires human-supplied candidate reference, exact expected manifest digest, `expected_status=pending`, decision, and nonempty note under the existing CAS contract. Comparison rank or recommendation is not accepted as evidence that those fields were reviewed.

Every Gate mutation schema must reject the complete comparison response because required Gate fields are absent and comparison fields are unknown. Comparison and UI modules must not import, instantiate, or invoke Gate, promotion, Git, release, broker, or trading clients.

### 13.4 `ComparisonProblemV1`

HTTP errors use `application/problem+json` with strict fields:

- `schema_version:"comparison.problem.v1"`;
- `type`: stable URN `urn:hermes:comparison:<code>`;
- `title`: fixed public title;
- `status`: integer HTTP status;
- `code`: closed code;
- `detail`: fixed non-sensitive text;
- `operation_id`: opaque correlation ID;
- `retryable`: boolean.

No artifact digest, candidate identity, path, policy content, hidden count, or internal exception appears.

## 14. Error versus abstention

### 14.1 HTTP problem responses

These mean the request or purported evidence cannot safely produce a valid comparison object:

| Code | HTTP | Retryable |
|---|---:|---:|
| `invalid_request` | 400 | no |
| `schema_unsupported` | 400 | no |
| `policy_digest_mismatch` | 409 | no |
| `artifact_not_found_or_unauthorized` | 404 | no |
| `artifact_digest_mismatch` | 422 | no |
| `artifact_snapshot_changed` | 409 | yes with same digests |
| `noncanonical_manifest` | 422 | no |
| `producer_evidence_incomplete` | 422 | no |
| `origin_conflict` | 422 | no |
| `origin_unverifiable` | 422 | no |
| `origin_mixed` | 422 | no |
| `not_comparable` | 422 | no |
| `metric_recomputation_mismatch` | 422 | no |
| `axis_evidence_invalid` | 422 | no |
| `resource_limit_exceeded` | 413 | no |
| `cancelled` | 499 | yes by caller |
| `deadline_exceeded` | 504 | yes with same digests |
| `comparison_overloaded` | 429 | yes; honor `Retry-After` |
| `result_cache_conflict` | 500 | no; service quarantined |
| `deterministic_engine_corrupt` | 500 | no; service quarantined |

### 14.2 Canonical abstention reasons

These apply only after request, authorization, artifact integrity, origin, and controlled design are valid:

- `axis_capability_disabled`
- `axis_validate_only`
- `axis_unavailable`
- `capacity_evidence_missing`
- `insufficient_regime_observations`
- `insufficient_controlled_cost_scenarios`
- `required_ranking_key_null`
- `proposal_capability_disabled`
- `sample_proposal_forbidden`

If any required candidate-axis pair is unavailable, the service returns one abstention containing every applicable closed reason, an empty ranking, and no candidate. It never drops an incomplete candidate to rank survivors. Supplied invalid evidence returns HTTP `axis_evidence_invalid` and no comparison response.

Capacity unavailability alone does not abstain production V1 because capacity is not a required axis. It remains visible in limitations and axis results.

## 15. Cache behavior

The result cache is optional and non-authoritative. Cache key is `comparison_id`. The cached value is canonical response bytes with `correlation.client_request_id=null`, plus response digest, source snapshot object versions, policy-set digest, engine revision seal, and expiration. Entries expire exactly 604,800 monotonic seconds after successful commit; wall-clock changes do not extend them. A read after expiry behaves as a miss and schedules deterministic eviction.

Processing order on every request is authentication, complete-set authorization, immutable snapshot open, semantic identity derivation, then cache lookup. A cache hit is valid only if policy digest and engine revision match and the snapshot store confirms every bound object version still exists and is not revoked. Origin issuer/key/commit revocation is checked before serving a hit. In-flight identical comparisons may share one computation only after every caller has independently passed authentication and complete-set authorization; cancellation disconnects only that waiter unless all waiters cancel, and each waiter retains its own deadline.

The cache stores only complete proposal or abstention responses after the final cancellation/deadline check. It never stores problems, cancellation, deadline expiry, partial axes, or events. On return, the service injects the request correlation without changing `response_digest`.

`put_if_absent` semantics:

- absent key: atomically store bytes;
- same key and byte-identical value: replay success;
- same key and different bytes: return `result_cache_conflict`, quarantine both records, disable proposal capability in that process, and emit restricted integrity audit.

Eviction is deterministic LRU by successful access sequence with digest ascending as the exact tie-break. Eviction affects performance only. Recalculation must reproduce byte-identical core response bytes.

## 16. Observability

Optional at-least-once events are:

- `comparison.validation_started`
- `comparison.bundle_verified`
- `comparison.design_verified`
- `comparison.axis_evaluated`
- `comparison.ranking_computed`
- `comparison.proposal_emitted`
- `comparison.abstained`
- `comparison.failed`

Event ID is the digest of `comparison_id`, event type, candidate manifest digest or null, axis or null, and result digest or null. Events contain digests and closed statuses only. They contain no paths, prompts, payloads, unrestricted evidence, secrets, provider bodies, Gate fields, or mutable refs.

Events are published only after the corresponding immutable stage commits in memory. Loss, duplication, delay, and reordering do not affect comparison output. Cancellation or deadline publishes at most `validation_started` and restricted `failed`; it publishes no axis-complete, ranking, proposal, abstention, or cache event.

No event consumer in this contract may invoke Gate 2, Gate 3, registry, promotion, Git, release, broker, order, public-write, or safety mutation.

## 17. Hermetic interfaces

Production interfaces are exactly:

- `AuthorizationPort.authorize_all(digests, principal) -> AuthorizationDecision`
- `ManifestStore.open_many(digests, authorization) -> ImmutableSnapshot`
- `ImmutableSnapshot.read_manifest(digest, max_bytes) -> bytes`
- `ImmutableSnapshot.read_member(manifest_digest, logical_name, max_bytes) -> bytes`
- `PolicyRegistry.require_policy_set(id, digest, deployment_mode) -> PolicySetV1`
- `BundleVerifier.verify(snapshot, policy, limits, cancellation) -> VerifiedCandidateGroups`
- `OriginVerifier.classify(groups, policy) -> OriginEvidenceV1`
- `DesignValidator.validate(groups, policy) -> ComparisonDesignV1`
- `ObservationReader.read_verified_member(...) -> typed rows`
- `MetricEvaluator.evaluate(series, trades, policy) -> MetricVectorV1`
- `RegimeAxis.evaluate(design, groups, policy) -> CrossRegimeResultV1[]`
- `CostAxis.evaluate(design, groups, policy) -> CostSensitivityResultV1[]`
- `CapacityAxis.evaluate(design, groups, policy) -> CapacityResultV1[]`
- `RankingEngine.rank(axis_results, policy) -> RankingRowV1[]|Abstention`
- `ResultCache.get/put_if_absent`
- `EventSink.publish`
- `MonotonicClock.now()`
- `CancellationToken.raise_if_cancelled()`

The production dependency graph contains no Gate, approval, promotion, candidate mutation, Git, subprocess, provider network, market-data network, broker, order, release, public-write, or safety-flag port. Market observations are read only from the authorized immutable snapshot.

## 18. Resource and concurrency behavior

A process admits at most four executing comparisons and 32 queued comparisons. Admission is decided before authorization and before any manifest, member, or cache access. Additional work returns HTTP 429 `comparison_overloaded`, `application/problem+json`, and an integer `Retry-After` header computed from the operations policy's fixed overload retry value; it contains no artifact identity. Queue order is FIFO by authenticated admission sequence; queue wait consumes the 30,000 ms deadline and does not affect result identity.

Each comparison receives isolated parser state, decimal context, temporary directory, and cancellation token. Temporary files use a process-private directory, mode `0700`; files are regular files only, never followed through symlinks or hard links, and are removed on all exits.

V1 bundles are not general archives. The immutable store exposes named member objects. ZIP, TAR, nested archive, compressed member, symlink, hard link, device, FIFO, socket, sparse file, and path traversal are rejected. This removes archive-bomb and extraction ambiguity rather than attempting to estimate it.

Memory use must remain below 1 GiB per comparison. Readers stream rows and retain only bounded axis accumulators plus the required aligned series. Crossing the limit cancels the operation with `resource_limit_exceeded`; it does not swap, truncate, or sample.

## 19. Required tests

### 19.1 Schema and canonicalization

- Golden Python/TypeScript vectors for every schema and digest.
- Duplicate keys, unknown fields, wrong versions, invalid UTF-8/NFC, floats, NaN, Infinity, negative zero, integer overflow, decimal exponent, unsafe names, ordering, and self-digest regressions.
- Manifest exact-byte canonicality and member size/digest verification.
- Links, special files, nested archives, compression, traversal, oversized manifests/members/rows/timestamps, parser depth, and aggregate limits.

### 19.2 Authorization and snapshots

- Missing versus unauthorized versus hidden versus archived artifacts produce indistinguishable public 404 bodies and header sets.
- All digests are authorized before artifact-specific publication or cache lookup.
- Cache cannot leak result existence.
- Snapshot mutation at every manifest/member boundary returns no comparison.
- Recovery always reuses exact digests and never substitutes latest, path, filename, candidate ID, or Run ID.

### 19.3 Producer and origin

- Complete allowlisted real chain with valid signatures.
- Provider-name-only spoof, declared-real sample, fixture marker, synthetic marker, unknown producer, dirty revision seal, bad signature, revoked key, revoked commit, config mismatch, digest mismatch, expired coverage, legacy wrapper, and post-hoc wrapping.
- Production accepts only all-real; sample accepts only all-sample; test accepts only all-synthetic; every mixed combination fails.
- Current HQA summary receipt, one-run experiment receipt, empty folds, stale artifact path, and float-only metrics fail `producer_evidence_incomplete`.

### 19.4 Candidate groups and design

- Group digest, member ordering, duplicate roles, bundle overlap, strategy mismatch, and candidate mismatch.
- Each fixed dimension varied one at a time and rejected.
- Candidate strategy difference across groups remains legal.
- Only cost-owned fields vary across cost scenarios.
- Exact timestamp equality; timezone, DST, calendar, window, universe, adjustment, observation index, and benchmark binding.
- Request permutations and physical relocation yield identical identities and response bytes.

### 19.5 Metrics and axes

- Golden metric vectors matching `metrics-daily-v1`, including existing Platform zero-return behavior where zero mean and zero variance produce Sharpe zero.
- Positive/negative/zero returns, nonpositive equity, zero variance with nonzero mean, drawdown, turnover, annualization, signed zero, rounding boundaries, large bounded decimals, and summary mismatch.
- Regime lookback, threshold equality, closed label order, unknown count, minimum observations, and all four regime formulas.
- Cost grid role/parameter binding, commission/slippage exact sum, slopes, degradation, break-even equality/interpolation, nonmonotonic limitation, and unsupported cost components.
- Capacity is always unavailable under V1 despite turnover, position constraints, or partial fills. A capacity bundle presented to the disabled policy cannot activate it.

### 19.6 Ranking and response

- Ordered-key direction for every key, exact null behavior, exact ties, digest tie-break, consecutive ranks, and permutation invariance.
- One incomplete required candidate-axis pair empties the entire ranking and abstains.
- Capacity unavailability alone does not block V1 ranking.
- Proposal and abstention wording are byte-exact.
- Response contains no mutable path, Gate field, mutation URL, command, approval, registration, promotion, release, execution, or trading field.
- Feeding the complete response to every existing Gate 1, Gate 2, Gate 3, candidate mutation, and promotion schema fails strict validation.
- Dependency spies prove zero calls to every forbidden port.

### 19.7 Cancellation, deadline, cache, and events

- Cancellation and deadline before/after every required boundary produce no partial response, completed cache entry, ranking, proposal, or abstention event.
- Concurrent identical requests produce one byte-identical cache value.
- Forced same-ID/different-byte cache conflict quarantines and disables proposal in process.
- Cache eviction and cold recomputation preserve bytes.
- Event duplication, loss, delay, and reordering do not alter output.
- Resource saturation rejects before artifact access.

### 19.8 Compatibility and safety

- Existing `/api/backtests` and `/api/experiments` request/response snapshots remain byte-compatible.
- Existing Gate 2 exact caller-supplied candidate ID/digest/pending-status/note CAS remains unchanged.
- Existing Gate 3 preparation remains unchanged.
- No comparison input or output mutates `kill_switch`, `live_trading_enabled`, `release_authorized`, public-write defaults, orders, Runs, Tasks, Attempts, Commands, candidates, approvals, Git, or releases.
- Production binary cannot load sample or test stores; sample binary cannot load production store or Gate clients; test role cannot start in a deployed environment.

## 20. Activation and rollback

Activation gates are independent and fail closed:

1. **Schema gate:** strict codecs, canonicalization, all golden vectors, and resource-limit tests pass in Python and TypeScript.
2. **Evidence-reader gate:** immutable snapshot, external manifest identity, member verification, authorization non-leakage, cancellation, and deadline tests pass.
3. **Producer gate:** a newly committed Platform producer emits complete V1 bundles. Legacy artifacts remain ineligible.
4. **Origin gate:** issuer keys, providers, repositories, producer commits, acquisition commits/configs, build policies, revocation data, and signatures are sealed in `origin-real-v1`.
5. **Design gate:** every fixed and controlled dimension predicate has a golden accept/reject case.
6. **Metric gate:** recomputation agrees with producer summaries within the fixed tolerance and all formula vectors pass.
7. **Axis gates:** each axis is independently `disabled`, `validate_only`, or `proposal_enabled`. Cross-regime and cost move through all three states. Capacity remains `disabled` for V1.
8. **Ranking gate:** ranking stays disabled until both required axes are proposal-enabled and whole-comparison abstention tests pass.
9. **Proposal gate:** production-only capability `comparison_proposal_v1` is enabled only after Gate non-handoff tests and dependency spies pass.
10. **Isolation gate:** real, sample, and test compositions prove store, credential, key, cache, and process separation.
11. **Operational gate:** concurrency, queue, CPU deadline, memory, byte, row, cache, and cancellation canaries pass.
12. **Revision gate:** activation manifest records exact clean committed producer and reader repository URLs, commits, source-tree digests, dependency-lock digests, policy digests, test receipt digests, and build artifacts. Dirty working-tree bytes cannot support activation.

Rollout order is evidence reader in validate-only mode, producer shadow generation, real-origin validation, design validation, metric shadow recomputation, cross-regime validate-only, cost validate-only, ranking shadow with response suppressed, private authorized proposal canary, then production read exposure.

Rollback before any proposal disables the affected capability. After proposal activation, rollback disables new proposal responses while retaining exact readers needed to replay existing content-addressed responses. Cache deletion is always safe because cache is non-authoritative. Policy, manifest, comparison, and response history is never rewritten to simulate rollback.

## 21. UI contract

The UI renders only response fields from an authorized current read. It displays the verified origin label persistently. Sample and test modes never visually resemble production proposal readiness.

A proposal view displays rank, exact candidate manifest digest, evidence-set digest, policy ID/digest, axes, limitations, and the exact proposal statement. It must use language equivalent to “proposed for independent manual review,” never “winner,” “approved,” “selected for deployment,” or “ready to trade.”

The UI provides no approve/reject button, mutation call, prefilled Gate form, auto-submit callback, or copyable Gate command from comparison data. Navigation to candidate review is unbound and forces the independent review surface to select, load, and display exact candidate bytes before the human enters a note and decision.

An abstention displays every closed reason and no candidate emphasis. Capacity always displays `Unavailable: capacity evidence missing` under V1; it is not inferred from turnover or constraints.

## 22. Explicit non-goals and standing safety assertions

Contract 3 does not:

- add public, browser, or chat mutation routes;
- approve or reject candidates;
- satisfy Gate 1, Gate 2, or Gate 3;
- register, promote, release, commit, merge, or push anything;
- submit, cancel, replace, or modify an order;
- call a broker or live market-data provider;
- treat origin declaration, provider name, successful Run, budget status, turnover, constraints, or partial fills as stronger evidence than specified;
- expose prompts, payload bodies, reasoning, tool output, secrets, provider bodies, unrestricted evidence bodies, mutable paths, or hidden artifact existence;
- infer Task, Attempt, Run, Command, candidate, approval, promotion, release, or trading state from comparison output.

Standing assertions remain unchanged:

- `kill_switch=true`;
- `live_trading_enabled=false`;
- public write standing default OFF;
- `release_authorized=false`.

Any implementation that requires weakening one of these assertions is outside Contract 3 and must not activate.
