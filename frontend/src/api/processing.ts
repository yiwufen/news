import client from './client'
import type { PaginatedResponse, ProcessingLogEntry, PipelineStatus, ContainerStatus } from './types'

export async function fetchProcessingLog(
  page: number,
  pageSize: number,
): Promise<PaginatedResponse<ProcessingLogEntry>> {
  const res = await client.get<PaginatedResponse<ProcessingLogEntry>>('/processing-log', {
    params: { page, page_size: pageSize },
  })
  return res.data
}

export async function fetchPipelineStatus(): Promise<PipelineStatus> {
  const res = await client.get<PipelineStatus>('/pipeline/status')
  return res.data
}

export async function fetchContainerStatuses(): Promise<ContainerStatus[]> {
  const res = await client.get<ContainerStatus[]>('/containers/status')
  return res.data
}
