import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import Overview from "./pages/Overview";
import ReviewDetail from "./pages/ReviewDetail";
import Reviews from "./pages/Reviews";
import "./styles.css";

function App() {
  return (
    <div className="shell">
      <aside className="nav">
        <div className="brand">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden>
            <rect width="32" height="32" rx="8" className="brand-bg" />
            <path d="M9 12l-4 4 4 4M23 12l4 4-4 4M18 9l-4 14" className="brand-mark" />
          </svg>
          <span>Review Agent</span>
        </div>
        <NavLink to="/" end>Overview</NavLink>
        <NavLink to="/reviews">Reviews</NavLink>
        <a className="nav-foot" href="/docs" target="_blank" rel="noreferrer">API docs ↗</a>
      </aside>
      <main>
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/reviews" element={<Reviews />} />
          <Route path="/reviews/:id" element={<ReviewDetail />} />
        </Routes>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
