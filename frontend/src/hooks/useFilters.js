import { useState, useMemo } from 'react'

export function useFilters(data = []) {
  const [search, setSearch]   = useState('')
  const [city,   setCity]     = useState('')
  const [state,  setState]    = useState('')
  const [page,   setPage]     = useState(1)
  const perPage = 50

  const filtered = useMemo(() => {
    let result = [...(data || [])]
    if (search) {
      const s = search.toLowerCase()
      result = result.filter(
        (r) =>
          (r.email || '').toLowerCase().includes(s) ||
          (r.phone || '').includes(s) ||
          (r.customer_name || '').toLowerCase().includes(s)
      )
    }
    if (city)  result = result.filter((r) => (r.city  || '').toLowerCase() === city.toLowerCase())
    if (state) result = result.filter((r) => (r.state || '').toLowerCase() === state.toLowerCase())
    return result
  }, [data, search, city, state])

  const paginated = useMemo(() => {
    const start = (page - 1) * perPage
    return filtered.slice(start, start + perPage)
  }, [filtered, page])

  const totalPages = Math.max(1, Math.ceil(filtered.length / perPage))

  return {
    search, setSearch,
    city, setCity,
    state, setState,
    page, setPage,
    filtered, paginated,
    totalPages, perPage,
    total: filtered.length,
  }
}
