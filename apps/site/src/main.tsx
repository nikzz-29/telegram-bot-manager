import { createRoot } from "react-dom/client";
import { SiteApp } from "./SiteApp";
import "./site.css";

const root = document.getElementById("root");
if (!root) throw new Error("Missing site root");
createRoot(root).render(<SiteApp />);
