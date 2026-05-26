import client from './client'
import type { PaginatedResponse, EntitySummary } from './types'

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
