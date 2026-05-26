import axios from 'axios'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

function getAccessToken(): string | null {
  return localStorage.getItem('access_token')
}

function getRefreshToken(): string | null {
  return localStorage.getItem('refresh_token')
}

function setTokens(access: string, refresh: string): void {
  localStorage.setItem('access_token', access)
  localStorage.setItem('refresh_token', refresh)
}

function clearTokens(): void {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
}

let isRefreshing = false
let refreshQueue: Array<{ resolve: (token: string) => void; reject: (err: Error) => void }> = []

client.interceptors.request.use((config) => {
  const token = getAccessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (res) => res,
  async (err) => {
    const originalRequest = err.config
    if (err.response?.status === 401 && !originalRequest._retry) {
      // Don't try refresh on auth endpoints themselves
      if (originalRequest.url?.includes('/auth/')) {
        clearTokens()
        window.location.href = '/admin/login'
        return Promise.reject(err)
      }

      originalRequest._retry = true
      const refreshToken = getRefreshToken()
      if (!refreshToken) {
        clearTokens()
        window.location.href = '/admin/login'
        return Promise.reject(err)
      }

      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          refreshQueue.push({ resolve, reject })
        }).then((token) => {
          originalRequest.headers.Authorization = `Bearer ${token}`
          return client.request(originalRequest)
        })
      }

      isRefreshing = true
      try {
        const res = await axios.post('/api/v1/auth/refresh', { refresh_token: refreshToken })
        const { access_token, refresh_token } = res.data
        setTokens(access_token, refresh_token)
        originalRequest.headers.Authorization = `Bearer ${access_token}`
        refreshQueue.forEach((p) => p.resolve(access_token))
        refreshQueue = []
        return client.request(originalRequest)
      } catch {
        clearTokens()
        refreshQueue.forEach((p) => p.reject(new Error('Refresh failed')))
        refreshQueue = []
        window.location.href = '/admin/login'
        return Promise.reject(err)
      } finally {
        isRefreshing = false
      }
    }
    return Promise.reject(err)
  },
)

export { setTokens, clearTokens, getAccessToken }
export default client
