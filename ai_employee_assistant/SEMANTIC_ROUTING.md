# Semantic MCP routing

Requests use keywords and local `nomic-embed-text` sentence embeddings. The router
matches server capabilities, then ranks discovered tools using descriptions and
intent examples. Vectors are cached in memory; optional servers remain lazy-loaded.
Document indexes are unaffected.

Competing semantic matches without clear wording trigger clarification. Insufficient
evidence no longer selects arbitrary tools. Approval cards still control actions
such as sending email and creating tickets.

Keep Ollama running with `nomic-embed-text` installed. Settings in `.env`:
`MCP_EMBEDDING_MODEL`, `MCP_EMBEDDING_TIMEOUT_SECONDS`,
`MCP_SEMANTIC_THRESHOLD`, and `MCP_SEMANTIC_MARGIN`.
Embedding failures fall back to keywords, with a 60-second retry cooldown.
Thresholds are heuristics, not probabilities or guarantees. This does not train
the model or implement reinforcement learning.

Try “Let Sarah know I cannot attend,” “I need someone from IT to look into my
broken laptop,” and “Keep in mind that I prefer short responses.” Review proposed
actions before approving them.
