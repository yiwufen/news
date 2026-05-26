import client from './client'
import type { PaginatedResponse, EntitySummary, KUSummary, ClusterSummary } from './types'

export async function fetchEntities(
  page: number,
  pageSize: number,
  search = '',
): Promise<PaginatedResponse<EntitySummary>> {
  const res = await client.get<PaginatedResponse<EntitySummary>>('/entities', {
    params: { page, page_size: pageSize, search: search || undefined },
  })
  return res.data
}

export async function fetchEntity(entityId: string): Promise<Record<string, unknown>> {
  const res = await client.get(`/entities/${entityId}`)
  return res.data
}

export async function fetchEntityRelatedKUs(
  entityId: string,
  page: number,
  pageSize: number,
): Promise<PaginatedResponse<KUSummary>> {
  const res = await client.get<PaginatedResponse<KUSummary>>(`/entities/${entityId}/knowledge-units`, {
    params: { page, page_size: pageSize },
  })
  return res.data
}

export async function fetchEntityRelatedClusters(
  entityId: string,
  page: number,
  pageSize: number,
): Promise<PaginatedResponse<ClusterSummary>> {
  const res = await client.get<PaginatedResponse<ClusterSummary>>(`/entities/${entityId}/event-clusters`, {
    params: { page, page_size: pageSize },
  })
  return res.data
}
