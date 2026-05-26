import client from './client'
import type { PaginatedResponse, ProcessingLogEntry } from './types'

export async function fetchProcessingLog(
  page: number,
  pageSize: number,
): Promise<PaginatedResponse<ProcessingLogEntry>> {
  const res = await client.get<PaginatedResponse<ProcessingLogEntry>>('/processing-log', {
    params: { page, page_size: pageSize },
  })
  return res.data
}
