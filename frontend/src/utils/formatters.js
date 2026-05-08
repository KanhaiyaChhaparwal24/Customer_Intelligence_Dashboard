export const fmtCurrency = (val) => {
  if (!val && val !== 0) return '—'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency', currency: 'INR', maximumFractionDigits: 0,
  }).format(val)
}

export const fmtNumber = (val) =>
  val !== null && val !== undefined ? Number(val).toLocaleString('en-IN') : '—'

export const fmtPercent = (val) =>
  val !== null && val !== undefined ? `${val}%` : '—'

export const fmtDate = (val) => {
  if (!val) return '—'
  try {
    return new Date(val).toLocaleDateString('en-IN', {
      day: '2-digit', month: 'short', year: 'numeric',
    })
  } catch { return val }
}

export const fmtPhone = (phone) => {
  if (!phone) return '—'
  const d = phone.replace(/\D/g, '')
  if (d.length === 10) return `${d.slice(0,5)} ${d.slice(5)}`
  return phone
}

export const truncate = (str, n = 30) =>
  str && str.length > n ? `${str.slice(0, n)}…` : (str || '—')

export const fmtDuration = (secs) => {
  if (!secs) return '—'
  if (secs < 60) return `${Math.round(secs)}s`
  return `${Math.floor(secs / 60)}m ${Math.round(secs % 60)}s`
}
