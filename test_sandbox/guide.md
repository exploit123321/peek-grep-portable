# Peek & Grep Workstation Deployment Guide

Welcome to the **Peek & Grep** local desktop search and inspection documentation. This guide details setup procedures, performance characteristics, and system health checks.

## Architecture Overview

Peek & Grep utilizes SQLite FTS5 for sub-50ms full-text retrieval, pairing asynchronous filesystem monitoring with a zero-latency spacebar Quick Look preview modal.

| Component | Technology | Primary Role |
| :--- | :--- | :--- |
| **Storage Engine** | SQLite3 + FTS5 | Indexed metadata & unicode61 inverted index |
| **Backend API** | FastAPI + Uvicorn | High-throughput REST API with CORS |
| **Event Watcher** | Watchdog | Asynchronous file mutations dispatcher |
| **Visual HUD** | React 19 + Tailwind | Keyboard-first command palette & Quick Look modal |

## Implementation Checklist

- [x] Configure SQLite WAL mode for non-blocking concurrent reads
- [x] Tokenize search queries to prevent FTS5 syntax exceptions
- [x] Mount PrismJS syntax highlighters for Python, TypeScript, and SQL
- [ ] Benchmark crawl throughput on 100,000+ files
- [ ] Implement fuzzy phonetic matching for misspelling tolerance

## Sample Configuration

```json
{
  "search_roots": ["./test_sandbox"],
  "ignore_patterns": [".git", "node_modules", ".venv"],
  "max_file_size_mb": 10,
  "telemetry_enabled": false
}
```

> **Pro Tip:** Press `Space` at any time to inspect file contents without losing your active search cursor. Press `Enter` to launch the native desktop editor.
