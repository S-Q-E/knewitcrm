import {
  BarChart3,
  Bell,
  Coins,
  LogOut,
  MessagesSquare,
  Moon,
  Search,
  Settings,
  Sun,
  Users,
} from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useLogout, useMe } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/deals", label: "Сделки", icon: Coins, adminOnly: false },
  { to: "/dialogs", label: "Диалоги", icon: MessagesSquare, adminOnly: false },
  { to: "/contacts", label: "Контакты", icon: Users, adminOnly: false },
  { to: "/tasks", label: "Задачи", icon: Bell, adminOnly: false },
  { to: "/analytics", label: "Аналитика", icon: BarChart3, adminOnly: false },
  { to: "/settings", label: "Настройки", icon: Settings, adminOnly: true },
];

export function Layout() {
  const { data: me } = useMe();
  const logout = useLogout();
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);

  const onSearch = (event: FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    navigate(trimmed ? `/contacts?q=${encodeURIComponent(trimmed)}` : "/contacts");
  };

  const onLogout = async () => {
    try {
      await logout.mutateAsync();
    } catch {
      // Session may already be gone; still leave.
    }
    navigate("/login", { replace: true });
  };

  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="flex w-16 flex-col items-center gap-1 border-r border-slate-200 bg-white py-3 dark:border-slate-800 dark:bg-slate-900 md:w-20">
        <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-sm font-bold text-white dark:bg-slate-100 dark:text-slate-900">
          K
        </div>
        {NAV.filter((item) => !item.adminOnly || me?.role === "admin").map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            title={item.label}
            className={({ isActive }) =>
              cn(
                "flex h-11 w-11 flex-col items-center justify-center gap-0.5 rounded-lg text-slate-500 hover:bg-slate-100 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-slate-100",
                isActive &&
                  "bg-slate-900 text-white hover:text-white dark:bg-slate-100 dark:text-slate-900 dark:hover:text-slate-900",
              )
            }
          >
            <item.icon className="h-5 w-5" />
            <span className="hidden text-[10px] leading-none md:block">{item.label}</span>
          </NavLink>
        ))}
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-900 md:gap-4 md:px-6">
          <form onSubmit={onSearch} className="relative w-full max-w-md">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Глобальный поиск: контакты и сделки"
              className="pl-9"
            />
          </form>
          <div className="ml-auto flex items-center gap-1 md:gap-2">
            <Button variant="ghost" size="icon" onClick={toggle} title="Переключить тему">
              {theme === "dark" ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
            </Button>
            <div className="relative">
              <Button
                variant="ghost"
                size="icon"
                title="Уведомления"
                onClick={() => {
                  setBellOpen((open) => !open);
                  setMenuOpen(false);
                }}
              >
                <Bell className="h-5 w-5" />
              </Button>
              {bellOpen && (
                <div className="absolute right-0 z-20 mt-2 w-64 rounded-md border border-slate-200 bg-white p-4 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900">
                  <p className="font-medium">Уведомления</p>
                  <p className="mt-1 text-slate-500 dark:text-slate-400">
                    Пока нет новых уведомлений.
                  </p>
                </div>
              )}
            </div>
            <div className="relative">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setMenuOpen((open) => !open);
                  setBellOpen(false);
                }}
              >
                {me?.name ?? "Меню"}
              </Button>
              {menuOpen && (
                <div className="absolute right-0 z-20 mt-2 w-56 rounded-md border border-slate-200 bg-white p-2 text-sm shadow-lg dark:border-slate-700 dark:bg-slate-900">
                  <div className="px-2 py-1.5">
                    <p className="font-medium">{me?.name}</p>
                    <p className="text-slate-500 dark:text-slate-400">{me?.email}</p>
                  </div>
                  <button
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left hover:bg-slate-100 dark:hover:bg-slate-800"
                    onClick={() => {
                      void onLogout();
                    }}
                  >
                    <LogOut className="h-4 w-4" />
                    Выйти
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main className="min-w-0 flex-1 p-3 md:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
