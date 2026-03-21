# Product Requirement Document (PRD): Project "Native-Search"

## 1. Executive Summary
**Project Name:** Native-Search Crawler & Engine  
**Objective:** Build a high-performance, single-machine web crawler and real-time search engine from scratch using language-native networking and concurrency primitives.  
**Core Value Proposition:** To provide a transparent, efficient indexing system where search results are immediately available and updated as the crawler discovers new data, without relying on high-level third-party scraping frameworks.

---

## 2. Goals & Objectives
* **Recursive Discovery:** Successfully crawl the web starting from an origin URL up to a defined depth $k$.
* **Real-time Search:** Enable search queries while the indexer is actively running.
* **Load Management:** Implement robust back-pressure mechanisms to prevent system exhaustion.
* **Native-First:** Demonstrate architectural depth by avoiding high-level libraries (e.g., Scrapy, Beautiful Soup).

---

## 3. Functional Requirements

### 3.1. Indexer Component
| Feature | Description |
| :--- | :--- |
| **Recursive Crawling** | System must follow links from an `origin` URL to a maximum depth of $k$ hops. |
| **Uniqueness Guard** | A "Visited" set must track processed URLs to prevent infinite loops and redundant work. |
| **Back-Pressure** | Must implement a mechanism (e.g., worker pools, rate limiters, or semaphore-based throttling) to manage CPU and memory load. |
| **Native Execution** | Must use language-native HTTP clients (e.g., `net/http` in Go, `urllib` in Python) for fetching content. |

### 3.2. Searcher Component
| Feature | Description |
| :--- | :--- |
| **Live Indexing** | Search queries must be executable against the index while the crawler is actively writing new data. |
| **Output Format** | Search results must return a list of triples: `(relevant_url, origin_url, depth)`. |
| **Ranking Heuristic** | A simple relevancy algorithm (e.g., keyword frequency or title matching) to order results. |
| **Thread Safety** | Must utilize thread-safe data structures (Mutexes, Atomic counters, or Channels) to prevent race conditions during concurrent Read/Write operations. |

### 3.3. System Visibility & UI
* **Dashboard:** A real-time interface (CLI or Web) to monitor system health.
* **Metrics Tracking:**
    * Total URLs processed vs. URLs currently in the queue.
    * Current queue depth.
    * Active back-pressure/throttling status (e.g., "Throttled" vs. "Active").

---

## 4. Technical Specifications & Architecture

### 4.1. The Data Pipeline
1.  **URL Frontier:** A queue managing URLs to be visited.
2.  **Worker Pool:** Concurrent "fetchers" that retrieve HTML and parse links.
3.  **Shared Index:** A thread-safe map or inverted index that stores processed content and metadata.

### 4.2. Concurrency Model
The system must be designed for **Parallel Processing**:
* **Indexer:** Multiple goroutines or threads handling network I/O.
* **Searcher:** Read-only access to the index during crawl, potentially using `RWMutex` to allow multiple readers without blocking, except during index updates.

---

## 5. Non-Functional Requirements
* **Scalability:** While limited to a single machine for this exercise, the architecture should be modular enough to allow for future distributed expansion.
* **Persistence (Bonus):** Ability to serialize the current "Visited" set and "Frontier" to disk to resume after a crash.
* **Performance:** Search latency should remain low ($<200ms$) even as the index grows.

---

## 6. Success Criteria
* **Functionality (40%):** Accurate recursive crawling and concurrent search functionality.
* **Architectural Sensibility (40%):** Efficient handling of back-pressure and proven thread-safety in the code.
* **AI Stewardship (20%):** Quality of documentation and the ability to justify design choices made during development.

---

## 7. Future Roadmap
* **Stage 1:** Core Indexer/Searcher logic with CLI dashboard.
* **Stage 2:** Implementation of disk-based persistence for state recovery.
* **Stage 3:** Advanced relevancy ranking (e.g., PageRank-lite or TF-IDF).