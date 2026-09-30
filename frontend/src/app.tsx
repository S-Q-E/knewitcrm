import { Navigate, Route, Routes } from "react-router-dom";

import { useMe } from "@/api/auth";
import { Layout } from "@/components/layout";
import { LoginPage } from "@/pages/login";
import { AnalyticsPage, ContactsPage, ForbiddenPage, SettingsPage } from "@/pages/stubs";
import { DealPage } from "@/pages/deal";
import { DealsPage } from "@/pages/deals";
import { DialogsPage } from "@/pages/dialogs";
import { TasksPage } from "@/pages/tasks";

function RequireAuth({ children }: { children: JSX.Element }) {
  const me = useMe();
  if (me.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Загрузка…
      </div>
    );
  }
  if (me.isError || !me.data) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  const me = useMe();
  if (me.isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-slate-500">
        Загрузка…
      </div>
    );
  }
  if (me.isError || !me.data) {
    return <Navigate to="/login" replace />;
  }
  if (me.data.role !== "admin") {
    return <ForbiddenPage />;
  }
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Navigate to="/deals" replace />} />
        <Route path="/deals" element={<DealsPage />} />
        <Route path="/deals/:id" element={<DealPage />} />
        <Route path="/dialogs" element={<DialogsPage />} />
        <Route path="/contacts" element={<ContactsPage />} />
        <Route path="/tasks" element={<TasksPage />} />
        <Route path="/analytics" element={<AnalyticsPage />} />
        <Route
          path="/settings"
          element={
            <RequireAdmin>
              <SettingsPage />
            </RequireAdmin>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
