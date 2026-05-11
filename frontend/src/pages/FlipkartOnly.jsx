import { useApi }     from '../hooks/useApi'
import { useFilters } from '../hooks/useFilters'
import { getCustomers } from '../utils/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { TableSkeleton }         from '../components/ui/Skeleton'
import { Badge }                 from '../components/ui/Badge'
import { fmtDate, fmtPhone, truncate } from '../utils/formatters'
import { Search } from 'lucide-react'

export default function MarketplaceOnly() {
  const { data, loading } = useApi(() => getCustomers({ source: 'marketplace' }))
  const rows = data?.data || []
  const { search, setSearch, paginated, page, setPage, totalPages, total, perPage } = useFilters(rows)

  const columns = [
    { key: 'email',        label: 'Email',        render: (v) => <span className="text-blue-300 text-xs">{v || '—'}</span> },
    { key: 'phone',        label: 'Phone',        render: (v) => fmtPhone(v) },
    { key: 'product',      label: 'Product',      render: (v, r) => truncate(r.product || v, 30) },
    { key: 'size',         label: 'Size',         render: (v) => v || '—' },
    { key: 'colour',       label: 'Colour',       render: (v) => v || '—' },
    { key: 'city',         label: 'City',         render: (v) => v || '—' },
    { key: 'state',        label: 'State',        render: (v) => v || '—' },
    { key: 'invoice_date', label: 'Invoice Date', render: (v) => fmtDate(v) },
    { key: 'detected_source', label: 'Source',    render: (v) => <Badge type={v?.toLowerCase() === 'flipkart' ? 'flipkart' : 'converted'}>{v || 'Marketplace'}</Badge> },
    { key: 'source_confidence', label: 'Conf.',   render: (v) => v ? `${(v * 100).toFixed(0)}%` : '—' },
  ]

  return (
    <div className="p-6 animate-slide-up">
      <div className="glass-card overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-sm font-semibold text-white">
            Marketplace Only
            <span className="ml-2 text-xs text-muted">({total})</span>
          </h2>
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input className="input-search pl-9 w-64" placeholder="Search email, phone…"
              value={search} onChange={(e) => { setSearch(e.target.value); setPage(1) }} />
          </div>
        </div>
        {loading ? <TableSkeleton /> : <DataTable columns={columns} data={paginated} emptyMessage="No marketplace-only customers found" />}
        <Pagination page={page} totalPages={totalPages} onPage={setPage} total={total} perPage={perPage} />
      </div>
    </div>
  )
}
