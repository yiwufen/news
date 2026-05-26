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
