import axios from 'axios'
import router from '../router'

// axios 实例：所有请求自动带 token
const request = axios.create({ baseURL: '/api' })

request.interceptors.request.use((config) => {
  const token = localStorage.getItem('token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 401 统一跳登录
request.interceptors.response.use(
  (resp) => resp,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      router.push('/login')
    }
    return Promise.reject(err)
  }
)

export default request
