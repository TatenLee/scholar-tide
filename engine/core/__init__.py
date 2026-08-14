"""Cross-cutting infrastructure: shared by spiders, pipeline and render.

Each module has exactly one job, so it stays small and independently
testable. If you ever wonder where to put a helper, it almost always
belongs here.
"""