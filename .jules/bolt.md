# Bolt's Journal - orange-translator

## 2025-05-14 - Bilingual Pipeline Parallelization
**Learning:** The previous implementation processed translation batches within a chapter sequentially. This was a significant bottleneck for cloud-based LLM APIs (OpenAI, DeepSeek) which can handle many concurrent requests. Even with `chapter_concurrency`, sequential batches within a chapter left a lot of performance on the table.
**Action:** Implemented `asyncio.gather` with a semaphore for batches within a chapter. This allows concurrent translation requests while maintaining control over the total number of parallel requests. Combined with a DOM insertion optimization that avoids unnecessary BeautifulSoup parsing for simple text, this makes the translation pipeline significantly faster for high-concurrency engines.
