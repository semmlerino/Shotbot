# Testing Guide Index

**Primary Documentation**: All testing guidance is consolidated in one place.

## Main Guide

📖 **[UNIFIED_TESTING_V2.MD](../UNIFIED_TESTING_V2.MD)** - The comprehensive testing guide

Contains everything you need:
- Quick Start (running tests)
- Test Isolation and Parallel Execution (critical for reliability)
- Testing Principles (UNIFIED_TESTING_GUIDE philosophy)
- Anti-Pattern Replacements
- Test Patterns by Category
- Debugging Workflow
- Best Practices Summary

## Supplementary Documentation

🔍 **[TEST_ISOLATION_CASE_STUDIES.md](TEST_ISOLATION_CASE_STUDIES.md)** - Deep dive into real debugging examples
- Case Study 1: QTimer Resource Leak
- Case Study 2: Global Config State Contamination  
- Case Study 3: Module-Level Cache Contamination
- Includes before/after code, timelines, and verification

## Archived Documents

📦 **[docs/archive/TESTING_BEST_PRACTICES_2025-10-31.md](archive/TESTING_BEST_PRACTICES_2025-10-31.md)**
- Archived after consolidation into UNIFIED_TESTING_V2.MD
- Kept for historical reference

## Quick Links

**Most Common Questions**:
- How do I run tests? → [UNIFIED_TESTING_V2.MD > Quick Start](../UNIFIED_TESTING_V2.MD#quick-start)
- Tests fail in parallel but pass alone? → [UNIFIED_TESTING_V2.MD > Test Isolation](../UNIFIED_TESTING_V2.MD#test-isolation-and-parallel-execution--critical)
- What are anti-patterns to avoid? → [UNIFIED_TESTING_V2.MD > Anti-Pattern Replacements](../UNIFIED_TESTING_V2.MD#anti-pattern-replacements)
- How do I debug failures? → [UNIFIED_TESTING_V2.MD > Debugging](../UNIFIED_TESTING_V2.MD#debugging-test-failures)
- Real debugging examples? → [TEST_ISOLATION_CASE_STUDIES.md](TEST_ISOLATION_CASE_STUDIES.md)

## Recent Updates

**2025-10-31**: Major consolidation
- Merged three overlapping guides into one authoritative UNIFIED_TESTING_V2.MD
- Added comprehensive Test Isolation section
- Created detailed case studies document
- Fixed 3 flaky tests with proper isolation
- All 1,975 tests now pass consistently in parallel

---

**When in doubt, start with [UNIFIED_TESTING_V2.MD](../UNIFIED_TESTING_V2.MD)**
