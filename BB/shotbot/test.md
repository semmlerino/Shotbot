
- Do NOT make assumptions, read the actual implementation. Adapt tests to the code, but keep in mind that there might be bugs or suboptimal implementations in the code.

-For new functionality or refactors, consider writing the test first. It often simplifies the logic and exposes edge cases early.
    
- **If you're changing a test because it fails, double-check it's not exposing a real bug. Don’t patch over actual issues.** 
    
- **If the implementation is suboptimal, fixing the code is on the table. Let the tests drive better design.
    
- **Start running tests early. Avoid mocking where possible. Deploy multiple agents concurrently where helpful.
- Every once in a while, assess if we use too much mocking and if this could be replaced by real implementations.
    
- **Don’t count a task as done if _any_ test is failing—even if it’s not the focus right now.** 
- Avoid type ignore if you can, only use this as a last resort.
    
- use  **sequential thinking tool** where needed.
- A timeout counts as a failure. Investigate those.
- You can research the web if you're unsure about an implementation.
- Occasionally **step back and reassess**. Avoid going deep down the wrong path, check if looking at the bigger picture would be revealing and more helpful. 
- Feel free to deploy 2 agents or more simultanously & concurrently where it helps.
    
- If coverage is sufficient, shift focus to higher-impact areas. 

-If a test is skipped, check if it really is not needed or can be fixed, otherwise delete if there is no reason to keep it.