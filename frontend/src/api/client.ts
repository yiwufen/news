import axios from 'axios'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
})

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

client.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      const token = prompt('Admin Token:')
      if (token) {
        localStorage.setItem('admin_token', token)
        err.config.headers.Authorization = `Bearer ${token}`
        return client.request(err.config)
      }
    }
    return Promise.reject(err)
  },
)

export default client
