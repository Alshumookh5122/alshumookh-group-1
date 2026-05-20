# ALSHUMOOKH Enterprise Upgrade Master Plan

Date: 2026-05-11
Environment: Production
Primary Domain: https://api.alshumookh-pay.com

## 1. Objective

Upgrade the current ALSHUMOOKH platform from a stable operational settlement system into an enterprise-style settlement receiver suitable for high-value technical onboarding, without breaking current production workflows.

The upgrade must preserve:

- Existing admin access
- Existing client access
- Existing payment and order flows
- Existing payload ingestion and blockchain verification features
- Existing MoonPay and dashboard functionality

## 2. Current Production Baseline

The current platform already provides:

- Production domain with HTTPS
- Admin dashboard
- Client portal
- Settlement payload ingestion
- JSON schema endpoint
- Alchemy and RPC verification support
- Audit trail and event logging
- Public surface hardening
- Session controls and login protection
- Sender-facing technical documentation

This means the project is not a rebuild. It is a controlled hardening and operational maturity program.

## 3. Upgrade Principle

All work must follow these rules:

1. No uncontrolled production edits
2. No breaking changes to existing sender flows
3. Backward compatibility wherever possible
4. Single controlled deployment after verification
5. Rollback path prepared before production release

## 4. Scope of the Upgrade

### A. Security Maturity

- Tighten public route protections
- Strengthen API authentication posture
- Improve bot and scanner resistance
- Prepare strict sender onboarding controls
- Improve operational security headers and request handling

### B. Counterparty Readiness

- Standardize sender onboarding requirements
- Finalize machine-readable API guidance
- Formalize sender-specific access model
- Improve request validation and exception clarity
- Strengthen technical evidence package for counterparties

### C. Operational Readiness

- Improve monitoring and logging clarity
- Improve reconciliation visibility
- Improve admin visibility for payloads and settlements
- Improve incident traceability

### D. Infrastructure Readiness

- Prepare for dedicated hosting posture
- Prepare WAF and Cloudflare layer
- Prepare migration-safe deployment sequence
- Prepare secret and environment validation

## 5. Work Phases

### Phase A - Planning and Freeze

Goal:
Define all changes before code implementation.

Deliverables:

- Enterprise upgrade master plan
- Release checklist
- Zero-break deployment plan
- Change inventory

### Phase B - Safe Build

Goal:
Implement all approved changes without touching production behavior unnecessarily.

Deliverables:

- Hardened code changes
- Configuration additions
- UI and UX improvements
- Logging and audit improvements

### Phase C - Verification

Goal:
Validate the full system before release.

Deliverables:

- Functional tests
- Regression review
- Sender flow review
- Dashboard review
- Authentication review

### Phase D - Controlled Deployment

Goal:
Deploy once with a monitored production rollout.

Deliverables:

- Clean commit and push
- Single deployment event
- Post-deploy smoke tests
- Monitoring review

## 6. High-Priority Gaps to Close

The following items are the most important to close in this upgrade cycle:

1. Better public-edge protection
2. Stricter sender authentication posture
3. Cleaner operational evidence for counterparties
4. Better dashboard visibility for settlement activity
5. Safer deployment discipline

## 7. Explicit Non-Goals for This Cycle

The following are not part of this immediate code cycle:

- Formal ISO 27001 certification
- Formal SOC 2 certification
- PCI certification
- Legal or regulatory licensing
- Full banking-grade compliance claims

These will follow after the technical platform is fully stabilized and documented.

## 8. Success Criteria

This upgrade cycle is successful if:

- Production stays operational
- Current senders are not broken
- Admin and client workflows remain functional
- Payload ingestion remains stable
- Security posture is visibly stronger
- Documentation is clearer and more credible
- Production deployment can be completed with low risk

## 9. Final Target State for This Cycle

At the end of this cycle, the platform should be describable as:

"An operational enterprise-style settlement platform with hardened public access, structured sender onboarding, secure payload ingestion, blockchain verification, operational audit visibility, and production-safe deployment controls."
