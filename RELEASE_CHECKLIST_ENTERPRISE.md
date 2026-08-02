# ALSHUMOOKH Enterprise Release Checklist

Date: 2026-05-11

## 1. Pre-Build Review

- [ ] Confirm scope of upgrade
- [ ] Confirm no destructive database change is planned
- [ ] Confirm no sender-facing endpoint will be removed
- [ ] Confirm admin login flow remains available
- [ ] Confirm current production domain remains unchanged

## 2. Security Controls

- [ ] Public route hardening reviewed
- [ ] Suspicious probe handling active
- [ ] Rate limiting reviewed for admin, client, and public paths
- [ ] Security headers active
- [ ] Noindex headers on sensitive pages active
- [ ] Sender authentication posture reviewed

## 3. Sender / API Controls

- [ ] Payload schema endpoint working
- [ ] Payload ingest endpoint working
- [ ] Invalid method returns expected response
- [ ] Invalid auth returns expected response
- [ ] Sender-facing error messages are clear
- [ ] Required fields and validation behavior documented

## 4. Client and Admin UX

- [ ] Admin login works
- [ ] Client login works
- [ ] Client registration works with valid input
- [ ] Registration errors are readable
- [ ] Dashboard loads correctly
- [ ] Client portal loads correctly
- [ ] Payment cards and transaction list load correctly

## 5. Payments and Settlement

- [ ] MoonPay flow not broken
- [ ] Direct payment flow not broken
- [ ] Orders list still loads
- [ ] Payload dashboard still loads
- [ ] Alchemy events still load
- [ ] Audit logs still load

## 6. Static and Public Assets

- [ ] favicon.ico returns 200
- [ ] favicon.png returns 200
- [ ] apple-touch-icon.png returns 200
- [ ] apple-touch-icon-precomposed.png returns 200
- [ ] robots.txt returns 200
- [ ] security.txt returns 200

## 7. Production Smoke Tests

- [ ] GET / returns redirect as expected
- [ ] GET /login returns 200
- [ ] GET /health returns 200
- [ ] GET /api/v1/payloads/schema returns 200
- [ ] Protected endpoints deny unauthenticated access correctly

## 8. Deployment Readiness

- [ ] Changes reviewed in git diff
- [ ] Files staged cleanly
- [ ] Commit message prepared
- [ ] Push target confirmed
- [ ] Render auto-deploy expected

## 9. Post-Deploy Verification

- [ ] Deployment finished successfully
- [ ] Application startup complete in logs
- [ ] Domain responds correctly
- [ ] No new critical errors in logs
- [ ] Admin dashboard accessible
- [ ] Client portal accessible

## 10. Sign-Off

- [ ] Technical review complete
- [ ] Production behavior confirmed
- [ ] Safe to notify counterparties
