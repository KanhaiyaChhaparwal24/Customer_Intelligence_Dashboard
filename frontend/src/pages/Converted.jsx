import { useState } from "react";
import { useApi } from "../hooks/useApi";
import { useFilters } from "../hooks/useFilters";
import { getConversions, getJourney } from "../utils/api";
import { DataTable, Pagination } from "../components/tables/DataTable";
import { TableSkeleton } from "../components/ui/Skeleton";
import { Badge } from "../components/ui/Badge";
import { fmtCurrency, fmtDate, fmtPhone, truncate } from "../utils/formatters";
import { Search, GitBranch, X } from "lucide-react";

function JourneyModal({ email, onClose }) {
  const { data, loading } = useApi(() => getJourney(email), [email]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-card border border-border rounded-2xl p-6 max-w-lg w-full mx-4 max-h-[80vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-5">
          <h2 className="text-sm font-bold text-white">
            Customer Journey — {email}
          </h2>
          <button onClick={onClose} className="text-muted hover:text-white">
            <X size={16} />
          </button>
        </div>
        {loading ? (
          <div className="text-center text-muted py-8">Loading…</div>
        ) : !data?.events?.length ? (
          <div className="text-center text-muted py-8">No events found</div>
        ) : (
          <div className="space-y-3">
            {data.events.map((e, i) => (
              <div key={i} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <div
                    className={`w-2.5 h-2.5 rounded-full mt-1 ${e.type === "warranty_registration" ? "bg-flipkart" : e.type === "marketplace_purchase" ? "bg-flipkart" : "bg-d2c"}`}
                  />
                  {i < data.events.length - 1 && (
                    <div className="w-px flex-1 bg-border mt-1" />
                  )}
                </div>
                <div className="pb-3 flex-1">
                  <div className="flex items-center justify-between">
                    <Badge
                      type={
                        e.type === "marketplace_purchase"
                          ? "flipkart"
                          : e.type === "warranty_registration"
                            ? "flipkart"
                            : "d2c"
                      }
                    >
                      {e.type === "marketplace_purchase"
                        ? e.platform || "Marketplace"
                        : e.type === "warranty_registration"
                          ? "Warranty Registration"
                          : "D2C Order"}
                    </Badge>
                    <span className="text-xs text-muted">
                      {fmtDate(e.date)}
                    </span>
                  </div>
                  <p className="text-xs text-slate-400 mt-1">
                    {e.product ||
                      e.invoice_number ||
                      e.order_id ||
                      (e.type === "marketplace_purchase"
                        ? "Marketplace Purchase"
                        : "D2C Order")}
                  </p>
                  {e.amount !== undefined && e.amount !== null && (
                    <p className="text-xs font-semibold text-emerald-400">
                      {fmtCurrency(e.amount)}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function Converted() {
  const { data, loading } = useApi(getConversions);
  const [journeyEmail, setJourneyEmail] = useState(null);
  const rows = data?.data || [];
  const {
    search,
    setSearch,
    paginated,
    page,
    setPage,
    totalPages,
    total,
    perPage,
  } = useFilters(rows);

  const columns = [
    {
      key: "email",
      label: "Email",
      render: (v) => <span className="text-blue-300 text-xs">{v || "—"}</span>,
    },
    { key: "phone", label: "Phone", render: (v) => fmtPhone(v) },
    {
      key: "products",
      label: "Products",
      render: (v, r) => truncate((r.products || []).join(', ') || v, 28),
    },
    { key: "city", label: "City", render: (v, r) => r.city || "—" },
    {
      key: "match_reason",
      label: "Match Reason",
      render: (v) => <span className="text-xs text-muted">{v || "—"}</span>,
    },
    {
      key: "match_confidence_bucket",
      label: "Confidence",
      render: (v) => {
        let color = "text-muted";
        if (v === "High Confidence") color = "text-emerald-400";
        else if (v === "Medium Confidence") color = "text-amber-400";
        else if (v === "Weak Match") color = "text-orange-400";
        return <span className={`text-xs ${color}`}>{v || "—"}</span>;
      },
    },
    {
      key: "source_inference_method",
      label: "Source Inference",
      render: (v) => <span className="text-xs text-muted">{v || "—"}</span>,
    },
    {
      key: "d2c_orders",
      label: "D2C Orders",
      render: (v) => (
        <span className="text-orange-400 font-semibold">{v ?? 0}</span>
      ),
    },
    {
      key: "d2c_spend",
      label: "D2C Spend",
      render: (v) => <span className="text-emerald-400">{fmtCurrency(v)}</span>,
    },
    {
      key: "d2c_products",
      label: "D2C Products",
      render: (v) => truncate((v || []).join(", "), 30),
    },
    { key: "invoice_date", label: "Invoice Date", render: (v) => fmtDate(v) },
    {
      key: "_journey",
      label: "Journey",
      render: (_, r) => (
        <button
          onClick={() => setJourneyEmail(r.email)}
          className="flex items-center gap-1 text-xs text-converted hover:text-purple-300 transition-colors"
        >
          <GitBranch size={12} /> View
        </button>
      ),
    },
  ];

  return (
    <div className="p-6 animate-slide-up">
      {journeyEmail && (
        <JourneyModal
          email={journeyEmail}
          onClose={() => setJourneyEmail(null)}
        />
      )}

      <div className="glass-card overflow-hidden">
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-sm font-semibold text-white">
            Converted Customers
            <span className="ml-2 text-xs text-muted">({total})</span>
          </h2>
          <div className="relative">
            <Search
              size={14}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-muted"
            />
            <input
              className="input-search pl-9 w-64"
              placeholder="Search email, phone…"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(1);
              }}
            />
          </div>
        </div>
        {loading ? (
          <TableSkeleton />
        ) : (
          <DataTable columns={columns} data={paginated} />
        )}
        <Pagination
          page={page}
          totalPages={totalPages}
          onPage={setPage}
          total={total}
          perPage={perPage}
        />
      </div>
    </div>
  );
}
