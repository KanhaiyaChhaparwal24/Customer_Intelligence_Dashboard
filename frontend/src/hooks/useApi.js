import { useState, useEffect, useCallback } from 'react'

export function useApi(fetchFn, deps = []) {
  const [data, setData]       = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchFn()
      setData(result)
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Error loading data')
    } finally {
      setLoading(false)
    }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load() }, [load])

  return { data, loading, error, reload: load }
}

export function usePolling(fetchFn, intervalMs = 30000, deps = []) {
  const result = useApi(fetchFn, deps)

  useEffect(() => {
    const id = setInterval(result.reload, intervalMs)
    return () => clearInterval(id)
  }, [intervalMs]) // eslint-disable-line

  return result
}
