"""Sprint 0 launch-security primitives: rate limiting, quotas, request guards.

Nothing in this package changes analysis, scoring, or product behaviour — it is
the safety perimeter around the serving layer (auth gating, cost control, abuse
prevention).  All state is in-process; move the backends to Redis for multi-
worker / multi-replica deployments.
"""
