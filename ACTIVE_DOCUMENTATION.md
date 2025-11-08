# ShotBot Active Documentation Index

**Last Updated:** 2025-11-08
**Status:** Current and maintained

---

## 🎯 Start Here

### For New Developers
1. **[README.md](./README.md)** - Project overview
2. **[CLAUDE.md](./CLAUDE.md)** - Development guidelines and architecture
3. **[UNIFIED_TESTING_V2.MD](./UNIFIED_TESTING_V2.MD)** - Testing best practices

### For Testing Work
1. **[UNIFIED_TESTING_V2.MD](./UNIFIED_TESTING_V2.MD)** - **CANONICAL TESTING GUIDE**
   - Quick start commands
   - 5 Basic Qt Testing Hygiene Rules
   - Test isolation patterns
   - Parallel execution guidance
   - Qt-specific testing patterns
   - Debugging workflows

2. **[CONFTEST_IMPROVEMENTS_SUMMARY.md](./CONFTEST_IMPROVEMENTS_SUMMARY.md)** - Recent improvements (2025-11-08)
   - 14 critical conftest.py improvements
   - pyproject.toml updates
   - Performance optimizations

3. **[docs/CONFTEST_IMPROVEMENTS_2025-11-08.md](./docs/CONFTEST_IMPROVEMENTS_2025-11-08.md)** - Detailed changelog

---

## 📚 Active Documentation

### Project Core
- **[README.md](./README.md)** - Main project overview
- **[CLAUDE.md](./CLAUDE.md)** - Primary development guidelines (architecture, patterns, commands)
- **[SECURITY_CONTEXT.md](./SECURITY_CONTEXT.md)** - Security posture (isolated VFX network)
- **[KNOWN_ISSUES.md](./KNOWN_ISSUES.md)** - Current known issues
- **[PERFORMANCE_OPTIMIZATIONS.md](./PERFORMANCE_OPTIMIZATIONS.md)** - Performance guidance

### Testing & Quality
- **[UNIFIED_TESTING_V2.MD](./UNIFIED_TESTING_V2.MD)** - **PRIMARY TESTING GUIDE** (replaces all other testing docs)
- **[CONFTEST_IMPROVEMENTS_SUMMARY.md](./CONFTEST_IMPROVEMENTS_SUMMARY.md)** - Latest improvements (2025-11-08)

### Deployment System
- **[POST_COMMIT_BUNDLE_GUIDE.md](./POST_COMMIT_BUNDLE_GUIDE.md)** - Automated bundle system
- **[AUTO_PUSH_SYSTEM.md](./AUTO_PUSH_SYSTEM.md)** - Auto-push to encoded-releases
- **[AUTO_PUSH_TROUBLESHOOTING_DO_NOT_DELETE.md](./AUTO_PUSH_TROUBLESHOOTING_DO_NOT_DELETE.md)** - **CRITICAL**

---

## 📁 Feature Documentation (`docs/`)

### Active Features
- **[docs/CUSTOM_LAUNCHER_DOCUMENTATION.md](./docs/CUSTOM_LAUNCHER_DOCUMENTATION.md)** - Launcher system
- **[docs/NUKE_PLATE_WORKFLOW.md](./docs/NUKE_PLATE_WORKFLOW.md)** - Nuke plate workflow
- **[docs/SIMPLE_VS_COMPLEX_NUKE_LAUNCH.md](./docs/SIMPLE_VS_COMPLEX_NUKE_LAUNCH.md)** - Launch patterns
- **[docs/QT_WARNING_DETECTION.md](./docs/QT_WARNING_DETECTION.md)** - Warning detection

### Recent Improvements
- **[docs/CONFTEST_IMPROVEMENTS_2025-11-08.md](./docs/CONFTEST_IMPROVEMENTS_2025-11-08.md)** - Detailed improvement log

### Refactoring History
- **[docs/refactoring_history/APPLICATION_IMPROVEMENT_PLAN.md](./docs/refactoring_history/APPLICATION_IMPROVEMENT_PLAN.md)**
- **[docs/refactoring_history/COMPREHENSIVE_AGENT_REPORT.md](./docs/refactoring_history/COMPREHENSIVE_AGENT_REPORT.md)**
- **[docs/refactoring_history/TEST_REFACTORING_SUMMARY.md](./docs/refactoring_history/TEST_REFACTORING_SUMMARY.md)**

---

## 🗂️ Archived Documentation

**See [archive/ARCHIVE_INDEX.md](./archive/ARCHIVE_INDEX.md) for complete listing**

### Recent Archive (2025-11-08)
**Reason:** Comprehensive test configuration improvements completed

**Archived Categories:**
- **`/audits/`** - 21 completed audit reports (issues now fixed)
- **`/quick-references/`** - 3 quick refs (consolidated into UNIFIED_TESTING_V2.MD)
- **`/testing-guides/`** - 4 testing guides (superseded by UNIFIED_TESTING_V2.MD)

**Total Archived:** 28 documents

**Key Archived Docs:**
- All Qt audit reports → Fixes implemented
- All test isolation audits → Fixes implemented
- All sync/cleanup audits → Fixes implemented
- WSL-TESTING.md → Covered in UNIFIED_TESTING_V2.MD
- XDIST_REMEDIATION_ROADMAP.md → All phases completed ✅
- QT_QUICK_REFERENCE.md → Content in UNIFIED_TESTING_V2.MD
- STATE_ISOLATION_QUICK_REFERENCE.md → Content in UNIFIED_TESTING_V2.MD

---

## 🚀 Quick Navigation

### Starting New Work
```bash
# 1. Understand the project
cat README.md
cat CLAUDE.md

# 2. Set up testing
cat UNIFIED_TESTING_V2.MD  # Read the 5 hygiene rules!

# 3. Run tests
~/.local/bin/uv run pytest tests/ -n 2  # Parallel (recommended)
~/.local/bin/uv run pytest tests/       # Serial (if debugging)
```

### Understanding the Codebase
1. **[README.md](./README.md)** - High-level overview, deployment
2. **[CLAUDE.md](./CLAUDE.md)** - Architecture, patterns, singleton resets
3. **[SECURITY_CONTEXT.md](./SECURITY_CONTEXT.md)** - VFX network context

### Working with Tests
1. **[UNIFIED_TESTING_V2.MD](./UNIFIED_TESTING_V2.MD)** - **READ THIS FIRST**
   - Section 1: Quick Start (commands)
   - Section 2: 5 Basic Qt Testing Hygiene Rules (essential)
   - Section 3: Test Isolation & Parallel Execution
   - Section 4: Qt-Specific Patterns
   - Section 5: Debugging Workflows

2. **[CONFTEST_IMPROVEMENTS_SUMMARY.md](./CONFTEST_IMPROVEMENTS_SUMMARY.md)** - Recent fixes

### Deployment
1. **[POST_COMMIT_BUNDLE_GUIDE.md](./POST_COMMIT_BUNDLE_GUIDE.md)** - How bundles work
2. **[AUTO_PUSH_SYSTEM.md](./AUTO_PUSH_SYSTEM.md)** - Auto-push system
3. Commit → Bundle auto-created → Auto-pushed to `encoded-releases` branch

---

## 📝 Document Status Summary

### ✅ Active Documents (17 total)
- **Core:** 5 docs (README, CLAUDE, SECURITY, KNOWN_ISSUES, PERFORMANCE)
- **Testing:** 2 docs (UNIFIED_TESTING_V2.MD, CONFTEST_IMPROVEMENTS_SUMMARY.md)
- **Deployment:** 3 docs (POST_COMMIT, AUTO_PUSH, TROUBLESHOOTING)
- **Features:** 4 docs (LAUNCHER, NUKE_PLATE, LAUNCH_PATTERNS, WARNING_DETECTION)
- **History:** 3 docs (APPLICATION_PLAN, AGENT_REPORT, TEST_REFACTORING)
- **Recent:** 1 doc (CONFTEST_IMPROVEMENTS_2025-11-08.md)

### 🗂️ Archived Documents (74 total)
- **Previous archive (2025-11-01):** 46 docs (reviews, old plans, old analysis)
- **Recent archive (2025-11-08):** 28 docs (audits, quick refs, testing guides)
- **See:** [archive/ARCHIVE_INDEX.md](./archive/ARCHIVE_INDEX.md)

### 📊 Documentation Cleanup Progress
- **Before (2025-10-30):** 120+ documents
- **After cleanup (2025-11-01):** 61 documents (-59)
- **After recent archive (2025-11-08):** 33 documents (-28)
- **Total reduction:** 87 documents (73% reduction)

---

## 🔄 Maintenance Guidelines

### When to Archive
- Document superseded by consolidated guide (e.g., → UNIFIED_TESTING_V2.MD)
- Audit complete and fixes implemented
- Historical reference value only

### When to Keep Active
- Current implementation guidance
- Feature documentation for active features
- Troubleshooting guides (AUTO_PUSH_TROUBLESHOOTING)
- Architecture and context (CLAUDE.md, SECURITY_CONTEXT.md)

### Archive Locations
- Audits/reviews → `archive/audits/`
- Quick references → `archive/quick-references/`
- Testing guides → `archive/testing-guides/`
- Old plans → `archive/old-plans-YYYY-MM-DD/`

---

## 🎓 Recommended Reading Order

### Day 1: Project Understanding
1. README.md (15 min)
2. CLAUDE.md (30 min)
3. SECURITY_CONTEXT.md (5 min)

### Day 2: Testing Setup
1. UNIFIED_TESTING_V2.MD - Sections 1-2 (30 min)
2. Run test suite: `~/.local/bin/uv run pytest tests/ -n 2`
3. UNIFIED_TESTING_V2.MD - Section 3 (20 min)

### Day 3: Deep Dive
1. UNIFIED_TESTING_V2.MD - Sections 4-5 (40 min)
2. CONFTEST_IMPROVEMENTS_SUMMARY.md (10 min)
3. Feature docs relevant to your work

### Ongoing Reference
- UNIFIED_TESTING_V2.MD - 5 hygiene rules (memorize these!)
- CLAUDE.md - Singleton reset pattern
- AUTO_PUSH_TROUBLESHOOTING_DO_NOT_DELETE.md - When git hooks fail

---

**Last Major Archive:** 2025-11-08
**Total Active Docs:** 17 (down from 120+)
**Archive Status:** 74 documents preserved for historical reference
**Next Review:** After next major implementation phase
