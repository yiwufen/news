"""
Worker Agent - 情报微粒提取器

从新闻中提取完整的结构化情报微粒。
"""

from __future__ import annotations

import json
from datetime import date
from typing import Iterator

from anthropic.types import Message, ToolUseBlock
from pydantic import ValidationError

from collectors.database import Database
from src.agents.worker.prompts import SYSTEM_PROMPT, build_batch_extraction_prompt, build_extraction_prompt
from src.agents.worker.tools import EXTRACTION_TOOL_SCHEMA
from src.llm import create_llm_client, DEFAULT_MAX_TOKENS
from src.schemas import ExtractionResult, IntelligenceParticle


class WorkerAgent:
    """情报微粒提取器"""

    def __init__(self, db_path: str = "data/news.db"):
        self.db = Database(db_path)
        self.client, self.model = create_llm_client()
        self.max_tokens = DEFAULT_MAX_TOKENS

    @staticmethod
    def _parse_nested_json(data):
        """递归解析嵌套的 JSON 字符串

        某些兼容 API 会将嵌套对象序列化为 JSON 字符串，
        需要递归解析以恢复正确的对象结构。
        """
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                return WorkerAgent._parse_nested_json(parsed)
            except (json.JSONDecodeError, TypeError):
                return data
        elif isinstance(data, dict):
            return {k: WorkerAgent._parse_nested_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [WorkerAgent._parse_nested_json(item) for item in data]
        return data

    def extract_single(self, article: dict) -> ExtractionResult:
        """从单篇文章提取情报微粒"""
        try:
            response = self._call_llm(user_prompt=build_extraction_prompt(article))
            return self._parse_response(response, article["doc_id"])
        except Exception as e:
            return ExtractionResult(success=False, error_message=str(e))

    def extract_batch(
        self,
        articles: list[dict],
        merge_same_event: bool = True,
    ) -> list[ExtractionResult]:
        """批量提取"""
        if merge_same_event and len(articles) > 1:
            try:
                response = self._call_llm(
                    user_prompt=build_batch_extraction_prompt(articles)
                )
                return self._parse_batch_response(response, articles)
            except Exception as e:
                return [ExtractionResult(success=False, error_message=str(e))] * len(articles)
        else:
            return [self.extract_single(a) for a in articles]

    def extract_from_articles(
        self,
        articles: list[dict],
        merge_same_event: bool = False,
    ) -> list[IntelligenceParticle]:
        """从外部传入的文章列表中提取情报微粒

        用于任务驱动架构，接收外部传入的文章数据，
        不依赖数据库读取。

        Args:
            articles: 外部传入的文章列表
            merge_same_event: 是否合并同一事件 (默认 False，保持 1:1 映射)

        Returns:
            提取的情报微粒列表
        """
        particles: list[IntelligenceParticle] = []

        if not articles:
            return particles

        # 批量提取
        results = self.extract_batch(articles, merge_same_event=merge_same_event)

        for result in results:
            if result.success and result.particle:
                particles.append(result.particle)

        return particles

    def _call_llm(
        self,
        user_prompt: str,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> Message:
        """调用 LLM API"""
        return self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system_prompt,
            tools=[EXTRACTION_TOOL_SCHEMA],  # type: ignore[arg-type]
            tool_choice={"type": "tool", "name": "extract_intelligence_particle"},
            messages=[{"role": "user", "content": user_prompt}],
        )

    def _parse_response(self, response: Message, doc_id: str) -> ExtractionResult:
        """解析响应"""
        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "extract_intelligence_particle":
                try:
                    # 递归解析嵌套的 JSON 字符串
                    parsed_input = self._parse_nested_json(block.input)
                    particle = IntelligenceParticle.model_validate(parsed_input)
                    # 确保 source_doc_ids 包含当前文档
                    if doc_id not in particle.traceability.source_doc_ids:
                        particle.traceability.source_doc_ids.append(doc_id)
                    return ExtractionResult(success=True, particle=particle)
                except ValidationError as e:
                    return ExtractionResult(
                        success=False,
                        error_message=f"验证失败: {e}",
                        raw_response=json.dumps(block.input, ensure_ascii=False),
                    )

        return ExtractionResult(success=False, error_message="未找到有效输出")

    def _parse_batch_response(
        self,
        response: Message,
        articles: list[dict],
    ) -> list[ExtractionResult]:
        """解析批量响应"""
        results: list[ExtractionResult] = []
        doc_ids = {a["doc_id"] for a in articles}

        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "extract_intelligence_particle":
                try:
                    # 递归解析嵌套的 JSON 字符串
                    parsed_input = self._parse_nested_json(block.input)
                    particle = IntelligenceParticle.model_validate(parsed_input)
                    # 过滤有效的 source_doc_ids
                    valid_ids = [did for did in particle.traceability.source_doc_ids if did in doc_ids]
                    if valid_ids:
                        particle.traceability.source_doc_ids = valid_ids
                    results.append(ExtractionResult(success=True, particle=particle))
                except ValidationError as e:
                    results.append(ExtractionResult(success=False, error_message=f"验证失败: {e}"))

        return results if results else [
            ExtractionResult(success=False, error_message="批量提取未产生有效结果")
        ]

    def iter_articles(
        self,
        batch_size: int = 10,
        time_window: str | None = None,
        incremental: bool = True,
    ) -> Iterator[list[dict]]:
        """迭代文章（按时间切片分组）"""
        articles = self.db.get_all_articles()

        if incremental:
            processed_ids = self.db.get_processed_doc_ids()
            articles = [a for a in articles if a["doc_id"] not in processed_ids]

        if time_window:
            from src.agents.worker.prompts import compute_slice_window
            articles = [
                a for a in articles
                if compute_slice_window(a["publish_time"]) == time_window
            ]

        for i in range(0, len(articles), batch_size):
            yield articles[i : i + batch_size]

    def run(
        self,
        batch_size: int = 10,
        time_window: str | None = None,
        incremental: bool = True,
        dry_run: bool = False,
    ) -> list[IntelligenceParticle]:
        """运行提取器

        Args:
            batch_size: 每批数量
            time_window: 时间切片过滤 (YYYY-WNN)
            incremental: 是否只处理未处理的文章
            dry_run: 仅测试，不保存

        Returns:
            成功提取的情报微粒列表
        """
        particles: list[IntelligenceParticle] = []

        for batch in self.iter_articles(batch_size, time_window, incremental):
            # 单篇提取，确保 1:1 映射
            results = self.extract_batch(batch, merge_same_event=False)

            success_particles: list[IntelligenceParticle] = []
            log_records: list[dict] = []

            for article, result in zip(batch, results):
                if result.success and result.particle:
                    success_particles.append(result.particle)
                    particles.append(result.particle)
                    log_records.append({
                        "doc_id": article["doc_id"],
                        "status": "success",
                        "particle_id": result.particle.id,
                    })
                else:
                    log_records.append({
                        "doc_id": article["doc_id"],
                        "status": "failed",
                        "error_message": result.error_message,
                    })
                    print(f"提取失败 [{article['doc_id']}]: {result.error_message}")

            # 分批保存
            if not dry_run:
                if success_particles:
                    self.db.insert_particles_batch([p.model_dump() for p in success_particles])
                self.db.log_processing_batch(log_records)

        return particles
