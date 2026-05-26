import client from './client'
import type { DashboardStats } from './types'

export async function fetchDashboardStats(): Promise<DashboardStats> {
  const res = await client.get<DashboardStats>('/dashboard/stats')
  return res.data
}
