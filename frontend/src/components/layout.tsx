import {
  BarChart3,
  Bell,
  Coins,
  LogOut,
  MessagesSquare,
  Moon,
  MoreHorizontal,
  Search,
  Settings,
  Sun,
  Users,
} from "lucide-react";
import { useState } from "react";
import type { FormEvent } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useLogout, useMe } from "@/api/auth";
import { useEventStream } from "@/api/stream";
import { BellBadge, BellDropdown } from "@/components/bell";
import { RealtimeStatus } from "@/components/realtime-status";
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
  { to: "/settings", label: "Настройки", icon: Settings, adminOnly: false },
];

export function Layout() {
  const { data: me } = useMe();
  useEventStream();
  const logout = useLogout();
  const navigate = useNavigate();
  const { theme, toggle } = useTheme();
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

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

  const visibleNav = NAV.filter((item) => !item.adminOnly || me?.role === "admin");
  // На телефоне в нижний бар влезает 5 слотов: 4 раздела + «Ещё».
  const tabNav = visibleNav.slice(0, 4);
  const moreNav = visibleNav.slice(4);

  return (
    <div className="flex min-h-screen bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
      <aside className="hidden w-16 flex-col items-center gap-1 border-r border-slate-200 bg-white py-3 dark:border-slate-800 dark:bg-slate-900 md:flex md:w-20">
        <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-lg bg-slate-900 text-sm font-bold text-white dark:bg-slate-100 dark:text-slate-900">
          K
        </div>
        {visibleNav.map((item) => (
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
        <header className="flex flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-slate-900 md:gap-4 md:px-6">
          <form
            onSubmit={onSearch}
            className="relative order-first w-full md:order-none md:w-auto md:min-w-0 md:flex-1 md:max-w-md"
          >
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Глобальный поиск: контакты и сделки"
              className="pl-9"
            />
          </form>
          <div className="ml-auto flex items-center gap-1 md:gap-2">
            <RealtimeStatus />
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
                <span className="relative">
                  <Bell className="h-5 w-5" />
                  <BellBadge />
                </span>
              </Button>
              {bellOpen && <BellDropdown onClose={() => setBellOpen(false)} />}
            </div>
            <div className="relative">
              <Button
                variant="ghost"
                size="sm"
                className="max-w-32 truncate md:max-w-none"
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
        <main className="min-w-0 flex-1 p-3 pb-24 md:p-6 md:pb-6">
          <Outlet />
        </main>
      </div>

      <nav
        aria-label="Основная навигация"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900 md:hidden"
        style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      >
        <div className="flex items-stretch">
          {tabNav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setMoreOpen(false)}
              className={({ isActive }) =>
                cn(
                  "flex min-h-11 flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-slate-500 dark:text-slate-400",
                  isActive && "text-slate-900 dark:text-slate-100",
                )
              }
            >
              <item.icon className="h-5 w-5" />
              <span className="text-[10px] leading-none">{item.label}</span>
            </NavLink>
          ))}
          {moreNav.length > 0 && (
            <div className="relative flex-1">
              <button
                type="button"
                aria-expanded={moreOpen}
                onClick={() => setMoreOpen((open) => !open)}
                className={cn(
                  "flex min-h-11 w-full flex-col items-center justify-center gap-0.5 py-1.5 text-slate-500 dark:text-slate-400",
                  moreOpen && "text-slate-900 dark:text-slate-100",
                )}
              >
                <MoreHorizontal className="h-5 w-5" />
                <span className="text-[10px] leading-none">Ещё</span>
              </button>
              {moreOpen && (
                <div className="absolute inset-x-2 bottom-full mb-2 rounded-lg border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
                  {moreNav.map((item) => (
                    <NavLink
                      key={item.to}
                      to={item.to}
                      onClick={() => setMoreOpen(false)}
                      className={({ isActive }) =>
                        cn(
                          "flex min-h-11 items-center gap-2 rounded-md px-3 text-sm text-slate-600 dark:text-slate-300",
                          isActive &&
                            "bg-slate-100 font-medium text-slate-900 dark:bg-slate-800 dark:text-slate-100",
                        )
                      }
                    >
                      <item.icon className="h-5 w-5" />
                      {item.label}
                    </NavLink>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </nav>
    </div>
  );
}
