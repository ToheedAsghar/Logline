import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/layout/AppShell";
import { RequireAuth } from "@/layout/RequireAuth";
import { GapDetector, History, Login, OutputComposer, Settings, Signup, StyleGuide, Timeline } from "@/pages";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
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
