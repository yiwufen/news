import client from './client'
import type { ReprocessResult } from './types'

export async function reprocessDocument(docId: string): Promise<ReprocessResult> {
  const res = await client.post<ReprocessResult>(`/reprocessing/${docId}`)
  return res.data
}

export async function reprocessBatch(docIds: string[]): Promise<ReprocessResult[]> {
  const res = await client.post<ReprocessResult[]>('/reprocessing/batch', { doc_ids: docIds })
  return res.data
}
