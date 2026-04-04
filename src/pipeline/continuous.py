"""
持续运行模式入口

完整的持续运行流程：新闻 → 情报微粒 → 图谱同步
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.agents.integrator import IntegratorAgent
from src.agents.worker import WorkerAgent
from src.schemas import IntelligenceParticle


@dataclass
class ContinuousRunResult:
    """持续运行结果"""

    particles_extracted: int
    particles_saved: int
    nodes_created: int
    edges_created: int
    errors: list[str]
    particles: list[IntelligenceParticle]


class ContinuousPipeline:
    """持续运行模式流水线

    完整流程：
    1. 从数据库读取未处理的新闻
    2. Worker Agent 提取情报微粒
    3. 保存到 SQLite
    4. Integrator Agent 实体对齐 + 图谱同步

    这是持续运行模式的标准入口，产出：
    - SQLite: 情报微粒存储
    - Neo4j: 知识图谱
    """

    def __init__(
        self,
        batch_size: int = 10,
        graph_enabled: bool = True,
        incremental: bool = True,
    ):
        """初始化持续运行流水线

        Args:
            batch_size: 每批处理数量
            graph_enabled: 是否启用图谱同步（默认启用）
            incremental: 是否增量处理
        """
        self.batch_size = batch_size
        self.graph_enabled = graph_enabled
        self.incremental = incremental

        self.worker = WorkerAgent()
        self.integrator = IntegratorAgent(graph_enabled=graph_enabled)

    def run(
        self,
        time_window: str | None = None,
        dry_run: bool = False,
    ) -> ContinuousRunResult:
        """运行持续处理流程

        Args:
            time_window: 时间切片过滤 (YYYY-WNN)
            dry_run: 仅测试，不保存

        Returns:
            ContinuousRunResult: 处理结果
        """
        errors: list[str] = []
        all_particles: list[IntelligenceParticle] = []
        total_nodes = 0
        total_edges = 0

        # 1. 迭代处理文章批次
        for batch in self.worker.iter_articles(
            batch_size=self.batch_size,
            time_window=time_window,
            incremental=self.incremental,
        ):
            # 2. Worker Agent 提取情报微粒
            results = self.worker.extract_batch(batch, merge_same_event=False)

            success_particles: list[IntelligenceParticle] = []
            log_records: list[dict[str, Any]] = []

            for article, result in zip(batch, results):
                if result.success and result.particle:
                    success_particles.append(result.particle)
                    all_particles.append(result.particle)
                    log_records.append({
                        "doc_id": article["doc_id"],
                        "status": "success",
                        "particle_id": result.particle.id,
                    })
                else:
                    log_records.append({
                        "doc_id": article["doc_id"],
                        "status": "failed",
                        "error_message": result.error_message or "未知错误",
                    })
                    errors.append(f"[{article['doc_id']}] 提取失败: {result.error_message}")

            if dry_run:
                continue

            # 3. 保存情报微粒到 SQLite
            if success_particles:
                self.worker.db.insert_particles_batch(
                    [p.model_dump() for p in success_particles]
                )

            # 4. 记录处理状态
            self.worker.db.log_processing_batch(log_records)

            # 5. 图谱同步
            if success_particles and self.graph_enabled:
                sync_result = self.integrator.run(success_particles)
                total_nodes += sync_result.get("entities_created", 0) + sync_result.get("entities_merged", 0)
                total_edges += sync_result.get("edges_created", 0)
                errors.extend(sync_result.get("errors", []))

        return ContinuousRunResult(
            particles_extracted=len(all_particles),
            particles_saved=len(all_particles) if not dry_run else 0,
            nodes_created=total_nodes,
            edges_created=total_edges,
            errors=errors,
            particles=all_particles,
        )

    def run_once(self, limit: int = 10) -> ContinuousRunResult:
        """运行一次处理（用于测试或手动触发）

        Args:
            limit: 处理文章数量上限

        Returns:
            ContinuousRunResult: 处理结果
        """
        # 临时修改 batch_size
        original_batch_size = self.batch_size
        self.batch_size = limit

        result = self.run()

        self.batch_size = original_batch_size
        return result


def run_continuous(
    batch_size: int = 10,
    graph_enabled: bool = True,
    incremental: bool = True,
    time_window: str | None = None,
    dry_run: bool = False,
) -> ContinuousRunResult:
    """持续运行模式便捷入口

    Args:
        batch_size: 每批处理数量
        graph_enabled: 是否启用图谱同步
        incremental: 是否增量处理
        time_window: 时间切片过滤
        dry_run: 仅测试

    Returns:
        ContinuousRunResult: 处理结果
    """
    pipeline = ContinuousPipeline(
        batch_size=batch_size,
        graph_enabled=graph_enabled,
        incremental=incremental,
    )
    return pipeline.run(time_window=time_window, dry_run=dry_run)
