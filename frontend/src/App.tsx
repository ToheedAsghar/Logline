import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/layout/AppShell";
import { RequireAuth } from "@/layout/RequireAuth";
import {
  ForgotPassword,
  GapDetector,
  History,
  Login,
  OAuthCallback,
  OutputComposer,
  ResetPassword,
  Settings,
  Signup,
  StyleGuide,
  Timeline,
  VerifyEmail,
} from "@/pages";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route path="/verify-email" element={<VerifyEmail />} />
      <Route path="/oauth/callback" element={<OAuthCallback />} />
      <Route path="/styleguide" element={<StyleGuide />} />

      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="/" element={<Timeline />} />
        <Route path="/gaps" element={<GapDetector />} />
        <Route path="/compose" element={<OutputComposer />} />
        <Route path="/history" element={<History />} />
        <Route path="/settings" element={<Settings />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
