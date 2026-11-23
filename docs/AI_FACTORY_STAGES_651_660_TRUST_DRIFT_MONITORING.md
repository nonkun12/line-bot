# AI Factory Stages 651–660: Trust Drift Monitoring

| Stage | Responsibility |
|---|---|
| 651 | Bind monitor, subject, prior trust evaluation, and policy |
| 652 | Declare bounded monitoring window and schedule coverage |
| 653 | Record typed events with ordered observation/recording timestamps |
| 654 | Bind event sources to provenance and digest declarations |
| 655 | Classify severity without inferring truth |
| 656 | Bound affected resources and claims; prohibit wildcard impact |
| 657 | Require a named owner, procedure, and reassessment deadline |
| 658 | Record containment recommendations/requests without executing them |
| 659 | Require resolution evidence for declared closure |
| 660 | Integrate a fail-closed review gate |

## Trust and action boundary

The validator consumes caller-supplied declarations only. It does not run a live
monitor, authenticate event sources, inspect source payloads, verify digests against
bytes, query revocation services, suspend trust, quarantine resources, or remediate
anything. A complete record is only structurally ready for independent review.
