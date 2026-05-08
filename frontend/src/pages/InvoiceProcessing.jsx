import { useState } from 'react'
import { useApi }   from '../hooks/useApi'
import { getInvoices, retryFile, retryFailed } from '../utils/api'
import { DataTable, Pagination } from '../components/tables/DataTable'
import { TableSkeleton }         from '../components/ui/Skeleton'
import { Badge }                 from '../components/ui/Badge'
import { fmtDate } from '../utils/formatters'
import { RefreshCw, RotateCcw, CheckCircle, XCircle, Clock } from 'lucide-react'

export default function InvoiceProcessing() {
  const [page, setPage]       = useState(1)
  const { data, loading, reload } = useApi(() => getInvoices(page), [page])
  const [retrying, setRetrying] = useState({})
  const [retryingAll, setRetryingAll] = useState(false)

  const handleRetry = async (fileId) => {
    setRetrying((p) => ({ ...p, [fileId]: true }))
    try { await retryFile(fileId) } catch (e) { console.error(e) }
    setRetrying((p) => ({ ...p, [fileId]: false }))
    reload()
  }

  const handleRetryAll = async () => {
    setRetryingAll(true)
    try { await retryFailed() } catch (e) { console.error(e) }
    setRetryingAll(false)
    setTimeout(reload, 2000)
  }

  const files = data?.files || []
  const total = data?.total || 0
  const totalPages = Math.max(1, Math.ceil(total / 50))

  const columns = [
    { key: 'filename',     label: 'Filename',   width: 200, render: (v) => <span className="text-slate-300 text-xs font-mono">{v || 'Unknown'}</span> },
    { key: 'file_id',      label: 'File ID',    width: 180, render: (v) => <span className="text-muted text-[10px] font-mono">{v?.slice(0, 20)}…</span> },
    { key: 'row_number',   label: 'Sheet Row',  render: (v) => <span className="text-muted text-xs">#{v}</span> },
    { key: 'status',       label: 'Status',
      render: (v) => (
        v === 'success' ? <Badge type="success"><CheckCircle size={10} className="inline" /> Success</Badge>
        : v === 'failed'  ? <Badge type="failed"><XCircle size={10} className="inline" /> Failed</Badge>
        : v === 'retrying'? <Badge type="pending"><RefreshCw size={10} className="inline animate-spin" /> Retrying</Badge>
        : <Badge type="pending"><Clock size={10} className="inline" /> {v || 'Pending'}</Badge>
      )
    },
    { key: 'processed_at', label: 'Processed At', render: (v) => fmtDate(v) },
    { key: '_actions',     label: 'Actions',
      render: (_, row) => row.status === 'failed' ? (
        <button
          onClick={() => handleRetry(row.file_id)}
          disabled={retrying[row.file_id]}
          className="flex items-center gap-1 text-xs text-converted hover:text-purple-300 disabled:opacity-50 transition-colors"
        >
          <RotateCcw size={12} className={retrying[row.file_id] ? 'animate-spin' : ''} />
          Retry OCR
        </button>
      ) : null
    },
  ]

  return (
    <div className="p-6 animate-slide-up">
      <div className="glass-card overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-sm font-semibold text-white">
            Invoice Processing Log
            <span className="ml-2 text-xs text-muted">({total} files)</span>
          </h2>
          <div className="flex gap-2">
            <button onClick={reload} className="btn-ghost flex items-center gap-2">
              <RefreshCw size={13} /> Refresh
            </button>
            <button
              onClick={handleRetryAll}
              disabled={retryingAll}
              className="btn-primary flex items-center gap-2"
            >
              <RotateCcw size={13} className={retryingAll ? 'animate-spin' : ''} />
              Retry All Failed
            </button>
          </div>
        </div>
        {loading ? <TableSkeleton cols={6} /> : (
          <DataTable columns={columns} data={files} emptyMessage="No invoices processed yet" />
        )}
        <Pagination page={page} totalPages={totalPages} onPage={setPage} total={total} perPage={50} />
      </div>
    </div>
  )
}
