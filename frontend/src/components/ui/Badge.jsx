export function Badge({ type, children }) {
  const cls = {
    flipkart:  'badge-flipkart',
    d2c:       'badge-d2c',
    converted: 'badge-converted',
    success:   'badge-success',
    failed:    'badge-failed',
    pending:   'badge-pending',
    retrying:  'badge badge-pending',
    processing:'badge badge-pending',
    high:      'badge bg-emerald-500/20 text-emerald-300',
    medium:    'badge bg-yellow-500/20 text-yellow-300',
    low:       'badge bg-red-500/20 text-red-300',
  }[type] || 'badge bg-slate-500/20 text-slate-300'

  return <span className={cls}>{children || type}</span>
}
