export interface PaginatedResponse<T> {
  total: number
  items: T[]
  page: number
  page_size: number
}

export interface DashboardStats {
  entities: { total: number; by_type: Record<string, number> }
  knowledge_units: { total: number; by_kind: Record<string, number> }
  event_clusters: { total: number }
  articles: {
    total: number
    by_category: Record<string, number>
    time_range: { start: string | null; end: string | null }
  }
  processing: {
    total_processed: number
    total_failed: number
    total_pending: number
    last_processed_at: string | null
  }
}

export interface EntitySummary {
  entity_id: string
  canonical_name: string
  entity_type: string | null
  updated_at: string
}

export interface KUSummary {
  ku_id: string
  unit_kind: string
  unit_type: string
  summary: string
  published_at: string
  conflict_status: string
  status: string
}

export interface ClusterSummary {
  cluster_id: string
  cluster_type: string
  title: string
  member_count: number
  source_count: number
  conflict_status: string
  updated_at: string
}

export interface ArticleSummary {
  id: number
  doc_id: string
  title: string
  publish_time: string
  source_name: string
  category: string
  credibility_tier: number
}

export interface ProcessingLogEntry {
  doc_id: string
  status: string
  knowledge_units_count: number
  entities_count: number
  clusters_count: number
  error_message: string | null
  updated_at: string
}
