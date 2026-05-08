import { useState } from 'react'
import { RefreshCw, Download, Activity, Clock } from 'lucide-react'
import { triggerSync, exportCsv } from '../../utils/api'
import { fmtDate, fmtDuration } from '../../utils/formatters'

export function Header({ kpis, activeTab, onSyncDone }) {
  const [syncing, setSyncing] = useState(false)

  const handleSync = async () => {
    setSyncing(true)
    try {
      await triggerSync()
      setTimeout(() => { onSyncDone?.(); setSyncing(false) }, 2000)
    } catch { setSyncing(false) }
  }

  return (
    <header className="flex items-center justify-between px-6 py-4 border-b border-border bg-card/80 backdrop-blur-sm sticky top-0 z-30">
      <div>
        <h1 className="text-lg font-bold text-white capitalize">
          {activeTab === 'overview' ? 'Customer Intelligence Overview'
           : activeTab === 'converted' ? 'Converted Customers'
           : activeTab === 'flipkart' ? 'Flipkart Only Customers'
           : activeTab === 'd2c' ? 'D2C Only Customers'
           : activeTab === 'customers' ? 'All Customers'
           : 'Invoice Processing'}
        </h1>
        {kpis?.last_sync_time && (
          <p className="text-xs text-muted flex items-center gap-1 mt-0.5">
            <Clock size={10} />
            Last sync: {fmtDate(kpis.last_sync_time)}
            {kpis.last_sync_duration && ` · ${fmtDuration(kpis.last_sync_duration)}`}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3">
        {/* Sync status indicator */}
        {kpis?.sync_running && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-yellow-500/10 border border-yellow-500/30">
            <Activity size={12} className="text-yellow-400 animate-pulse" />
            <span className="text-xs text-yellow-400 font-medium">Syncing…</span>
          </div>
        )}

        <button
          onClick={() => exportCsv(
            activeTab === 'converted' ? 'converted'
            : activeTab === 'flipkart' ? 'flipkart'
            : activeTab === 'd2c' ? 'd2c' : 'all'
          )}
          className="btn-ghost flex items-center gap-2"
        >
          <Download size={14} />
          Export CSV
        </button>

        <button
          onClick={handleSync}
          disabled={syncing}
          className="btn-primary flex items-center gap-2"
        >
          <RefreshCw size={14} className={syncing ? 'animate-spin' : ''} />
          {syncing ? 'Syncing…' : 'Sync Now'}
        </button>
      </div>
    </header>
  )
}
