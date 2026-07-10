import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { LayoutModeProvider } from "./lib/layoutMode";
import "./theme.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <LayoutModeProvider>
        <App />
      </LayoutModeProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
