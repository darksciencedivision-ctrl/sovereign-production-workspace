# Snapshot policy

This package exports exact tracked bytes from the immutable selected commit. It excludes secrets, private runtime payloads, model weights, caches, generated build debris, and raw `.git` state. The tracked RC3 Git bundle is retained as intentional provenance. Security scanning is pattern based and cannot guarantee absence of every possible secret.
