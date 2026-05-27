import client from './client'
import type { PaginatedResponse, AuditLogEntry } from './types'

export async function fetchAuditLog(
  page: number,
  pageSize: number,
  action = '',
  resourceType = '',
): Promise<PaginatedResponse<AuditLogEntry>> {
  const res = await client.get<PaginatedResponse<AuditLogEntry>>('/audit-log', {
    params: {
      page,
      page_size: pageSize,
      action: action || undefined,
      resource_type: resourceType || undefined,
    },
  })
  return res.data
}

export async function fetchAuditEntry(logId: number): Promise<AuditLogEntry> {
  const res = await client.get<AuditLogEntry>(`/audit-log/${logId}`)
  return res.data
}

export async function undoAuditEntry(logId: number): Promise<{ message: string }> {
  const res = await client.post<{ message: string }>(`/audit-log/${logId}/undo`)
  return res.data
}
