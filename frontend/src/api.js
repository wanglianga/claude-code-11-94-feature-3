import { reactive } from 'vue'

const STORAGE_KEY = 'battery_eol_user'

export const store = reactive({
  user: JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'),
  setUser(user) {
    this.user = user
    if (user) localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
    else localStorage.removeItem(STORAGE_KEY)
  },
  logout() {
    this.setUser(null)
  },
  hasRole(...roles) {
    return this.user && roles.includes(this.user.role)
  },
})

async function request(method, url, body) {
  const headers = { 'Content-Type': 'application/json' }
  if (store.user) headers['X-Username'] = store.user.username
  const resp = await fetch(url, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await resp.json().catch(() => ({}))
  if (!resp.ok) {
    const err = new Error(data.message || `请求失败 ${resp.status}`)
    err.code = data.code
    err.status = resp.status
    err.details = data.details
    throw err
  }
  return data
}

export const api = {
  get: (url) => request('GET', url),
  post: (url, body) => request('POST', url, body),
}
