import client from './client'
import type { PaginatedResponse, EntitySummary, KUSummary, ClusterSummary } from './types'

export async function fetchEntities(
  page: number,
  pageSize: number,
  search = '',
  entityType = '',
): Promise<PaginatedResponse<EntitySummary>> {
  const res = await client.get<PaginatedResponse<EntitySummary>>('/entities', {
    params: { page, page_size: pageSize, search: search || undefined, entity_type: entityType || undefined },
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

let cachedEntityTypes: string[] | null = null

export async function fetchEntityTypes(): Promise<string[]> {
  if (cachedEntityTypes) return cachedEntityTypes
  const res = await client.get<string[]>('/entity-types')
  cachedEntityTypes = res.data
  return res.data
}

export interface EditEntityRequest {
  canonical_name?: string
  entity_type?: string
  description?: string
  aliases?: string[]
  identifiers?: Record<string, string>
  tags?: string[]
}

export interface NewEntitySpec {
  canonical_name: string
  entity_type?: string
  aliases?: string[]
  identifiers?: Record<string, string>
  description?: string
  ku_ids: string[]
}

export async function editEntity(entityId: string, updates: EditEntityRequest): Promise<Record<string, unknown>> {
  const res = await client.put(`/entities/${entityId}`, updates)
  return res.data
}

export async function mergeEntities(sourceId: string, targetId: string): Promise<Record<string, unknown>> {
  const res = await client.post('/entities/merge', { source_id: sourceId, target_id: targetId })
  return res.data
}

export async function splitEntity(entityId: string, newEntities: NewEntitySpec[]): Promise<Record<string, unknown>[]> {
  const res = await client.post(`/entities/${entityId}/split`, { new_entities: newEntities })
  return res.data
}

export async function deleteEntity(entityId: string): Promise<void> {
  await client.delete(`/entities/${entityId}`)
}
