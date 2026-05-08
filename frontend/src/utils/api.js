import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    console.error('API Error:', err.response?.data || err.message)
    return Promise.reject(err)
  }
)

export const getKpis        = ()              => api.get('/dashboard/kpis')
export const getConversions = ()              => api.get('/dashboard/conversions')
export const getProducts    = ()              => api.get('/dashboard/products')
export const getCities      = ()              => api.get('/dashboard/cities')
export const getRevenue     = ()              => api.get('/dashboard/revenue')
export const getSizes       = ()              => api.get('/dashboard/sizes')
export const getColours     = ()              => api.get('/dashboard/colours')
export const getPayments    = ()              => api.get('/dashboard/payments')
export const getInvoices    = (page = 1)      => api.get(`/dashboard/invoices?page=${page}`)
export const getJourney     = (email)         => api.get(`/dashboard/journey/${encodeURIComponent(email)}`)

export const getCustomers = (params = {}) => {
  const q = new URLSearchParams(params).toString()
  return api.get(`/dashboard/customers?${q}`)
}

export const triggerSync    = ()          => api.post('/sync/trigger')
export const getSyncStatus  = ()          => api.get('/sync/status')
export const retryFailed    = ()          => api.post('/sync/retry-failed')
export const retryFile      = (fileId)    => api.post(`/invoices/${fileId}/retry`)
export const reprocessRow   = (rowNum)    => api.post(`/invoices/row/${rowNum}/reprocess`)

export const exportCsv = (type = 'all') => {
  window.open(`/api/export/csv?type=${type}`, '_blank')
}

export default api
