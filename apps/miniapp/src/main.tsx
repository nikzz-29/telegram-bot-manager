import React from "react";
import { createRoot } from "react-dom/client";

function App(): React.JSX.Element {
  return <main><h1>Telegram Bot Manager</h1><p>Mini App skeleton — settings are coming next.</p></main>;
}

createRoot(document.getElementById("root")!).render(<App />);
