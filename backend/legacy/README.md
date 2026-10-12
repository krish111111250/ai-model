# Legacy server-side RAG (pre-v3)

These modules ran the old architecture, where the server stored and searched
every customer's documents:

- `rag.py`     - server-side ChromaDB indexing, hybrid search, reranking, grounding
- `routers.py` - upload/chat endpoints used by the React frontend
- `saas.py`    - multi-tenant upload/ask with background jobs and webhooks

They were retired when storage and RAM on the server became the bottleneck and
enterprise customers asked that documents never leave their machines. The
retrieval logic now lives in `cli.py` (client side) and the generation logic in
`app/generation.py` (server side).

Nothing here is imported by the running app. Kept for reference and for the
React frontend, which needs a server-side store and no longer has one.
