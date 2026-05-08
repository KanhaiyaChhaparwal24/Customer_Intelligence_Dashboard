import { useState } from 'react'
import {
  LayoutDashboard, Users, ShoppingBag, Store,
  ListFilter, FileSearch, Menu, X,
  Zap, Package
} from 'lucide-react'

const NAV = [
  { id: 'overview',    label: 'Overview',          icon: LayoutDashboard },
  { id: 'converted',   label: 'Converted',         icon: Zap },
  { id: 'flipkart',    label: 'Flipkart Only',      icon: ShoppingBag },
  { id: 'd2c',         label: 'D2C Only',           icon: Store },
  { id: 'customers',   label: 'All Customers',      icon: Users },
  { id: 'invoices',    label: 'Invoice Processing', icon: FileSearch },
]

export function Sidebar({ activeTab, onTab }) {
  const [collapsed, setCollapsed] = useState(false)

  return (
    <>
      {/* Mobile overlay */}
      <aside
        className={`
          fixed left-0 top-0 h-full z-40 flex flex-col
          bg-card border-r border-border transition-all duration-300
          ${collapsed ? 'w-16' : 'w-60'}
        `}
      >
        {/* Logo */}
        <div className="flex items-center gap-3 px-4 py-5 border-b border-border">
          <div className="w-8 h-8 rounded-xl bg-gradient-to-br from-converted to-flipkart flex items-center justify-center shrink-0">
            <Package size={16} className="text-white" />
          </div>
          {!collapsed && (
            <div className="overflow-hidden">
              <p className="text-sm font-bold text-white leading-tight">LuggageIQ</p>
              <p className="text-[10px] text-muted">Customer Intelligence</p>
            </div>
          )}
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="ml-auto text-muted hover:text-white transition-colors shrink-0"
          >
            {collapsed ? <Menu size={16} /> : <X size={16} />}
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 py-4 px-2 space-y-1">
          {NAV.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => onTab(id)}
              className={`
                w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium
                transition-all duration-200 group
                ${activeTab === id
                  ? 'bg-gradient-to-r from-converted/20 to-flipkart/10 text-white border border-converted/30'
                  : 'text-muted hover:text-slate-200 hover:bg-surface'
                }
              `}
            >
              <Icon
                size={17}
                className={activeTab === id ? 'text-converted' : 'text-muted group-hover:text-slate-400'}
              />
              {!collapsed && <span className="truncate">{label}</span>}
            </button>
          ))}
        </nav>

        {/* Footer */}
        {!collapsed && (
          <div className="p-4 border-t border-border">
            <p className="text-[10px] text-muted text-center">v2.0 · Incremental Sync</p>
          </div>
        )}
      </aside>
    </>
  )
}
