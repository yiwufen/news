import client from './client'
import type { PaginatedResponse, KUSummary, EntitySummary } from './types'

export async function fetchKnowledgeUnits(
  page: number,
  pageSize: number,
  search = '',
  unitType = '',
  unitKind = '',
): Promise<PaginatedResponse<KUSummary>> {
  const res = await client.get<PaginatedResponse<KUSummary>>('/knowledge-units', {
    params: {
      page,
      page_size: pageSize,
      search: search || undefined,
      unit_type: unitType || undefined,
      unit_kind: unitKind || undefined,
    },
  })
  return res.data
}

export async function fetchKnowledgeUnit(kuId: string): Promise<Record<string, unknown>> {
  const res = await client.get(`/knowledge-units/${kuId}`)
  return res.data
}

export async function fetchKURelatedEntities(kuId: string): Promise<EntitySummary[]> {
  const res = await client.get<EntitySummary[]>(`/knowledge-units/${kuId}/entities`)
  return res.data
}
