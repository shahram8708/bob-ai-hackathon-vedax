import { lazy, Suspense, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Layout } from "@/components/Layout";
import { Spinner } from "@/components/ui";
import { useSession } from "@/lib/session";
import { LoginPage } from "@/pages/Login";

const Overview = lazy(() => import("@/pages/Overview"));
const Schedule = lazy(() => import("@/pages/Schedule"));
const Operations = lazy(() => import("@/pages/Operations"));
const Vehicles = lazy(() => import("@/pages/Vehicles"));
const VehicleDetail = lazy(() => import("@/pages/VehicleDetail"));
const Trips = lazy(() => import("@/pages/Trips"));
const Alerts = lazy(() => import("@/pages/Alerts"));
const Energy = lazy(() => import("@/pages/Energy"));
const Reports = lazy(() => import("@/pages/Reports"));
const FleetMap = lazy(() => import("@/pages/FleetMap"));
const Infrastructure = lazy(() => import("@/pages/Infrastructure"));
const Tariffs = lazy(() => import("@/pages/Tariffs"));
const Settings = lazy(() => import("@/pages/Settings"));
const Audit = lazy(() => import("@/pages/Audit"));
const Driver = lazy(() => import("@/pages/Driver"));

function Guard({ perms, children }: { perms: string[]; children: ReactNode }) {
  const { can } = useSession();
  if (!can(...perms)) {
    return (
      <div className="panel mx-auto mt-10 max-w-md p-6 text-center">
        <p className="font-medium">You don’t have access to this page</p>
        <p className="mt-1 text-sm text-ink-3">Your role does not include the permission required to view it.</p>
      </div>
    );
  }
  return <>{children}</>;
}

function Home() {
  const { can } = useSession();
  if (can("dashboard:view")) return <Overview />;
  if (can("driver:self")) return <Navigate to="/driver" replace />;
  return <Navigate to="/vehicles" replace />;
}

export function App() {
  const { user, loading } = useSession();
  const location = useLocation();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner label="Starting ChargeOpt" />
      </div>
    );
  }
  if (!user) {
    return location.pathname === "/login" ? <LoginPage /> : <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  const page = (perms: string[], node: ReactNode) => <Guard perms={perms}>{node}</Guard>;
  return (
    <Suspense
      fallback={
        <div className="p-8">
          <Spinner />
        </div>
      }
    >
      <Routes>
        <Route path="/login" element={<Navigate to="/" replace />} />
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="schedule" element={page(["fleet:view"], <Schedule />)} />
          <Route path="operations" element={page(["fleet:view"], <Operations />)} />
          <Route path="vehicles" element={page(["fleet:view"], <Vehicles />)} />
          <Route path="vehicles/:id" element={page(["fleet:view"], <VehicleDetail />)} />
          <Route path="trips" element={page(["fleet:view"], <Trips />)} />
          <Route path="alerts" element={page(["dashboard:view"], <Alerts />)} />
          <Route path="energy" element={page(["dashboard:view"], <Energy />)} />
          <Route path="reports" element={page(["reports:view"], <Reports />)} />
          <Route path="map" element={page(["fleet:view"], <FleetMap />)} />
          <Route path="infrastructure" element={page(["fleet:view"], <Infrastructure />)} />
          <Route path="tariffs" element={page(["fleet:view"], <Tariffs />)} />
          <Route path="settings" element={page(["config:manage", "users:manage", "simulation:control"], <Settings />)} />
          <Route path="audit" element={page(["audit:view"], <Audit />)} />
          <Route path="driver" element={page(["driver:self"], <Driver />)} />
          <Route
            path="*"
            element={
              <div className="panel mx-auto mt-10 max-w-md p-6 text-center">
                <p className="font-medium">Page not found</p>
                <p className="mt-1 text-sm text-ink-3">Check the address or use the navigation.</p>
              </div>
            }
          />
        </Route>
      </Routes>
    </Suspense>
  );
}
