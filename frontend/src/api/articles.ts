import client from './client'
import type { PaginatedResponse, ArticleSummary } from './types'

export async function fetchArticles(
  page: number,
  pageSize: number,
  search = '',
  category = '',
): Promise<PaginatedResponse<ArticleSummary>> {
  const res = await client.get<PaginatedResponse<ArticleSummary>>('/articles', {
    params: { page, page_size: pageSize, search: search || undefined, category: category || undefined },
  })
  return res.data
}

export async function fetchArticle(docId: string): Promise<Record<string, unknown>> {
  const res = await client.get(`/articles/${docId}`)
  return res.data
}
