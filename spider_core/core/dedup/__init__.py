# Spider Core — Deduplication Pipeline
from core.dedup.redis_dedup import DedupPipelineError, RedisDedupPipeline

__all__ = ["RedisDedupPipeline", "DedupPipelineError"]
