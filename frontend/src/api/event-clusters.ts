import client from './client'
import type { PaginatedResponse, ClusterSummary, KUSummary, EntitySummary } from './types'

export async function fetchEventClusters(
  page: number,
  pageSize: number,
  clusterType = '',
): Promise<PaginatedResponse<ClusterSummary>> {
  const res = await client.get<PaginatedResponse<ClusterSummary>>('/event-clusters', {
    params: { page, page_size: pageSize, cluster_type: clusterType || undefined },
  })
  return res.data
}

export async function fetchEventCluster(clusterId: string): Promise<Record<string, unknown>> {
  const res = await client.get(`/event-clusters/${clusterId}`)
  return res.data
}

export async function fetchClusterMemberKUs(
  clusterId: string,
  page: number,
  pageSize: number,
): Promise<PaginatedResponse<KUSummary>> {
  const res = await client.get<PaginatedResponse<KUSummary>>(`/event-clusters/${clusterId}/knowledge-units`, {
    params: { page, page_size: pageSize },
  })
  return res.data
}

export async function fetchClusterRelatedEntities(clusterId: string): Promise<EntitySummary[]> {
  const res = await client.get<EntitySummary[]>(`/event-clusters/${clusterId}/entities`)
  return res.data
}

export interface EditClusterRequest {
  title?: string
  summary?: string
  primary_entity_id?: string
  conflict_status?: 'none' | 'possible' | 'confirmed'
}

export async function editCluster(clusterId: string, updates: EditClusterRequest): Promise<Record<string, unknown>> {
  const res = await client.put(`/event-clusters/${clusterId}`, updates)
  return res.data
}

export async function mergeClusters(clusterIds: string[]): Promise<Record<string, unknown>> {
  const res = await client.post('/event-clusters/merge', { cluster_ids: clusterIds })
  return res.data
}

export async function splitCluster(clusterId: string, removeKuIds: string[]): Promise<Record<string, unknown>> {
  const res = await client.post(`/event-clusters/${clusterId}/split`, { remove_ku_ids: removeKuIds })
  return res.data
}

export async function deleteCluster(clusterId: string): Promise<void> {
  await client.delete(`/event-clusters/${clusterId}`)
}
