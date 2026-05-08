import { useApi }     from '../hooks/useApi'
import { useFilters } from '../hooks/useFilters'
import { getCustomers } from '../utils/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { TableSkeleton }         from '../components/ui/Skeleton'
import { Badge }                 from '../components/ui/Badge'
import { fmtCurrency, fmtDate, fmtPhone, truncate } from '../utils/formatters'
import { Search } from 'lucide-react'

export default function D2COnly() {
  const { data, loading } = useApi(() => getCustomers({ source: 'd2c' }))
  const rows = data?.data || []
  const { search, setSearch, paginated, page, setPage, totalPages, total, perPage } = useFilters(rows)

  const columns = [
    { key: 'email',       label: 'Email',       render: (v) => <span className="text-orange-300 text-xs">{v || '—'}</span> },
    { key: 'phone',       label: 'Phone',       render: (v) => fmtPhone(v) },
    { key: 'orders',      label: 'Orders',      render: (v, r) => <span className="text-orange-400 font-semibold">{(r.orders || []).length || 0}</span> },
    { key: 'spend',       label: 'Total Spend', render: (v, r) => <span className="text-emerald-400">{fmtCurrency(r.total_spend ?? v)}</span> },
    { key: 'products',    label: 'Products',    render: (v, r) => truncate((r.products || []).join(', '), 35) },
    { key: 'first_order', label: 'First Order', render: (v) => fmtDate(v) },
    { key: 'city',        label: 'City',        render: (v) => v || '—' },
    { key: '_source',     label: 'Source',      render: () => <Badge type="d2c">D2C</Badge> },
  ]

  return (
    <div className="p-6 animate-slide-up">
      <div className="glass-card overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-sm font-semibold text-white">
            D2C Only Customers
            <span className="ml-2 text-xs text-muted">({total})</span>
          </h2>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input className="input-search pl-9 w-64" placeholder="Search email, phone…"
              value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
          </div>
        </div>
        {loading ? <TableSkeleton /> : <DataTable columns={columns} data={paginated} emptyMessage="No D2C-only customers found" />}
        <Pagination page={page} totalPages={totalPages} onPage={setPage} total={total} perPage={perPage} />
      </div>
    </div>
  )
}
