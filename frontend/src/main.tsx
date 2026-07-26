import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { initializeStoredTheme } from "./theme";
import "./styles.css";

initializeStoredTheme();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
