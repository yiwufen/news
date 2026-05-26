import client from './client'

export interface UserInfo {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'viewer'
  is_active: boolean
  created_at: string
  last_login_at: string | null
}

export async function fetchUsers(): Promise<UserInfo[]> {
  const res = await client.get('/users')
  return res.data
}

export async function createUser(data: {
  username: string
  password: string
  display_name?: string
  role?: string
}): Promise<UserInfo> {
  const res = await client.post('/users', data)
  return res.data
}

export async function updateUser(id: number, data: Record<string, unknown>): Promise<UserInfo> {
  const res = await client.put(`/users/${id}`, data)
  return res.data
}

export async function deleteUser(id: number): Promise<void> {
  await client.delete(`/users/${id}`)
}
