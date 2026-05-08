import { useState } from 'react'
import { Sidebar }   from './components/layout/Sidebar'
import { Header }    from './components/layout/Header'
import { useApi }    from './hooks/useApi'
import { getKpis }   from './utils/api'
import Overview         from './pages/Overview'
import Converted        from './pages/Converted'
import FlipkartOnly     from './pages/FlipkartOnly'
import D2COnly          from './pages/D2COnly'
import AllCustomers     from './pages/AllCustomers'
import InvoiceProcessing from './pages/InvoiceProcessing'

export default function App() {
  const [activeTab, setActiveTab] = useState('overview')
  const { data: kpis, reload: reloadKpis } = useApi(getKpis)

  const PAGES = {
    overview:  <Overview />,
    converted: <Converted />,
    flipkart:  <FlipkartOnly />,
    d2c:       <D2COnly />,
    customers: <AllCustomers />,
    invoices:  <InvoiceProcessing />,
  }

  return (
    <div className="min-h-screen bg-bg flex">
      <Sidebar activeTab={activeTab} onTab={setActiveTab} />

      {/* Main content — offset by sidebar width */}
      <div className="flex-1 flex flex-col ml-60 transition-all duration-300 min-h-screen">
        <Header kpis={kpis} activeTab={activeTab} onSyncDone={reloadKpis} />
        <main className="flex-1 overflow-auto">
          {PAGES[activeTab] || <Overview />}
        </main>
      </div>
    </div>
  )
}
