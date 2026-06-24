import React from "react";
import ReactDOM from "react-dom/client";
import ChatWidget from "../components/ChatWidget";
import "./index.css";

ReactDOM.createRoot(document.getElementById("widget-root")!).render(
  <React.StrictMode>
    <ChatWidget />
  </React.StrictMode>
);
