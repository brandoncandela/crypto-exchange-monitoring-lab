# Control-tuning case study

Generated from the committed snapshot and four actual runs. This is a rejected what-if, not a production recommendation.

## Decision and fixed proposal

Baseline R03: deposit ≥ $1,000, ≥80% withdrawn within 60 minutes. Proposed: raise only the deposit floor to $50,000. This round-number materiality hypothesis is declared in code before the evaluation runs. It tests whether a smaller queue would conceal smaller review-worthy transfers. No thresholds are selected by searching evaluation labels. There is no automated tuning or training.

The original fixture is an explanatory baseline. The separate challenge set was authored with knowledge of the rules and includes misses, overlaps, benign settlements and threshold edges. It is not a blind holdout, and neither set establishes production accuracy.

## Baseline fixtures: R03

| Control | Customer precision | Customer recall | Alert precision proxy | Alerts | Missed customers |
| --- | ---: | ---: | ---: | ---: | --- |
| baseline | 2/3 (66.7%) | 2/2 (100.0%) | 2/12 (16.7%) | 12 | None |
| proposed | 1/2 (50.0%) | 1/2 (50.0%) | 1/9 (11.1%) | 9 | C-006 |

### Workload assumptions

Each dataset covers a fictional 30-day observation period. Illustrative handling assumptions: 20 minutes per R03 alert, or alternatively 45 minutes per distinct R03 customer case if alerts are consolidated. These are separate operating models, not additive, and exclude QC, sanctions specialists, information requests and rework. No FTE or real savings claim is made.

- Baseline: 12 × 20 = 240 minutes (4.00 hours) per-alert review; alternatively 3 × 45 = 135 minutes (2.25 hours) consolidated review.
- Proposed: 9 × 20 = 180 minutes (3.00 hours) per-alert review; alternatively 2 × 45 = 90 minutes (1.50 hours) consolidated review.

## Evaluation fixtures: R03

| Control | Customer precision | Customer recall | Alert precision proxy | Alerts | Missed customers |
| --- | ---: | ---: | ---: | ---: | --- |
| baseline | 3/5 (60.0%) | 3/6 (50.0%) | 3/5 (60.0%) | 5 | C-002, C-003, C-004 |
| proposed | 1/2 (50.0%) | 1/6 (16.7%) | 1/2 (50.0%) | 2 | C-001, C-002, C-003, C-004, C-008 |

### Workload assumptions

Each dataset covers a fictional 30-day observation period. Illustrative handling assumptions: 20 minutes per R03 alert, or alternatively 45 minutes per distinct R03 customer case if alerts are consolidated. These are separate operating models, not additive, and exclude QC, sanctions specialists, information requests and rework. No FTE or real savings claim is made.

- Baseline: 5 × 20 = 100 minutes (1.67 hours) per-alert review; alternatively 5 × 45 = 225 minutes (3.75 hours) consolidated review.
- Proposed: 2 × 20 = 40 minutes (0.67 hours) per-alert review; alternatively 2 × 45 = 90 minutes (1.50 hours) consolidated review.

## Recommendation, approval and rollback

Do not approve the deposit-floor increase on this evidence: it removes review-worthy customers while high-value benign OTC settlement still alerts. Investigate case consolidation and documented customer context instead of blanket OTC exemptions; the evaluation includes review-worthy OTC activity.

Before any production change: the monitoring owner, BSA/AML compliance and independent validation/QC must agree scope, representative adjudicated data, risk acceptance and acceptance criteria. Engineering must reconcile input volumes and implement versioned configuration with an approved release record. These are proposed governance requirements, not approvals already obtained.

Pilot in shadow mode. Monitor alert volume and distinct cases by segment, amount and rule; sample suppressed activity with independent review; track complaints, escalations, SAR outcomes, data freshness and below-threshold activity. Define quantitative tolerances with the owners before launch. Any confirmed material miss, data defect or unapproved risk change pauses the pilot. Restore the previous $1,000 configuration, re-run the affected observation window and reconcile/review the suppressed queue. Do not remove existing cases or bypass direct sanctions controls.

## Metric definitions

Customer precision = correctly flagged customer–typology pairs / all flagged pairs for that rule.
Customer recall = correctly flagged pairs / all authored positive pairs for that rule.
Alert precision proxy = alerts on customers labeled for that rule / all alerts from that rule.
Repeated alerts count repeatedly in the alert denominator, but once per customer in the customer denominator.
Alert recall is unavailable: there is no exhaustive event-level reference set or count of missed events.
A zero denominator is N/A, not 0% or 100%. All labels express fictional review-worthiness, not confirmed crime.
Cross-rule counts can overlap; do not add customer counts to estimate distinct cases.
