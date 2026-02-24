  Key principles to follow:
  1. Read actual implementations, don't make assumptions
  2. Adapt tests to code, but consider if the code has bugs
  3. Start running tests at the first opportunity.
  4. For new functionality/refactors, consider test-first approach
  5. Don't patch over real bugs - if a test fails, it might expose a real issue
  6. If implementation is suboptimal, fixing the code is on the table
  7. Use sequential thinking where needed
  8. Don't count task as done if ANY test is failing
  9. We have time, do not get overwhelmed if there are a large number of issues. Be systematic and thorough in your approach 
  10. Avoid type ignore as last resort
  11. Research using the context7 MCP if unsure
  12. Step back and reassess periodically
  13. If test is skipped, fix or delete
  14. Don't create scripts, fix systematically
  15. Timeouts/aborts are failures. Investigate those.
  16. Ensure all tests follow best practices from UNIFIED_TESTING_V2.md