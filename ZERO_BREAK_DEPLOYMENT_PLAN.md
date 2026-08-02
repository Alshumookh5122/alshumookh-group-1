# ALSHUMOOKH Zero-Break Deployment Plan

Date: 2026-05-11

## 1. Deployment Objective

Release enterprise upgrade changes with minimal operational risk and without breaking:

- Existing sender integrations
- Current admin access
- Current client access
- Existing payment order flows
- Existing settlement tracking

## 2. Deployment Strategy

Use a controlled single-release approach:

1. Build all changes first
2. Verify all changes before push
3. Push once
4. Allow one clean production deployment
5. Run smoke tests immediately
6. Monitor logs closely

## 3. Zero-Break Rules

- Do not remove existing routes
- Do not rename sender-facing routes
- Do not force incompatible auth changes without compatibility path
- Do not introduce untested database migrations
- Do not change core payment models unless required and verified

## 4. Safe Change Categories

These changes are considered safe when verified:

- New defensive routes
- New headers
- Better validation messages
- New aliases for existing static assets
- Public hardening rules
- Documentation improvements
- Logging improvements

## 5. Medium-Risk Change Categories

These require explicit verification before deploy:

- Authentication changes
- Dashboard behavior changes
- Settlement ingest validation changes
- Webhook handling changes
- Provider integration changes

## 6. High-Risk Change Categories

These should not be deployed without special preparation:

- Database schema rewrites
- Infrastructure migration
- Secrets rotation without staged validation
- Breaking auth model changes
- Removing old payload compatibility behavior

## 7. Verification Sequence Before Push

1. Compile changed Python files
2. Review git diff
3. Check route behavior for:
   - /login
   - /health
   - /api/v1/payloads/schema
   - /api/v1/payloads/ingest
4. Check dashboard and client flow
5. Confirm static assets load

## 8. Production Deployment Sequence

1. Stage files
2. Commit once
3. Push to main
4. Wait for Render deploy start
5. Wait for startup completion
6. Run smoke tests
7. Watch logs for errors

## 9. Smoke Test List

- GET /health => 200
- GET /login => 200
- GET /favicon.ico => 200
- GET /robots.txt => 200
- GET /.well-known/security.txt => 200
- GET /api/v1/payloads/schema => 200
- POST /client/login with invalid credentials => expected failure
- GET /dashboard unauthenticated => redirect

## 10. Rollback Plan

If deployment causes instability:

1. Identify last stable commit
2. Revert to that commit
3. Push rollback
4. Verify startup and smoke tests again
5. Isolate failing change in branch before retry

## 11. Release Communication Rule

Do not notify counterparties of a new release until:

- Smoke tests pass
- Logs are stable
- Admin dashboard works
- Client workflow works
- Sender-facing schema and ingest behavior are confirmed

## 12. Final Principle

Production remains the source of truth. Every change must prove that it improves security or readiness without reducing current operational reliability.
