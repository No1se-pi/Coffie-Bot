import { BrowserRouter, Outlet, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { AuthGate, NotFoundPage, RoleGuard } from "./components/AppShell";
import {
  CardPage,
  HistoryPage,
  HomePage,
  MenuPage,
  MorePage,
  PostPurchasePage,
  RewardsPage,
} from "./pages/customer";
import { LoyaltyPage } from "./pages/loyalty";
import {
  AccrualPanel,
  ClientPreviewPage,
  RecentOperationsPage,
  ScannerPage,
  StaffHomePage,
  StaffProfilePage,
  StaffWorkspaceProvider,
} from "./pages/staff";
import {
  AdminAdjustmentPage,
  AdminCustomerMergePage,
  AdminEventsPage,
  AdminFeedbackPage,
  AdminMenuPage,
  AdminOverviewPage,
  AdminPromotionsPage,
  AdminSettingsPage,
  AdminStaffPage,
  AdminUsersPage,
} from "./pages/admin";
import { AdminPricingPage } from "./pages/admin-pricing";

export { AccrualPanel };

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <StaffWorkspaceProvider>
          <Routes>
            <Route element={<AuthGate />}>
              <Route
                path="after-purchase/:operationId"
                element={<PostPurchasePage />}
              />
              <Route
                element={
                  <RoleGuard allow={["customer"]}>
                    <Outlet />
                  </RoleGuard>
                }
              >
                <Route index element={<HomePage />} />
                <Route path="card" element={<CardPage />} />
                <Route path="rewards" element={<RewardsPage />} />
                <Route path="history" element={<HistoryPage />} />
                <Route path="loyalty" element={<LoyaltyPage />} />
                <Route path="menu" element={<MenuPage />} />
                <Route path="more" element={<MorePage />} />
              </Route>
              <Route
                path="staff"
                element={
                  <RoleGuard allow={["staff", "admin", "owner"]}>
                    <Outlet />
                  </RoleGuard>
                }
              >
                <Route index element={<StaffHomePage />} />
                <Route path="scan" element={<ScannerPage />} />
                <Route path="client/:userId" element={<ClientPreviewPage />} />
                <Route path="recent" element={<RecentOperationsPage />} />
                <Route path="profile" element={<StaffProfilePage />} />
              </Route>
              <Route
                path="admin"
                element={
                  <RoleGuard allow={["admin", "owner"]}>
                    <Outlet />
                  </RoleGuard>
                }
              >
                <Route index element={<AdminOverviewPage />} />
                <Route path="users" element={<AdminUsersPage />} />
                <Route
                  path="customer-merge"
                  element={<AdminCustomerMergePage />}
                />
                <Route path="staff" element={<AdminStaffPage />} />
                <Route
                  path="users/:userId/adjust"
                  element={<AdminAdjustmentPage />}
                />
                <Route path="events" element={<AdminEventsPage />} />
                <Route path="feedback" element={<AdminFeedbackPage />} />
                <Route path="settings" element={<AdminSettingsPage />} />
                <Route path="menu" element={<AdminMenuPage />} />
                <Route path="promotions" element={<AdminPromotionsPage />} />
                <Route path="pricing" element={<AdminPricingPage />} />
              </Route>
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </StaffWorkspaceProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
