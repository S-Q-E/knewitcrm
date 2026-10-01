import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { AnalyticsFilters, AnalyticsSection, FunnelStage } from "@/api/analytics";
import { downloadAnalyticsCsv, useAnalyticsOverview, useDrillDeals } from "@/api/analytics";
import { usePipelines, useUsersLite } from "@/api/deals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Preset = "today" | "7" | "30" | "90" | "custom";

const PRESETS: { id: Preset; label: string }[] = [
  { id: "today", label: "Сегодня" },
  { id: "7", label: "7 дней" },
  { id: "30", label: "30 дней" },
  { id: "90", label: "90 дней" },
  { id: "custom", label: "Свой период" },
];

function toISODate(d: Date): string {
  const year = d.getFullYear();
  const month = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function resolveRange(
  preset: Preset,
  customFrom: string,
  customTo: string,
): {
  date_from: string;
  date_to: string;
} {
  const today = toISODate(new Date());
  if (preset === "today") return { date_from: today, date_to: today };
  if (preset === "custom") {
    return {
      date_from: customFrom || today,
      date_to: customTo || customFrom || today,
    };
  }
  const days = Number(preset);
  const from = new Date();
  from.setDate(from.getDate() - (days - 1));
  return { date_from: toISODate(from), date_to: today };
}

const number = new Intl.NumberFormat("ru-RU");

function formatMoney(value: number, currency: string): string {
  return `${number.format(value)} ${currency === "KZT" ? "₸" : currency}`;
}

function formatPercent(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(1)} %`;
}

function formatHours(value: number | null): string {
  if (value === null || value === undefined) return "—";
  if (value < 1) return `${Math.round(value * 60)} мин`;
  if (value < 48) return `${value.toFixed(1)} ч`;
  return `${(value / 24).toFixed(1)} дн`;
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Kpi({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
      <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}

function CsvButton({ section, filters }: { section: AnalyticsSection; filters: AnalyticsFilters }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <span className="inline-flex items-center gap-2">
      {error && <span className="text-xs text-red-600">{error}</span>}
      <Button
        variant="secondary"
        size="sm"
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError(null);
          downloadAnalyticsCsv(section, filters)
            .catch((err: Error) => setError(err.message))
            .finally(() => setBusy(false));
        }}
      >
        {busy ? "Готовим…" : "CSV"}
      </Button>
    </span>
  );
}

type SortDir = "asc" | "desc";

function useSort<T extends string>(initial: T) {
  const [key, setKey] = useState<T>(initial);
  const [dir, setDir] = useState<SortDir>("desc");
  const toggle = (next: T) => {
    if (next === key) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setKey(next);
      setDir("desc");
    }
  };
  const sortRows = <R,>(rows: R[], get: (row: R, key: T) => number | string | null): R[] => {
    return [...rows].sort((a, b) => {
      const va = get(a, key);
      const vb = get(b, key);
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      const cmp =
        typeof va === "number" && typeof vb === "number"
          ? va - vb
          : String(va).localeCompare(String(vb), "ru");
      return dir === "asc" ? cmp : -cmp;
    });
  };
  return { key, dir, toggle, sortRows };
}

function Th({
  label,
  active,
  dir,
  onClick,
}: {
  label: string;
  active: boolean;
  dir: SortDir;
  onClick: () => void;
}) {
  return (
    <th className="px-2 py-1.5 text-left font-medium">
      <button
        type="button"
        onClick={onClick}
        className="inline-flex items-center gap-1 hover:underline"
      >
        {label}
        <span
          className={cn(
            "text-[10px]",
            active ? "text-slate-900 dark:text-slate-100" : "text-slate-300 dark:text-slate-600",
          )}
        >
          {active ? (dir === "asc" ? "▲" : "▼") : "△"}
        </span>
      </button>
    </th>
  );
}

function DrillModal({
  stage,
  filters,
  onClose,
}: {
  stage: FunnelStage;
  filters: AnalyticsFilters;
  onClose: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const drill = useDrillDeals(stage.stage_id, filters, offset);
  const total = drill.data?.total ?? 0;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-2xl overflow-auto rounded-lg bg-white p-5 dark:bg-slate-900"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-base font-bold">Сделки на стадии «{stage.name}»</h3>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Закрыть
          </Button>
        </div>
        <p className="mb-3 text-xs text-slate-500">
          Когорта: сделки, созданные в выбранном периоде. Всего: {number.format(total)}
        </p>
        {drill.isPending && <p className="text-sm text-slate-500">Загрузка…</p>}
        {drill.isError && <p className="text-sm text-red-600">Не удалось загрузить сделки.</p>}
        {drill.data && (
          <>
            <table className="w-full text-sm">
              <tbody>
                {drill.data.items.map((deal) => (
                  <tr key={deal.id} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="py-2 pr-2">
                      <Link
                        to={`/deals/${deal.id}`}
                        className="font-medium text-sky-700 hover:underline dark:text-sky-400"
                      >
                        {deal.title}
                      </Link>
                      <span className="ml-2 text-xs text-slate-400">{deal.status}</span>
                    </td>
                    <td className="py-2 text-right text-slate-500">
                      {deal.amount !== null ? number.format(deal.amount) : "—"}
                    </td>
                  </tr>
                ))}
                {drill.data.items.length === 0 && (
                  <tr>
                    <td className="py-4 text-center text-slate-500">Нет сделок с таким фильтром</td>
                  </tr>
                )}
              </tbody>
            </table>
            <div className="mt-3 flex items-center justify-between">
              <Button
                variant="secondary"
                size="sm"
                disabled={offset === 0}
                onClick={() => setOffset((o) => Math.max(0, o - 20))}
              >
                Назад
              </Button>
              <span className="text-xs text-slate-500">
                {offset + 1}–{offset + drill.data.items.length} из {number.format(total)}
              </span>
              <Button
                variant="secondary"
                size="sm"
                disabled={offset + 20 >= total}
                onClick={() => setOffset((o) => o + 20)}
              >
                Дальше
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export function AnalyticsPage() {
  const today = toISODate(new Date());
  const [preset, setPreset] = useState<Preset>("30");
  const [customFrom, setCustomFrom] = useState(today);
  const [customTo, setCustomTo] = useState(today);
  const [pipelineId, setPipelineId] = useState("");
  const [ownerId, setOwnerId] = useState("");
  const [granularity, setGranularity] = useState<"day" | "week">("day");
  const [drill, setDrill] = useState<FunnelStage | null>(null);

  const pipelines = usePipelines();
  const users = useUsersLite();

  const range = resolveRange(preset, customFrom, customTo);
  const filters: AnalyticsFilters = useMemo(
    () => ({
      date_from: range.date_from,
      date_to: range.date_to,
      granularity,
      ...(pipelineId ? { pipeline_id: pipelineId } : {}),
      ...(ownerId ? { owner_id: ownerId } : {}),
    }),
    [range.date_from, range.date_to, granularity, pipelineId, ownerId],
  );
  const overview = useAnalyticsOverview(filters);

  const funnelSort = useSort<"reached" | "conversion_from_prev" | "avg_hours_on_stage" | "current">(
    "reached",
  );
  const managerSort = useSort<"deals_in_work" | "won" | "conversion" | "won_sum" | "tasks_overdue">(
    "won_sum",
  );

  const data = overview.data;
  const funnelRows = useMemo(
    () => (data ? funnelSort.sortRows(data.funnel.stages, (row, key) => row[key]) : []),
    [data, funnelSort],
  );
  const managerRows = useMemo(
    () => (data ? managerSort.sortRows(data.managers, (row, key) => row[key]) : []),
    [data, managerSort],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <div className="flex flex-wrap gap-1">
          {PRESETS.map((p) => (
            <Button
              key={p.id}
              variant={preset === p.id ? "default" : "secondary"}
              size="sm"
              onClick={() => setPreset(p.id)}
            >
              {p.label}
            </Button>
          ))}
        </div>
        {preset === "custom" && (
          <div className="flex items-center gap-2">
            <Input
              type="date"
              value={customFrom}
              max={customTo}
              onChange={(e) => setCustomFrom(e.target.value)}
              className="w-auto"
            />
            <span className="text-sm text-slate-500">—</span>
            <Input
              type="date"
              value={customTo}
              min={customFrom}
              max={today}
              onChange={(e) => setCustomTo(e.target.value)}
              className="w-auto"
            />
          </div>
        )}
        <select
          value={pipelineId}
          onChange={(e) => setPipelineId(e.target.value)}
          className="h-8 rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          title="Воронка"
        >
          <option value="">Все воронки</option>
          {pipelines.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <select
          value={ownerId}
          onChange={(e) => setOwnerId(e.target.value)}
          className="h-8 rounded-md border border-slate-200 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-900"
          title="Ответственный"
        >
          <option value="">Все менеджеры</option>
          {users.data?.items.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </select>
        <div className="flex gap-1">
          {(["day", "week"] as const).map((g) => (
            <Button
              key={g}
              variant={granularity === g ? "default" : "secondary"}
              size="sm"
              onClick={() => setGranularity(g)}
            >
              {g === "day" ? "По дням" : "По неделям"}
            </Button>
          ))}
        </div>
      </div>

      {overview.isPending && <p className="text-sm text-slate-500">Загрузка аналитики…</p>}
      {overview.isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700">
          Не удалось загрузить аналитику.{" "}
          <button type="button" className="underline" onClick={() => overview.refetch()}>
            Повторить
          </button>
        </div>
      )}

      {data && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <Kpi label="Новые лиды" value={number.format(data.summary.new_leads)} />
            <Kpi label="Записи на пробное" value={number.format(data.summary.trials_booked)} />
            <Kpi
              label="Продажи"
              value={`${number.format(data.summary.won_count)} · ${formatMoney(data.summary.won_sum, data.meta.currency)}`}
              hint={`Средний чек ${formatMoney(data.summary.avg_check, data.meta.currency)}`}
            />
            <Kpi label="Потери" value={number.format(data.summary.lost_count)} />
            <Kpi label="Конверсия общая" value={formatPercent(data.funnel.overall_conversion)} />
            <Kpi
              label="Без менеджера"
              value={formatPercent(data.bot.closed_without_manager_share)}
              hint={`${number.format(data.bot.closed_without_manager)} диалогов`}
            />
          </div>

          <Card title={`Воронка · когорта ${number.format(data.funnel.cohort_deals)} сделок`}>
            <div className="mb-2 flex justify-end">
              <CsvButton section="funnel" filters={filters} />
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={data.funnel.stages}
                  margin={{ top: 4, right: 8, bottom: 40, left: 0 }}
                  onClick={(state) => {
                    const stage = state?.activePayload?.[0]?.payload as FunnelStage | undefined;
                    if (stage) setDrill(stage);
                  }}
                >
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis
                    dataKey="name"
                    tick={{ fontSize: 11 }}
                    interval={0}
                    angle={-25}
                    textAnchor="end"
                    height={70}
                  />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip
                    formatter={(value, name) => {
                      if (name === "reached") return [value, "Дошло"];
                      return [value, name];
                    }}
                    labelFormatter={(label) => `Стадия: ${label} (клик — сделки)`}
                  />
                  <Bar dataKey="reached" name="Дошло" fill="#0ea5e9" className="cursor-pointer">
                    {data.funnel.stages.map((s) => (
                      <Cell key={s.stage_id} fill={s.is_bottleneck ? "#f59e0b" : "#0ea5e9"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-700">
                    <th className="px-2 py-1.5 text-left font-medium">Стадия</th>
                    <Th
                      label="Дошло"
                      active={funnelSort.key === "reached"}
                      dir={funnelSort.dir}
                      onClick={() => funnelSort.toggle("reached")}
                    />
                    <Th
                      label="Конверсия"
                      active={funnelSort.key === "conversion_from_prev"}
                      dir={funnelSort.dir}
                      onClick={() => funnelSort.toggle("conversion_from_prev")}
                    />
                    <Th
                      label="Время"
                      active={funnelSort.key === "avg_hours_on_stage"}
                      dir={funnelSort.dir}
                      onClick={() => funnelSort.toggle("avg_hours_on_stage")}
                    />
                    <Th
                      label="Сейчас"
                      active={funnelSort.key === "current"}
                      dir={funnelSort.dir}
                      onClick={() => funnelSort.toggle("current")}
                    />
                  </tr>
                </thead>
                <tbody>
                  {funnelRows.map((s) => (
                    <tr
                      key={s.stage_id}
                      className="border-b border-slate-100 dark:border-slate-800"
                    >
                      <td className="px-2 py-1.5">
                        <button
                          type="button"
                          className="text-left hover:underline"
                          onClick={() => setDrill(s)}
                        >
                          {s.name}
                        </button>
                        {s.is_bottleneck && (
                          <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-800 dark:bg-amber-900 dark:text-amber-200">
                            узкое место
                          </span>
                        )}
                      </td>
                      <td className="px-2 py-1.5">{number.format(s.reached)}</td>
                      <td className="px-2 py-1.5">{formatPercent(s.conversion_from_prev)}</td>
                      <td className="px-2 py-1.5">{formatHours(s.avg_hours_on_stage)}</td>
                      <td className="px-2 py-1.5">{number.format(s.current)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Динамика">
            <div className="mb-2 flex justify-end">
              <CsvButton section="dynamics" filters={filters} />
            </div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart
                  data={data.summary.dynamics}
                  margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="new_leads"
                    name="Новые лиды"
                    stroke="#0ea5e9"
                    dot={false}
                  />
                  <Line
                    type="monotone"
                    dataKey="trials"
                    name="Записи"
                    stroke="#8b5cf6"
                    dot={false}
                  />
                  <Line type="monotone" dataKey="won" name="Продажи" stroke="#16a34a" dot={false} />
                  <Line type="monotone" dataKey="lost" name="Потери" stroke="#dc2626" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card title="Потери по причинам">
              <div className="mb-2 flex justify-end">
                <CsvButton section="lost_reasons" filters={filters} />
              </div>
              {data.summary.lost_by_reason.length === 0 ? (
                <p className="text-sm text-slate-500">Потерь за период нет</p>
              ) : (
                <table className="w-full text-sm">
                  <tbody>
                    {data.summary.lost_by_reason.map((r) => (
                      <tr
                        key={r.reason}
                        className="border-b border-slate-100 dark:border-slate-800"
                      >
                        <td className="px-2 py-1.5">{r.reason}</td>
                        <td className="px-2 py-1.5 text-right">{number.format(r.count)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
            <Card title="Источники">
              <div className="mb-2 flex justify-end">
                <CsvButton section="sources" filters={filters} />
              </div>
              {data.sources.length === 0 ? (
                <p className="text-sm text-slate-500">Нет данных</p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-700">
                      <th className="px-2 py-1.5 text-left font-medium">Источник</th>
                      <th className="px-2 py-1.5 text-right font-medium">Контакты</th>
                      <th className="px-2 py-1.5 text-right font-medium">Продажи</th>
                      <th className="px-2 py-1.5 text-right font-medium">Сумма</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sources.map((s) => (
                      <tr
                        key={s.source}
                        className="border-b border-slate-100 dark:border-slate-800"
                      >
                        <td className="px-2 py-1.5">{s.source}</td>
                        <td className="px-2 py-1.5 text-right">{number.format(s.contacts)}</td>
                        <td className="px-2 py-1.5 text-right">{number.format(s.won)}</td>
                        <td className="px-2 py-1.5 text-right">
                          {formatMoney(s.won_sum, data.meta.currency)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Card>
          </div>

          <Card title="Менеджеры">
            <div className="mb-2 flex justify-end">
              <CsvButton section="managers" filters={filters} />
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-700">
                    <th className="px-2 py-1.5 text-left font-medium">Менеджер</th>
                    <Th
                      label="В работе"
                      active={managerSort.key === "deals_in_work"}
                      dir={managerSort.dir}
                      onClick={() => managerSort.toggle("deals_in_work")}
                    />
                    <Th
                      label="Выиграно"
                      active={managerSort.key === "won"}
                      dir={managerSort.dir}
                      onClick={() => managerSort.toggle("won")}
                    />
                    <Th
                      label="Конверсия"
                      active={managerSort.key === "conversion"}
                      dir={managerSort.dir}
                      onClick={() => managerSort.toggle("conversion")}
                    />
                    <Th
                      label="Сумма"
                      active={managerSort.key === "won_sum"}
                      dir={managerSort.dir}
                      onClick={() => managerSort.toggle("won_sum")}
                    />
                    <th className="px-2 py-1.5 text-left font-medium">Первый ответ</th>
                    <th className="px-2 py-1.5 text-left font-medium">
                      Задачи (готово/просрочено)
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {managerRows.map((m) => (
                    <tr key={m.user_id} className="border-b border-slate-100 dark:border-slate-800">
                      <td className="px-2 py-1.5 font-medium">{m.name}</td>
                      <td className="px-2 py-1.5">{number.format(m.deals_in_work)}</td>
                      <td className="px-2 py-1.5">
                        {number.format(m.won)} / {number.format(m.lost)}
                      </td>
                      <td className="px-2 py-1.5">{formatPercent(m.conversion)}</td>
                      <td className="px-2 py-1.5">{formatMoney(m.won_sum, data.meta.currency)}</td>
                      <td className="px-2 py-1.5">
                        {m.avg_first_response_hours === null
                          ? "—"
                          : formatHours(m.avg_first_response_hours)}
                      </td>
                      <td className="px-2 py-1.5">
                        {number.format(m.tasks_done)} /{" "}
                        <span className={cn(m.tasks_overdue > 0 && "font-semibold text-red-600")}>
                          {number.format(m.tasks_overdue)}
                        </span>
                      </td>
                    </tr>
                  ))}
                  {managerRows.length === 0 && (
                    <tr>
                      <td className="px-2 py-4 text-center text-slate-500" colSpan={7}>
                        Нет данных
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </Card>

          <Card title="Бот">
            <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-4">
              <Kpi
                label="Сообщения in/out"
                value={`${number.format(data.bot.messages_in)} / ${number.format(data.bot.messages_out)}`}
              />
              <Kpi
                label="Среднее время ответа"
                value={
                  data.bot.avg_response_time_ms === null
                    ? "—"
                    : `${number.format(Math.round(data.bot.avg_response_time_ms))} мс`
                }
              />
              <Kpi label="Токены всего" value={number.format(data.bot.tokens_total)} />
              <Kpi
                label="Передачи менеджеру"
                value={`${number.format(data.bot.handover_count)} · ${formatPercent(data.bot.handover_share)}`}
              />
            </div>
            <div className="h-48">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart
                  data={data.bot.tokens_by_day}
                  margin={{ top: 4, right: 8, bottom: 4, left: 0 }}
                >
                  <CartesianGrid strokeDasharray="3 3" opacity={0.3} />
                  <XAxis dataKey="bucket" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
                  <Tooltip formatter={(value) => [value, "Токены"]} />
                  <Bar dataKey="tokens" name="Токены" fill="#8b5cf6" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <div className="mt-3 grid gap-4 lg:grid-cols-2">
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-sm font-semibold">Топ возражений</h3>
                  <CsvButton section="objections" filters={filters} />
                </div>
                {data.bot.top_objections.length === 0 ? (
                  <p className="text-sm text-slate-500">Нет данных</p>
                ) : (
                  <table className="w-full text-sm">
                    <tbody>
                      {data.bot.top_objections.map((o) => (
                        <tr
                          key={o.objection}
                          className="border-b border-slate-100 dark:border-slate-800"
                        >
                          <td className="px-2 py-1.5">{o.objection}</td>
                          <td className="px-2 py-1.5 text-right">{number.format(o.count)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <h3 className="text-sm font-semibold">Где застревают лиды</h3>
                  <CsvButton section="abandoned" filters={filters} />
                </div>
                {data.bot.abandoned_by_stage.length === 0 ? (
                  <p className="text-sm text-slate-500">Нет данных</p>
                ) : (
                  <table className="w-full text-sm">
                    <tbody>
                      {data.bot.abandoned_by_stage.map((a) => (
                        <tr
                          key={a.stage}
                          className="border-b border-slate-100 dark:border-slate-800"
                        >
                          <td className="px-2 py-1.5">{a.stage}</td>
                          <td className="px-2 py-1.5 text-right">
                            {number.format(a.count)} · {formatPercent(a.share)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </Card>

          <Card title="Теги">
            <div className="mb-2 flex justify-end">
              <CsvButton section="tags" filters={filters} />
            </div>
            {data.tags.length === 0 ? (
              <p className="text-sm text-slate-500">Нет данных</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-700">
                    <th className="px-2 py-1.5 text-left font-medium">Тег</th>
                    <th className="px-2 py-1.5 text-right font-medium">Сделки</th>
                    <th className="px-2 py-1.5 text-right font-medium">Продажи</th>
                    <th className="px-2 py-1.5 text-right font-medium">Сумма</th>
                  </tr>
                </thead>
                <tbody>
                  {data.tags.map((t) => (
                    <tr key={t.tag_id} className="border-b border-slate-100 dark:border-slate-800">
                      <td className="px-2 py-1.5">{t.tag}</td>
                      <td className="px-2 py-1.5 text-right">{number.format(t.deals)}</td>
                      <td className="px-2 py-1.5 text-right">{number.format(t.won)}</td>
                      <td className="px-2 py-1.5 text-right">
                        {formatMoney(t.won_sum, data.meta.currency)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </>
      )}

      {drill && data && (
        <DrillModal stage={drill} filters={filters} onClose={() => setDrill(null)} />
      )}
    </div>
  );
}
