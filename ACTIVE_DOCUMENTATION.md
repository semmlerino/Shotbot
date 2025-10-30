# ShotBot Active Documentation Index

**Last Updated:** 2025-10-30
**Status:** Current and maintained

---

## 🎯 Primary Documents (Implementation)

### For Remediation Work (START HERE)

1. **[REMEDIATION_README.md](./REMEDIATION_README.md)** 📖
   - Quick start guide for remediation
   - Overview of what's being fixed
   - Success criteria
   - **READ THIS FIRST**

2. **[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)** ⭐
   - Complete 4-phase remediation plan
   - 12 tasks with detailed code examples
   - Agent-based workflow
   - Success metrics and verification
   - **PRIMARY IMPLEMENTATION GUIDE**

3. **[IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md)** ✅
   - Task-by-task tracking
   - Review sign-offs
   - Progress monitoring
   - Git commit verification
   - **TRACK YOUR PROGRESS HERE**

---

## 📚 Reference Documentation (Keep)

### Project Documentation
- **[README.md](./README.md)** - Main project overview
- **[CLAUDE.md](./CLAUDE.md)** - Instructions for Claude Code
- **[SECURITY_CONTEXT.md](./SECURITY_CONTEXT.md)** - Security context (VFX network)
- **[KNOWN_ISSUES.md](./KNOWN_ISSUES.md)** - Current known issues

### Development Guides
- **[TESTING.md](./TESTING.md)** - Testing guide and commands
- **[TESTING_BEST_PRACTICES.md](./TESTING_BEST_PRACTICES.md)** - Testing standards
- **[QT_CONCURRENCY_BEST_PRACTICES.md](./QT_CONCURRENCY_BEST_PRACTICES.md)** - Qt threading guide
- **[WSL-TESTING.md](./WSL-TESTING.md)** - WSL-specific testing info

### Infrastructure
- **[POST_COMMIT_BUNDLE_GUIDE.md](./POST_COMMIT_BUNDLE_GUIDE.md)** - Git hook documentation
- **[AUDIT_INDEX.md](./AUDIT_INDEX.md)** - Audit tracking

---

## 📁 Feature Documentation (docs/)

### Active Feature Docs
- **[docs/CUSTOM_LAUNCHER_DOCUMENTATION.md](./docs/CUSTOM_LAUNCHER_DOCUMENTATION.md)**
  - Custom launcher system
  - Configuration and usage

- **[docs/NUKE_PLATE_WORKFLOW.md](./docs/NUKE_PLATE_WORKFLOW.md)**
  - Nuke plate-based workflow
  - Plate discovery and versioning

- **[docs/SIMPLE_VS_COMPLEX_NUKE_LAUNCH.md](./docs/SIMPLE_VS_COMPLEX_NUKE_LAUNCH.md)**
  - Comparison of Nuke launch approaches
  - Implementation details

- **[docs/QT_WARNING_DETECTION.md](./docs/QT_WARNING_DETECTION.md)**
  - Qt warning detection system
  - Configuration and monitoring

---

## 🗂️ Archived Documents (Reference Only)

### Previous Analysis (2025-10-30)
- **[docs/archive/analysis-2025-10-30/](./docs/archive/analysis-2025-10-30/)**
  - ARCHITECTURE_REVIEW.md
  - ARCHITECTURE_REVIEW_SUMMARY.txt
  - **Replaced by:** IMPLEMENTATION_PLAN.md

### Previous Plans (2025-10-30)
- **[docs/archive/old-plans-2025-10-30/](./docs/archive/old-plans-2025-10-30/)**
  - IMPLEMENTATION_PLAN_AMENDED.md
  - INCREMENTAL_CACHING_PLAN.md
  - VERIFICATION_CHECKLIST.md
  - **Replaced by:** IMPLEMENTATION_PLAN.md + IMPLEMENTATION_CHECKLIST.md

### Previous Analysis Documents (2025-10-30)
- **[docs/archive/old-analysis-2025-10-30/](./docs/archive/old-analysis-2025-10-30/)**
  - AGENT_REVIEW_VERIFICATION.md
  - AGENT_SCOPE_ANALYSIS.md
  - CONFIG_VALIDATION.md
  - INCREMENTAL_CACHING.md
  - NUKE_LAUNCHER_SIMPLIFICATION.md
  - THUMBNAIL_CACHE_IMPLEMENTATION_PLAN.md
  - IMPLEMENTATION_COMPLETE.md
  - TEST_SUITE_ENHANCEMENT_IMPLEMENTATION.md
  - TEST_SUITE_IMPROVEMENTS_2025.md
  - **Replaced by:** Comprehensive 6-agent analysis → IMPLEMENTATION_PLAN.md

---

## 📊 Test Documentation (tests/)

### Active Test Docs
- **[tests/README.md](./tests/README.md)** - Test suite overview
- **[tests/INTEGRATION_TEST_SUMMARY.md](./tests/INTEGRATION_TEST_SUMMARY.md)** - Integration tests
- **[tests/KEY_FEATURES_INTEGRATION_TESTS.md](./tests/KEY_FEATURES_INTEGRATION_TESTS.md)** - Feature tests
- **[tests/RUN_INTEGRATION_TESTS.md](./tests/RUN_INTEGRATION_TESTS.md)** - How to run tests
- **[tests/TEST_IMPROVEMENTS_SUMMARY.md](./tests/TEST_IMPROVEMENTS_SUMMARY.md)** - Recent improvements
- **[tests/THREAD_SAFETY_AUDIT_SUMMARY.md](./tests/THREAD_SAFETY_AUDIT_SUMMARY.md)** - Thread safety audit
- **[tests/THREAD_SAFETY_FIXES.md](./tests/THREAD_SAFETY_FIXES.md)** - Thread safety fixes

---

## 🚀 Quick Navigation

### Starting New Work
1. Read **[REMEDIATION_README.md](./REMEDIATION_README.md)** for overview
2. Open **[IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md)** for details
3. Use **[IMPLEMENTATION_CHECKLIST.md](./IMPLEMENTATION_CHECKLIST.md)** to track progress

### Understanding the Codebase
1. Start with **[README.md](./README.md)**
2. Review **[CLAUDE.md](./CLAUDE.md)** for architecture
3. Check **[SECURITY_CONTEXT.md](./SECURITY_CONTEXT.md)** for VFX context

### Working with Tests
1. Read **[TESTING.md](./TESTING.md)** for commands
2. Check **[tests/README.md](./tests/README.md)** for test organization
3. Follow **[TESTING_BEST_PRACTICES.md](./TESTING_BEST_PRACTICES.md)**

### Qt Threading Issues
1. Read **[QT_CONCURRENCY_BEST_PRACTICES.md](./QT_CONCURRENCY_BEST_PRACTICES.md)**
2. Check **[tests/THREAD_SAFETY_AUDIT_SUMMARY.md](./tests/THREAD_SAFETY_AUDIT_SUMMARY.md)**
3. Review **[tests/THREAD_SAFETY_FIXES.md](./tests/THREAD_SAFETY_FIXES.md)**

---

## 📝 Document Status

### ✅ Current and Active (15 documents)
- 3 Primary implementation docs
- 4 Project docs
- 4 Development guides
- 4 Feature docs

### 📚 Reference (Keep) (8 documents)
- Test documentation in tests/
- Infrastructure docs

### 🗂️ Archived (Not Needed) (18 documents)
- Previous analysis → docs/archive/analysis-2025-10-30/
- Old plans → docs/archive/old-plans-2025-10-30/
- Old analysis → docs/archive/old-analysis-2025-10-30/

---

## 🔄 Maintenance

### When to Archive
- Document superseded by newer version
- Analysis complete and plan created
- Implementation finished and verified

### When to Keep
- Current implementation plans
- Active feature documentation
- Reference guides and best practices
- Project context documents

### Archive Location
- Analysis/reviews → `docs/archive/analysis-YYYY-MM-DD/`
- Old plans → `docs/archive/old-plans-YYYY-MM-DD/`
- Old analysis → `docs/archive/old-analysis-YYYY-MM-DD/`

---

**Last Archived:** 2025-10-30 (18 obsolete documents)
**Next Review:** After Phase 4 completion (update with results)
