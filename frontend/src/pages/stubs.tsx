import { useSearchParams } from "react-router-dom";

export function StubPage({ title, hint }: { title: string; hint: string }) {
  const [params] = useSearchParams();
  const query = params.get("q");
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
      <h1 className="text-xl font-bold">{title}</h1>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{hint}</p>
      {query && (
        <p className="mt-2 text-sm">
          Поиск: <span className="font-medium">{query}</span>
        </p>
      )}
    </div>
  );
}

export function DealsPage() {
  return <StubPage title="Сделки (legacy)" hint="Старая заглушка, заменена канбаном." />;
}

export function ContactsPage() {
  return (
    <StubPage
      title="Контакты"
      hint="Список контактов с поиском появится здесь на следующем шаге."
    />
  );
}

export function AnalyticsPage() {
  return <StubPage title="Аналитика" hint="Воронка и отчёты появятся здесь на следующем шаге." />;
}

export function SettingsPage() {
  return (
    <StubPage title="Настройки" hint="Настройки CRM, воронка и пользователи (только для админа)." />
  );
}

export function ForbiddenPage() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-6 dark:border-slate-800 dark:bg-slate-900">
      <h1 className="text-xl font-bold">Нет доступа</h1>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
        Этот раздел доступен только администраторам.
      </p>
    </div>
  );
}
