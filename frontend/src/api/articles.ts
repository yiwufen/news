import client from './client'
import type { PaginatedResponse, ArticleSummary, KUSummary, EntitySummary } from './types'

export async function fetchArticles(
  page: number,
  pageSize: number,
  search = '',
  category = '',
  dateFrom = '',
  dateTo = '',
): Promise<PaginatedResponse<ArticleSummary>> {
  const res = await client.get<PaginatedResponse<ArticleSummary>>('/articles', {
    params: {
      page,
      page_size: pageSize,
      search: search || undefined,
      category: category || undefined,
      date_from: dateFrom || undefined,
      date_to: dateTo || undefined,
    },
  })
  return res.data
}

export async function fetchArticle(docId: string): Promise<Record<string, unknown>> {
  const res = await client.get(`/articles/${docId}`)
  return res.data
}

export async function fetchArticleRelatedKUs(
  docId: string,
  page: number,
  pageSize: number,
): Promise<PaginatedResponse<KUSummary>> {
  const res = await client.get<PaginatedResponse<KUSummary>>(`/articles/${docId}/knowledge-units`, {
    params: { page, page_size: pageSize },
  })
  return res.data
}

export async function fetchArticleRelatedEntities(docId: string): Promise<EntitySummary[]> {
  const res = await client.get<EntitySummary[]>(`/articles/${docId}/entities`)
  return res.data
}
